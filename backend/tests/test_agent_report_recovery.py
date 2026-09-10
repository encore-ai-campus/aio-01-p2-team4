"""WU-B6 보고서의 AGT-009~012와 복구 기록 경계를 합성 상태로 반복 검증한다.

각 pytest 항목은 새 저장소·Provider·MCP 전송 대역을 사용한다. 저장소 대역은
행의 읽기·쓰기와 transaction 복원만 수행하며, 실제 Orchestrator, MCP client,
command service와 GameEngine이 stale·중복·fallback·제출 여부를 판정한다.
기본 반복 수는 50이며 개발 확인만 AGENT_REPORT_SAMPLES=1로 줄일 수 있다.
실제 PostgreSQL SQL 제약, 동시 잠금, 외부 MCP 서버와 LLM 품질은 측정하지 않는다.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from threading import RLock
from types import SimpleNamespace
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
import psycopg
import pytest

from backend.app.agent.activity import FAILURE_REASONS, AgentActivity
from backend.app.agent.orchestrator import AgentJobSpec, AgentOrchestrator
from backend.app.agent.projections import build_context
from backend.app.infrastructure.transaction import TransactionManager
from backend.app.llm_provider.base import LLMResponse
from backend.app.mcp.client import FastMcpGameContextClient, McpContextError
from backend.app.models.enums import GamePhase, PlayerKind, PlayerRole
from backend.app.models.game_state import GameState, PlayerState
from backend.app.repositories.action_repository import PostgresActionRepository
from backend.app.repositories.agent_repository import AgentReservation, CapabilityGrant
from backend.app.repositories.game_repository import GameStateKeyring
from backend.app.schemas.command_schema import GameCommandRequest
from backend.app.services.game.action_command import PostgresActionCommandService
from backend.app.services.game.actor_context import ActorContext
from backend.app.services.game.agent_discussion import PostgresAgentDiscussionService
from backend.app.services.game.postgres_helpers import restore_locked_game
from backend.app.services.game.postgres_runtime import PostgresGameRuntime
from backend.app.services.game.window_service import next_window
from backend.app.core.errors import ApiError


NOW = datetime(2026, 9, 9, 6, 0, tzinfo=UTC)
SAMPLE_COUNT = int(os.environ.get("AGENT_REPORT_SAMPLES", "50"))
if SAMPLE_COUNT < 1:
    raise ValueError("AGENT_REPORT_SAMPLES는 1 이상의 정수여야 합니다.")
SAMPLES = pytest.mark.parametrize(
    "sample_index", range(SAMPLE_COUNT), ids=lambda value: f"sample_{value:03d}"
)


class FrozenDateTime(datetime):
    """실시간 마감이나 로컬 시간대가 합성 시험의 결과를 바꾸지 않게 한다."""

    @classmethod
    def now(cls, tz=None):
        return NOW.replace(tzinfo=None) if tz is None else NOW.astimezone(tz)


class MemoryLog:
    """운영 로그 파일을 열지 않고 실제 직렬화 결과만 메모리에 보관한다."""

    def __init__(self):
        self.lines = []

    def info(self, message, *args):
        self.lines.append(message % args if args else message)

    warning = info

    def records(self):
        return [json.loads(line) for line in self.lines]


@pytest.fixture(autouse=True)
def isolated_boundaries(monkeypatch):
    """시계·로그·네트워크만 격리하며 검증 함수나 게임 제출 함수를 바꾸지 않는다."""

    sink = MemoryLog()
    for module in (
        "backend.app.agent.orchestrator",
        "backend.app.agent.activity",
        "backend.app.services.game.discussion_transaction",
        "backend.app.services.game.action_command",
        "backend.app.game_engine.phases.transition",
    ):
        monkeypatch.setattr(f"{module}.datetime", FrozenDateTime)
    for module in (
        "backend.app.agent.orchestrator",
        "backend.app.agent.activity",
        "backend.app.core.logging",
    ):
        monkeypatch.setattr(f"{module}.progress_logger", lambda: sink)

    def reject_external(*args, **kwargs):
        pytest.fail("이 시험에서는 외부 네트워크와 실제 DB 연결을 사용할 수 없습니다.")

    monkeypatch.setattr(psycopg, "connect", reject_external)
    monkeypatch.setattr(socket.socket, "connect", reject_external)
    monkeypatch.setattr(socket, "create_connection", reject_external)
    return sink


class RowCursor:
    """저장소 대역 밖에 남은 잠금 SQL과 투표 버전 증거 조회만 수용한다."""

    def __init__(self, ledger):
        self.ledger = ledger
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params):
        sql = " ".join(query.split())
        self.ledger.sql.append(sql)
        if sql == "SELECT pg_advisory_xact_lock(%s)":
            self.result = None
        elif sql.startswith("SELECT 1 FROM public.action_submissions AS submission"):
            game_id, window_id, version = params
            self.result = next(({"one": 1} for row in self.ledger.data["submissions"]
                                if row["game_id"] == game_id and row["window_id"] == window_id
                                and row["action_type"] == "VOTE" and row["source"] == "HUMAN"
                                and row["observed_state_version"] == version
                                and self.ledger.get_kind(
                                    self, game_id=game_id, player_id=row["actor_player_id"]
                                ) == "HUMAN"), None)
        else:
            raise AssertionError("저장소 fixture가 지원하지 않는 SQL 경로입니다.")

    def fetchone(self):
        return deepcopy(self.result)


class RowConnection:
    """실제 TransactionManager에 연결 대역을 제공하고 실패 시 모든 행을 복원한다."""

    def __init__(self, ledger):
        self.ledger = ledger

    def __enter__(self):
        self.before = deepcopy(self.ledger.data)
        return self

    def __exit__(self, error_type, error, traceback):
        if error_type is not None:
            self.ledger.data = self.before
            self.ledger.rollbacks += 1
        else:
            self.ledger.commits += 1
        return False

    def cursor(self, **kwargs):
        return RowCursor(self.ledger)


class SyntheticLedger:
    """입력 행을 보관할 뿐 API 성공·거부나 엔진 결과를 만들어내지 않는 저장소다.

    제출에 중복 unique 제약을 구현하지 않는다. 두 번째 제출을 차단하는 근거는
    실제 service의 receipt 비교와 실제 엔진의 기존 제출 복원·중복 검사여야 한다.
    쓰기 실패 표식은 원장 반영 뒤 예외를 주입해 부분 쓰기 rollback을 확인한다.
    """

    vote_version_is_current = staticmethod(PostgresActionRepository.vote_version_is_current)

    def __init__(self, state, owner, identify):
        self.identify = identify
        seed = GameStateKeyring.legacy_plaintext().encrypt_seed(state.seed)
        self.data = {
            "game": {
                "id": state.game_id, "owner_user_id": owner,
                "phase": state.phase.value, "status": state.status.value,
                "round": state.round, "day_number": state.day_number,
                "state_version": state.state_version, "updated_at": NOW,
                "player_count": len(state.players), "mode": "STANDARD",
                "fast_forward_enabled": False, "seed_ciphertext": seed.ciphertext,
                "seed_nonce": seed.nonce, "seed_key_id": seed.key_id,
            },
            "players": [
                {"id": player.player_id, "seat": player.seat, "role": player.role.value,
                 "kind": player.kind.value, "display_name": player.display_name,
                 "alive": player.alive, "faction": player.faction.value,
                 "user_id": owner if player.kind is PlayerKind.HUMAN else None}
                for player in state.players
            ],
            "windows": [], "submissions": [], "events": [], "outbox": [],
            "receipts": {}, "front_sequence": 0,
        }
        self.sql = []
        self.writes = []
        self.commits = 0
        self.rollbacks = 0
        self.fail_on = None
        self.open_window(None, next_window(state, NOW))
        self.writes.clear()

    def lock_game(self, cursor, game_id):
        return deepcopy(self.data["game"]) if self.data["game"]["id"] == game_id else None

    def list_players(self, cursor, *, game_id):
        return deepcopy(self.data["players"]) if self.data["game"]["id"] == game_id else []

    def get_kind(self, cursor, *, game_id, player_id):
        return next((row["kind"] for row in self.list_players(cursor, game_id=game_id)
                     if row["id"] == player_id), None)

    def current_window(self, cursor, *, game_id):
        return next((deepcopy(row) for row in reversed(self.data["windows"])
                     if row["game_id"] == game_id and row["status"] == "OPEN"), None)

    def open_window(self, cursor, window):
        row = asdict(window)
        row["id"] = row.pop("window_id")
        row.update(status="OPEN", opened_at=NOW)
        self.data["windows"].append(row)
        self.writes.append("window")

    def cancel_current_window(self, cursor, *, game_id):
        for row in self.data["windows"]:
            if row["game_id"] == game_id and row["status"] == "OPEN":
                row["status"] = "CANCELLED"
        self.writes.append("cancel")

    def list_discussion_submissions(self, cursor, *, game_id, phase, round, cycle):
        return deepcopy([row for row in self.data["submissions"]
                         if row["game_id"] == game_id and row["phase"] == phase
                         and row["round"] == round and row["cycle"] == cycle])

    def recent_discussion_actions(self, cursor, *, game_id, since):
        return deepcopy([row for row in self.data["submissions"]
                         if row["game_id"] == game_id and row["submitted_at"] > since
                         and row["action_type"] in {"SPEAK", "PASS"}])

    def list_window_action_submissions(self, cursor, *, window_id):
        return deepcopy([row for row in self.data["submissions"]
                         if row["window_id"] == window_id])

    def insert_submission(self, cursor, submission):
        row = asdict(submission)
        window = next(item for item in self.data["windows"] if item["id"] == row["window_id"])
        row.update(submitted_at=NOW, phase=window["phase"], round=window["round"],
                   cycle=window["cycle"])
        self.data["submissions"].append(row)
        self.writes.append("submission")
        if self.fail_on == "second_submission" and len(self.data["submissions"]) == 2:
            raise RuntimeError("합성 저장소의 두 번째 제출 쓰기 실패")

    def update_game_state(self, cursor, *, state, expected_state_version, **kwargs):
        assert self.data["game"]["state_version"] == expected_state_version
        self.data["game"].update(
            state_version=state.state_version, updated_at=state.updated_at,
            phase=state.phase.value, status=state.status.value, round=state.round,
            day_number=state.day_number, winner=state.winner.value if state.winner else None,
            win_reason=state.win_reason.value if state.win_reason else None,
        )
        self.writes.append("game")

    def next_front_sequence(self, cursor, game_id):
        self.data["front_sequence"] += 1
        return self.data["front_sequence"]

    def append(self, cursor, **row):
        event = {**deepcopy(row), "id": self.identify(f"event-{len(self.data['events'])}")}
        self.data["events"].append(event)
        self.writes.append("event")
        return deepcopy(event)

    def enqueue(self, cursor, event_id):
        self.data["outbox"].append(event_id)
        self.writes.append("outbox")

    def find(self, cursor, *, principal_type, principal_id, idempotency_key):
        return deepcopy(self.data["receipts"].get((principal_type, principal_id, idempotency_key)))

    def insert(self, cursor, **row):
        key = (row["principal_type"], row["principal_id"], row["idempotency_key"])
        self.data["receipts"][key] = deepcopy(row)
        self.writes.append("receipt")
        if self.fail_on == "receipt":
            raise RuntimeError("합성 저장소의 receipt 쓰기 실패")


class JobRows:
    """proposal 생성용 예약 행만 제공하며 DB fencing·unique 성공률은 시험하지 않는다."""

    def __init__(self, identify):
        self.identify = identify
        self.reserved = []
        self.completed = []
        self.revoked = []
        self.released = []

    def reserve_job(self, **values):
        number = len(self.reserved)
        row = AgentReservation(
            self.identify(f"job-{number}"), values["game_id"], values["player_id"],
            values["window_id"], values["job_kind"], values["state_version"],
            self.identify(f"lease-{number}"), NOW + timedelta(seconds=40),
        )
        self.reserved.append(row)
        return row

    def issue_capability(self, reservation, **kwargs):
        return CapabilityGrant("synthetic-report-capability", "c" * 64,
                               reservation.lease_expires_at)

    def complete_job(self, reservation, **values):
        self.completed.append({"reservation": reservation, **deepcopy(values)})
        return True

    def revoke_capability(self, token_hash, **kwargs):
        self.revoked.append(token_hash)

    def release_unapplied_job(self, reservation):
        self.released.append(reservation)


class SyntheticProvider:
    """합성 원문만 응답하며 정규화·교정·제출 판정은 실제 Orchestrator에 남긴다."""

    def __init__(self, output):
        self.output = output
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        return LLMResponse(provider="synthetic", model="report-fixture",
                           output=deepcopy(self.output))


class RecoveryHarness:
    """외부 전송과 행 저장만 대체하여 실제 운영 runtime과 command service를 연결한다."""

    def __init__(self, monkeypatch, sink, sample_index, *, phase="DAY_DISCUSSION", day=2,
                 action="SPEAK"):
        self.identify = lambda label: uuid5(
            NAMESPACE_URL, f"agent-report-recovery/{sample_index}/{phase}/{day}/{action}/{label}"
        )
        self.owner, self.game_id = self.identify("owner"), self.identify("game")
        roles = (PlayerRole.CITIZEN, PlayerRole.MAFIA, PlayerRole.DETECTIVE,
                 PlayerRole.DOCTOR, PlayerRole.CITIZEN, PlayerRole.CITIZEN)
        players = [PlayerState(
            self.identify(f"player-{seat}"), seat, role,
            PlayerKind.HUMAN if seat == 6 else PlayerKind.AI, f"합성참가자{seat}",
        ) for seat, role in enumerate(roles, 1)]
        state = GameState(self.game_id, f"synthetic-seed-{sample_index}".encode(), players,
                          phase=GamePhase(phase), round=day if phase == "NIGHT_ACTION" else day - 1,
                          day_number=day,
                          state_version=10 + sample_index, updated_at=NOW)
        self.actor = players[1 if phase == "NIGHT_ACTION" else 0].player_id
        self.target = players[-1].player_id
        self.ledger = SyntheticLedger(state, self.owner, self.identify)
        common = dict(
            transactions=TransactionManager(
                "postgresql://synthetic.invalid/agent_report",
                connection_factory=lambda url: RowConnection(self.ledger),
            ),
            keyring=GameStateKeyring.legacy_plaintext(), games=self.ledger,
            players=self.ledger, actions=self.ledger, events=self.ledger,
            outbox=self.ledger, receipts=self.ledger,
        )
        self.discussion = PostgresAgentDiscussionService(**common)
        self.actions = PostgresActionCommandService(**common)
        self.jobs = JobRows(self.identify)
        self.sink = sink
        self.activity = AgentActivity(logger=sink)
        output = {"type": action}
        if action == "SPEAK":
            output.update(message=f"합성 관찰 {sample_index}의 근거를 확인해 줄래?",
                          public_rationale="ASK_FOR_CLARIFICATION")
        elif action in {"VOTE", "NIGHT_ACTION"}:
            output["target_player_id"] = str(self.target)
        self.provider = SyntheticProvider(output)
        self.tool_fault = None
        self.response_lost = False
        self.rpc_requests = []
        self.tool_arguments = []
        self.tool_receipts = []
        self.clients = []
        self.runtime = PostgresGameRuntime.__new__(PostgresGameRuntime)
        self.runtime._settings = SimpleNamespace(
            mcp_server_url="https://synthetic.invalid", llm_max_output_tokens=512,
            llm_timeout_seconds=5,
        )
        self.runtime._mutation_lock = RLock()
        self.runtime._activity = self.activity
        self.runtime._agent_repository = self.jobs
        self.runtime._agent_discussion = self.discussion
        self.runtime._actions = self.actions
        self.runtime._ai_worker = SimpleNamespace(wake_votes=lambda: None)
        self.runtime._read = SimpleNamespace(snapshot=self.snapshot)
        monkeypatch.setattr("backend.app.services.game.postgres_runtime.get_llm_provider",
                            lambda settings: self.provider)
        monkeypatch.setattr("backend.app.services.game.postgres_runtime.FastMcpGameContextClient",
                            self.make_client)

    @property
    def version(self):
        return self.ledger.data["game"]["state_version"]

    @property
    def window(self):
        return self.ledger.current_window(None, game_id=self.game_id)

    def snapshot(self, owner, game_id):
        assert (owner, game_id) == (self.owner, self.game_id)
        game = deepcopy(self.ledger.data["game"])
        window = self.window
        return {"game": {key: game[key] for key in (
            "phase", "status", "state_version", "day_number", "round",
        )}, "action_window": {
            "window_id": str(window["id"]),
            "turn_player_id": str(window["turn_player_id"]) if window["turn_player_id"] else None,
        }}

    def make_client(self, base_url, **binding):
        """실제 client에 MockTransport 소유권을 넘겨 종료 경로까지 그대로 실행한다."""

        client = FastMcpGameContextClient(
            base_url, **binding,
            client=httpx.AsyncClient(transport=httpx.MockTransport(self.serve), trust_env=False),
        )
        client._owns_client = True
        self.clients.append(client)
        return client

    def context(self, scope, actor):
        """현재 합성 원장을 실제 projection으로 투영하고 MCP 소유 지침만 덧붙인다."""

        state, _ = restore_locked_game(self.discussion, RowCursor(self.ledger),
                                      self.ledger.data["game"])
        persona = {
            "persona_id": "synthetic-persona", "version": "synthetic-v1",
            "display_name": "합성 페르소나", "speech_style": "짧은 질문",
            "backstory": "반복 검증을 위한 합성 설정",
            "parameters": {name: 0.5 for name in (
                "sociability", "assertiveness", "suspicion", "deception", "risk_tolerance",
                "memory_recall", "reasoning_skill", "emotionality", "cooperativeness", "verbosity",
            )},
        }
        envelope = build_context(
            state, subject_type="AI_PLAYER", subject_id=actor, scope=scope,
            window_id=self.window["id"], window=self.window, now=NOW,
            valid_target_ids=[] if self.window["window_kind"] == "SPEECH" else [self.target],
            facts={"alibi": "합성 알리바이", "observation": "합성 관찰"}, persona=persona,
            scenario={"scenario_id": "synthetic-report", "title": "합성 사건",
                      "background": "합성 시험 배경", "victim": "합성 피해자",
                      "locations": ["합성 서재", "합성 정원", "합성 복도", "합성 식당"]},
        )
        if scope in {"me", "persona"}:
            envelope["data"]["agent_instruction"] = "합성 공개 정보를 바탕으로 행동한다."
        return envelope

    def fail_tool(self, request, request_id):
        """전송 실패를 주입하되 오류 문자열에는 식별 가능한 합성 표식만 사용한다."""

        marker = "SYNTHETIC_DIAGNOSTIC_ONLY"
        if self.tool_fault == "timeout":
            raise httpx.ReadTimeout(marker, request=request)
        if self.tool_fault == "http_503":
            return httpx.Response(503, text=marker)
        if self.tool_fault == "rpc_error":
            return httpx.Response(200, json={
                "jsonrpc": "2.0", "id": request_id,
                "error": {"code": -32000, "message": marker},
            })
        if self.tool_fault == "invalid_json":
            return httpx.Response(200, text=marker)
        raise AssertionError("알려지지 않은 합성 전송 실패입니다.")

    def serve(self, request):
        """MCP protocol 전송만 대체하며 tools/call은 실제 submission service를 실행한다."""

        body = json.loads(request.content)
        self.rpc_requests.append(deepcopy(body))
        method = body["method"]
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {}}
        elif method == "resources/read":
            uri = body["params"]["uri"]
            actor, scope = uri.rsplit("/", 2)[-2:]
            result = {"contents": [{
                "uri": uri, "mimeType": "application/json",
                "text": json.dumps(self.context(scope, UUID(actor)), ensure_ascii=False),
            }]}
        elif method == "tools/call":
            arguments = body["params"]["arguments"]
            self.tool_arguments.append(deepcopy(arguments))
            if self.tool_fault and not self.response_lost:
                return self.fail_tool(request, body["id"])
            receipt, replayed = self.submit(
                {"type": arguments["action"], "message": arguments["message"],
                 "target_player_id": arguments["target_player_id"]},
                version=arguments["expected_state_version"],
                window=UUID(arguments["window_id"]), key=UUID(arguments["idempotency_key"]),
            )
            self.tool_receipts.append(deepcopy(receipt))
            if self.response_lost:
                return self.fail_tool(request, body["id"])
            result = {"content": [{"type": "text", "text": json.dumps({
                "status": "accepted", "source": "backend", "accepted": True,
                "replayed": replayed, "result": receipt,
            })}]}
        else:
            raise AssertionError("예상하지 않은 MCP 메서드입니다.")
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    def spec(self):
        phase = self.ledger.data["game"]["phase"]
        kind = {"DAY_DISCUSSION": "SPEECH", "NIGHT_ACTION": "NIGHT_ACTION",
                "DAY_VOTE": "VOTE"}[phase]
        return AgentJobSpec(self.game_id, self.actor, self.window["id"], kind, phase,
                            self.version, day_number=self.ledger.data["game"]["day_number"])

    async def decide(self, spec=None):
        spec = spec or self.spec()
        client = self.make_client(
            "https://synthetic.invalid", user_id=self.owner, game_id=self.game_id,
            player_id=spec.player_id, phase=spec.phase, state_version=spec.state_version,
            window_id=spec.window_id,
        )
        return await AgentOrchestrator(
            self.jobs, self.provider, client, clock=lambda: NOW,
            activity=self.activity, owner_user_id=self.owner,
        ).run(spec)

    def submit(self, proposal, *, version, window, key):
        body = proposal if isinstance(proposal, dict) else proposal.model_dump(mode="json")
        common = dict(expected_state_version=version, window_id=window, idempotency_key=key,
                      now=NOW)
        if body["type"] == "SPEAK":
            return self.discussion.submit_speak(
                self.owner, self.game_id, self.actor, body["message"], **common,
            )
        if body["type"] == "PASS":
            return self.discussion.submit_pass(self.owner, self.game_id, self.actor, **common)
        return self.actions.submit(
            self.owner, self.game_id,
            GameCommandRequest(
                type="SUBMIT_VOTE" if body["type"] == "VOTE" else "SUBMIT_NIGHT_ACTION",
                expected_state_version=version, window_id=window,
                target_player_id=body["target_player_id"],
            ), key, actor=ActorContext.agent(owner_user_id=self.owner, player_id=self.actor),
            now=NOW,
        )

    def stages(self):
        return [row["stage"] for row in self.sink.records()]

    def assert_closed(self):
        assert self.clients and all(client._client.is_closed for client in self.clients)
        assert len(self.jobs.revoked) == len(self.jobs.reserved)


@SAMPLES
@pytest.mark.parametrize("phase,action", [
    ("DAY_DISCUSSION", "SPEAK"), ("DAY_VOTE", "VOTE"), ("NIGHT_ACTION", "NIGHT_ACTION"),
])
@pytest.mark.parametrize("changed", ["version", "window"])
def test_agt_009_stale_submission_preserves_ledger(
    monkeypatch, isolated_boundaries, sample_index, phase, action, changed,
):
    """정상 생성 뒤 바뀐 version·window에 이전 proposal을 제출해 실제 저장 거부를 확인한다."""

    h = RecoveryHarness(monkeypatch, isolated_boundaries, sample_index, phase=phase, action=action)
    spec = h.spec()
    decision = asyncio.run(h.decide(spec))
    assert decision.status == "SUCCEEDED" and len(h.provider.requests) == 1
    if changed == "version":
        h.ledger.data["game"]["state_version"] += 1
    else:
        h.ledger.data["windows"][-1]["id"] = h.identify("replacement-window")
    before = deepcopy(h.ledger.data)
    with pytest.raises(ApiError) as error:
        h.submit(decision.proposal, version=spec.state_version, window=spec.window_id,
                 key=h.identify("stale-command"))
    # 보고서의 STALE는 분류명이다. speech의 window 거부는 현재 ACTOR 경계가
    # ACTION_NOT_ALLOWED로 표현하므로 API 정본과의 코드 차이를 별도 보고한다.
    expected = "STALE_STATE_VERSION" if changed == "version" else (
        "ACTION_NOT_ALLOWED" if phase == "DAY_DISCUSSION" else "WINDOW_CLOSED"
    )
    assert error.value.code == expected and error.value.status_code == 409
    assert h.ledger.data == before and h.ledger.writes == []
    assert h.ledger.rollbacks == 1 and h.tool_arguments == []
    assert "APPLIED" not in h.stages()
    h.assert_closed()


@SAMPLES
@pytest.mark.parametrize("changed", ["version", "window"])
def test_agt_009_stale_context_is_terminal_without_fallback(
    monkeypatch, isolated_boundaries, sample_index, changed,
):
    """실제 MCP binding 검사가 새 상태 응답을 STALE로 바꾸고 Provider·제출을 생략한다."""

    h = RecoveryHarness(monkeypatch, isolated_boundaries, sample_index)
    spec = h.spec()
    if changed == "version":
        h.ledger.data["game"]["state_version"] += 1
    else:
        h.ledger.data["windows"][-1]["id"] = h.identify("replacement-window")
    before = deepcopy(h.ledger.data)
    result = asyncio.run(h.decide(spec))
    assert result.status == "STALE" and result.failure_code == "STALE_STATE_VERSION"
    assert result.proposal is None and h.provider.requests == [] and h.tool_arguments == []
    assert h.ledger.data == before and h.ledger.writes == []
    assert h.jobs.completed[-1]["status"] == "STALE"
    assert h.stages()[-1] == "SKIPPED" and "FALLBACK" not in h.stages()
    h.assert_closed()


@SAMPLES
@pytest.mark.parametrize("phase,action", [
    ("DAY_DISCUSSION", "SPEAK"), ("DAY_VOTE", "VOTE"), ("NIGHT_ACTION", "NIGHT_ACTION"),
])
def test_agt_010_same_key_replays_first_receipt_without_second_mutation(
    monkeypatch, isolated_boundaries, sample_index, phase, action,
):
    """현재 창이 교체되어도 같은 원문·key는 첫 receipt만 돌려주고 원장을 다시 쓰지 않는다."""

    h = RecoveryHarness(monkeypatch, isolated_boundaries, sample_index, phase=phase, action=action)
    spec, key = h.spec(), h.identify("repeat-key")
    decision = asyncio.run(h.decide(spec))
    assert decision.status == "SUCCEEDED"
    first, replayed = h.submit(decision.proposal, version=spec.state_version,
                               window=spec.window_id, key=key)
    assert replayed is False and len(h.ledger.data["submissions"]) == 1
    before, writes = deepcopy(h.ledger.data), list(h.ledger.writes)
    second, replayed = h.submit(decision.proposal, version=spec.state_version,
                                window=spec.window_id, key=key)
    assert replayed is True and second == first
    assert h.ledger.data == before and h.ledger.writes == writes
    second["result_state_version"] = -1
    assert next(iter(h.ledger.data["receipts"].values()))["result_body"] == first
    h.assert_closed()


@SAMPLES
@pytest.mark.parametrize("phase,action", [("DAY_VOTE", "VOTE"), ("NIGHT_ACTION", "NIGHT_ACTION")])
@pytest.mark.parametrize("second_target", ["same", "different"])
def test_agt_010_same_window_actor_new_key_cannot_replace_first_action(
    monkeypatch, isolated_boundaries, sample_index, phase, action, second_target,
):
    """새 key와 최신 version으로도 기존 actor 제출을 실제 엔진이 DUPLICATE_ACTION으로 거부한다."""

    h = RecoveryHarness(monkeypatch, isolated_boundaries, sample_index, phase=phase, action=action)
    spec = h.spec()
    decision = asyncio.run(h.decide(spec))
    assert decision.status == "SUCCEEDED"
    h.submit(decision.proposal, version=spec.state_version, window=spec.window_id,
             key=h.identify("first-key"))
    assert len(h.ledger.data["submissions"]) == 1 and h.window["id"] == spec.window_id
    proposal = decision.proposal.model_dump(mode="json")
    if second_target == "different":
        proposal["target_player_id"] = str(h.identify("player-5"))
    before, writes = deepcopy(h.ledger.data), list(h.ledger.writes)
    with pytest.raises(ApiError) as error:
        h.submit(proposal, version=h.version, window=spec.window_id,
                 key=h.identify("second-key"))
    assert error.value.code == "ACTION_ALREADY_SUBMITTED"
    assert str(error.value.__cause__) == "DUPLICATE_ACTION"
    assert h.ledger.data == before and h.ledger.writes == writes
    assert h.ledger.data["submissions"][0]["target_player_id"] == h.target
    h.assert_closed()


@SAMPLES
@pytest.mark.parametrize("action", ["SPEAK", "PASS"])
@pytest.mark.parametrize("fault", ["timeout", "http_503", "rpc_error", "invalid_json"])
@pytest.mark.parametrize("fallback", ["commits", "rolls_back"])
def test_agt_011_mcp_attempt_is_bounded_and_fallback_is_atomic(
    monkeypatch, isolated_boundaries, sample_index, action, fault, fallback,
):
    """MCP 1회 실패 뒤 직접 제출 1회만 실행하고 성공 또는 원장 없는 실패로 끝난다.

    현재 client에는 네트워크 재시도 루프가 없다. 따라서 이 시험은 존재하지 않는
    재시도 성공률을 만들지 않고 실제 MCP 시도 수와 fallback 저장 경계를 측정한다.
    """

    h = RecoveryHarness(monkeypatch, isolated_boundaries, sample_index, action=action)
    h.tool_fault = fault
    h.ledger.fail_on = "receipt" if fallback == "rolls_back" else None
    before = deepcopy(h.ledger.data)
    if fallback == "rolls_back":
        with pytest.raises(ApiError) as error:
            asyncio.run(h.runtime.run_agent_turn(h.owner, h.game_id, h.actor))
        assert error.value.code == "DEPENDENCY_UNAVAILABLE"
        assert h.ledger.data == before and h.ledger.rollbacks == 1
        assert h.jobs.released == h.jobs.reserved
        assert "APPLIED" not in h.stages() and h.stages()[-1] == "FAILED"
    else:
        receipt = asyncio.run(h.runtime.run_agent_turn(h.owner, h.game_id, h.actor))
        assert receipt["result_state_version"] == before["game"]["state_version"] + 1
        assert len(h.ledger.data["submissions"]) == len(h.ledger.data["receipts"]) == 1
        row = h.ledger.data["submissions"][0]
        assert row["action_type"] == action and row["source"] == "AGENT"
        assert row["window_id"] == before["windows"][-1]["id"]
        assert row["observed_state_version"] == before["game"]["state_version"]
        assert row["message"] == h.provider.output.get("message")
        assert h.jobs.released == [] and h.stages()[-1] == "APPLIED"
    assert len(h.provider.requests) == len(h.tool_arguments) == 1
    assert h.ledger.writes.count("submission") == h.ledger.writes.count("receipt") == 1
    assert [row["params"]["uri"].rsplit("/", 1)[-1] for row in h.rpc_requests
            if row["method"] == "resources/read"] == ["public", "me", "turn", "persona"]
    final = h.activity.recent(h.owner, h.game_id)[-1]
    assert final["decision_source"] == "FALLBACK"
    assert final["reason_code"] == "MCP_SUBMISSION_FAILED"
    assert "SYNTHETIC_DIAGNOSTIC_ONLY" not in "\n".join(h.sink.lines)
    h.assert_closed()


@SAMPLES
@pytest.mark.parametrize("day,action", [(1, "SPEAK"), (2, "SPEAK"), (2, "PASS")])
@pytest.mark.parametrize("loss", ["timeout", "invalid_json"])
def test_agt_012_committed_response_loss_never_reapplies_to_new_window(
    monkeypatch, isolated_boundaries, sample_index, day, action, loss,
):
    """실제 첫 제출을 commit한 뒤 응답만 잃어도 fallback은 이전 version에서 거부된다."""

    h = RecoveryHarness(monkeypatch, isolated_boundaries, sample_index, day=day, action=action)
    h.tool_fault, h.response_lost = loss, True
    spec = h.spec()
    with pytest.raises(ApiError) as error:
        asyncio.run(h.runtime.run_agent_turn(h.owner, h.game_id, h.actor))
    assert error.value.code == "STALE_STATE_VERSION"
    assert error.value.details == {"current_state_version": spec.state_version + 1}
    assert len(h.provider.requests) == len(h.tool_arguments) == len(h.tool_receipts) == 1
    assert h.version == spec.state_version + 1 and h.window["id"] != spec.window_id
    assert len(h.ledger.data["submissions"]) == len(h.ledger.data["receipts"]) == 1
    row = h.ledger.data["submissions"][0]
    assert row["window_id"] == spec.window_id and row["observed_state_version"] == spec.state_version
    assert row["actor_player_id"] == h.actor and row["action_type"] == action
    assert row["message"] == h.provider.output.get("message")
    assert h.ledger.writes.count("submission") == h.ledger.writes.count("receipt") == 1
    assert len(h.ledger.data["events"]) == len(h.ledger.data["outbox"]) == 3
    assert h.ledger.commits == h.ledger.rollbacks == 1
    assert h.stages()[-2:] == ["FALLBACK", "FAILED"] and "APPLIED" not in h.stages()
    assert h.jobs.released == h.jobs.reserved
    assert h.activity.recent(h.owner, h.game_id)[-1]["reason_code"] == "MCP_SUBMISSION_FAILED"
    h.assert_closed()


@SAMPLES
@pytest.mark.parametrize("failure_point", ["second_submission", "receipt"])
def test_private_batch_rollback_never_records_applied(
    monkeypatch, isolated_boundaries, sample_index, failure_point,
):
    """두 AI의 실제 밤 제출 이후 저장 실패가 발생하면 부분 원장과 APPLIED를 남기지 않는다."""

    h = RecoveryHarness(monkeypatch, isolated_boundaries, sample_index,
                        phase="NIGHT_ACTION", action="NIGHT_ACTION")
    h.ledger.fail_on = failure_point
    before = deepcopy(h.ledger.data)
    actors = [h.identify("player-2"), h.identify("player-3")]
    turns = [{"player_id": actor, "window_id": h.window["id"],
              "state_version": h.version, "phase": "NIGHT_ACTION"} for actor in actors]
    with pytest.raises(ApiError) as error:
        asyncio.run(h.runtime.run_agent_night_turn(h.owner, h.game_id, turns))
    assert error.value.code == "DEPENDENCY_UNAVAILABLE"
    assert len(h.provider.requests) == 2 and h.ledger.writes.count("submission") == 2
    if failure_point == "receipt":
        assert h.ledger.writes.count("game") == h.ledger.writes.count("receipt") == 1
        assert h.ledger.writes.count("event") == h.ledger.writes.count("outbox") == 2
    assert h.ledger.data == before and h.ledger.rollbacks == 1 and h.ledger.commits == 0
    assert "APPLIED" not in h.stages() and "COMMAND_APPLIED" not in h.stages()
    assert h.stages().count("FAILED") == 2 and h.jobs.released == h.jobs.reserved
    assert all(row["status"] == "SUCCEEDED" for row in h.jobs.completed)
    assert h.activity.recent(h.owner, h.game_id) == []
    serialized = "\n".join(h.sink.lines)
    assert all(str(identifier) not in serialized for identifier in [*actors, h.target])
    h.assert_closed()


@SAMPLES
@pytest.mark.parametrize("reason", sorted(FAILURE_REASONS))
@pytest.mark.parametrize("terminal", ["APPLIED", "FAILED", "SKIPPED"])
def test_activity_keeps_fallback_reason_until_next_attempt(
    isolated_boundaries, sample_index, reason, terminal,
):
    """같은 actor·version의 원인은 terminal에서도 보존하되 새 시도에 상속하지 않는다."""

    identify = lambda name: uuid5(NAMESPACE_URL, f"report-activity/{sample_index}/{name}")
    activity = AgentActivity(logger=isolated_boundaries)
    args = dict(owner_user_id=identify("owner"), game_id=identify("game"),
                player_id=identify("actor"), phase="DAY_DISCUSSION", state_version=10 + sample_index)
    activity.record(**args, stage="FALLBACK", action="SPEAK", reason_code=reason,
                    decision_basis="ASK_FOR_CLARIFICATION")
    result = activity.record(**args, stage=terminal, action="SPEAK")
    assert result["decision_source"] == "FALLBACK" and result["reason_code"] == reason
    assert result["decision_basis"] == "ASK_FOR_CLARIFICATION"
    activity.record(**args, stage="STARTED", decision_source="MODEL")
    activity.record(**args, stage="DECIDED", action="SPEAK", decision_source="MODEL",
                    decision_basis="PUBLIC_EVIDENCE")
    result = activity.record(**args, stage="APPLIED", action="SPEAK")
    assert result["decision_source"] == "MODEL" and result["reason_code"] is None
    assert result["decision_basis"] == "PUBLIC_EVIDENCE"
    rows = activity.recent(args["owner_user_id"], args["game_id"])
    assert [row["sequence"] for row in rows] == [1, 2, 3, 4, 5]
    assert rows[-1] == result


@SAMPLES
@pytest.mark.parametrize("phase", ["DAY_DISCUSSION", "NIGHT_ACTION"])
@pytest.mark.parametrize("shape", ["text", "url", "newline", "list", "mapping", "bytes"])
def test_sensitive_diagnostics_never_enter_activity_or_mcp_error(
    isolated_boundaries, sample_index, phase, shape,
):
    """합성 비밀 표식과 비정상 타입을 공개 activity·파일 직렬화·MCP 오류에서 차단한다."""

    marker = f"SYNTHETIC_PRIVATE_MARKER_{sample_index}"
    values = {
        "text": marker, "url": f"https://synthetic.invalid/path?private={marker}",
        "newline": f"허용되지 않은 진단\n{marker}", "list": [marker],
        "mapping": {"private": marker}, "bytes": marker.encode(),
    }
    value = values[shape]
    activity = AgentActivity(logger=isolated_boundaries)
    identify = lambda name: uuid5(NAMESPACE_URL, f"report-redaction/{sample_index}/{name}")
    args = dict(game_id=identify("game"), owner_user_id=identify("owner"),
                player_id=identify("actor"), state_version=10 + sample_index, phase=phase)
    row = activity.record(**args, stage="DECIDED", action="SPEAK", decision_source=value,
                          reason_code=value, decision_basis=value)
    assert row["decision_source"] is row["reason_code"] is row["decision_basis"] is None
    error = McpContextError(value, http_status=value)
    assert error.code == "MCP_UNKNOWN_ERROR" and error.http_status is None
    assert marker not in str(error) and marker not in "\n".join(isolated_boundaries.lines)
    assert marker not in json.dumps(activity.recent(args["owner_user_id"], args["game_id"]))
    if phase == "NIGHT_ACTION":
        assert row["player_id"] is row["action"] is None
        assert activity.recent(args["owner_user_id"], args["game_id"]) == []
    before = list(isolated_boundaries.lines)
    with pytest.raises(ValueError):
        activity.record(**args, stage=value)
    assert isolated_boundaries.lines == before
