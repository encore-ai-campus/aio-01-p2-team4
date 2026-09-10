"""AGT-001~008의 행동·대상·입력·정보 경계를 독립 합성 표본으로 검증한다.

기본값은 각 변형당 50회이며 개발 확인에만 AGENT_REPORT_SAMPLES=1을 사용한다.
외부 Provider·MCP 전송·job 저장소만 합성 구현으로 바꾸고 실제 정규화, Agent
Orchestrator, MCP client, projection, 정보 수신자 검사와 GameEngine을 호출한다.
메모리 제출 증거는 DB 원장이나 실제 LLM 행동 오류율의 측정값이 아니다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest

from backend.app.agent.activity import AgentActivity
from backend.app.agent.orchestrator import AgentJobSpec, AgentOrchestrator
from backend.app.agent.projections import build_context
from backend.app.game_engine.engine import GameEngine
from backend.app.game_engine.errors import RuleViolation
from backend.app.game_engine.rules.night_rules import role_action
from backend.app.llm_provider.base import LLMResponse
from backend.app.llm_provider.errors import LLMResponseError
from backend.app.llm_provider.schemas import normalize_agent_proposal
from backend.app.mcp.client import FastMcpGameContextClient, McpContextError
from backend.app.models.enums import GamePhase, NightActionType, PlayerKind, PlayerRole
from backend.app.models.game_state import GameState, PlayerState
from backend.app.repositories.agent_repository import AgentReservation, CapabilityGrant
from backend.app.services.game.actor_context import _actor_target_ids, scoped_private_events
from backend.app.services.game.service_errors import rule_error


SAMPLE_COUNT = int(os.environ.get("AGENT_REPORT_SAMPLES", "50"))
if SAMPLE_COUNT < 1:
    raise ValueError("AGENT_REPORT_SAMPLES는 1 이상의 정수여야 합니다.")
SAMPLES = pytest.mark.parametrize(
    "sample_index", range(SAMPLE_COUNT), ids=lambda index: f"sample-{index:02d}"
)
NIGHT_ROLES = (PlayerRole.MAFIA, PlayerRole.DETECTIVE, PlayerRole.DOCTOR)
ROLE_ACTIONS = {
    PlayerRole.MAFIA: NightActionType.ATTACK,
    PlayerRole.DETECTIVE: NightActionType.INVESTIGATE,
    PlayerRole.DOCTOR: NightActionType.PROTECT,
}
PERSONA_PARAMETERS = (
    "sociability", "assertiveness", "suspicion", "deception", "risk_tolerance",
    "memory_recall", "reasoning_skill", "emotionality", "cooperativeness", "verbosity",
)


class SyntheticCase:
    """샘플마다 새 상태·식별자·후보·원장을 만들고 외부 연결을 갖지 않는다.

인원수, AI 좌석, 날짜, 생존자 집합, 버전과 페르소나 수치도 바꾼다. 식별자만
바꾼 동일 반복에 그치지 않고 역할별 후보와 정규화 경계를 함께 검사하기 위함이다.
"""

    def __init__(
        self, sample_index, *, phase=GamePhase.DAY_DISCUSSION,
        role=PlayerRole.CITIZEN, day=None, player_count=None,
    ):
        self.sample_index = sample_index
        self.offset = (sample_index + 1) * 10_000
        self.now = datetime(2026, 9, 9, 6, tzinfo=UTC) + timedelta(seconds=sample_index)
        count = 6 + sample_index % 4 if player_count is None else player_count
        mafia_count = 1 if count <= 7 else 2
        roles = [PlayerRole.MAFIA] * mafia_count + [PlayerRole.DETECTIVE, PlayerRole.DOCTOR]
        roles += [PlayerRole.CITIZEN] * (count - 1 - len(roles))
        shift = sample_index % len(roles)
        roles = roles[shift:] + roles[:shift]
        roles.append(PlayerRole.CITIZEN)
        players = [
            PlayerState(
                player_id=self.identifier(seat), seat=seat, role=assigned_role,
                kind=PlayerKind.HUMAN if seat == count else PlayerKind.AI,
                display_name=f"합성 참가자 {sample_index}-{seat}",
            )
            for seat, assigned_role in enumerate(roles, start=1)
        ]
        actors = [p for p in players if p.kind is PlayerKind.AI and p.role is role]
        self.actor = actors[sample_index % len(actors)]
        self.owner_id = self.identifier(800)
        self.window_id = self.identifier(900)
        selected_day = day if day is not None else 2 + (sample_index // 4) % 4
        if phase is GamePhase.NIGHT_ACTION and day is None:
            selected_day = 1 + sample_index % 5
        self.state = GameState(
            game_id=self.identifier(700), seed=f"agt-synthetic-{sample_index}".encode(),
            players=players, phase=phase, day_number=selected_day,
            round=selected_day if phase is GamePhase.NIGHT_ACTION else selected_day - 1,
            state_version=10 + sample_index * 3, updated_at=self.now,
        )
        # 1일차에는 사망자를 만들지 않고, 이후 표본은 공개 생존 후보의 수를 바꾼다.
        if selected_day > 1 and sample_index % 2:
            candidates = [p for p in players if p is not self.actor and p.role is PlayerRole.CITIZEN]
            candidates[-1].alive = False
        kind = {
            GamePhase.DAY_DISCUSSION: "SPEECH", GamePhase.DAY_VOTE: "VOTE",
            GamePhase.NIGHT_ACTION: "NIGHT",
        }[phase]
        deadline_seconds = {"SPEECH": 105, "VOTE": 30, "NIGHT": 30}[kind]
        deadline = self.now + timedelta(seconds=deadline_seconds)
        self.window = {
            "id": self.window_id, "game_id": self.state.game_id, "status": "OPEN",
            "phase": phase.value, "round": self.state.round, "window_kind": kind,
            "cycle": 1, "opened_state_version": self.state.state_version,
            "turn_player_id": self.actor.player_id if kind == "SPEECH" else None,
            "deadline_at": deadline,
        }
        self.state.deadline_at = deadline
        self.scenario = {
            "scenario_id": f"synthetic-{sample_index}", "title": "합성 사건",
            "background": "시험용 가상 장소에서 발생한 사건이다.", "victim": "가상 피해자",
            "locations": ["서재", "정원", "주방", "복도"],
        }
        self.facts = {
            p.player_id: {"alibi": f"{p.display_name}의 합성 알리바이",
                          "observation": f"{p.display_name}의 합성 관찰"}
            for p in players
        }
        self.persona = {
            "persona_id": f"synthetic-persona-{sample_index}", "version": "synthetic-v1",
            "display_name": "합성 성향", "speech_style": "확인한 사실로 질문한다.",
            "backstory": "실제 사용자와 무관한 합성 인물이다.",
            "parameters": {name: ((sample_index + index) % 11) / 10
                           for index, name in enumerate(PERSONA_PARAMETERS)},
        }
        self.public_events = [{
            "event_id": str(self.identifier(1001)), "event_type": "PLAYER_SPOKE",
            "created_at": self.now.isoformat(),
            "data": {"player_id": str(players[-1].player_id), "message": "합성 공개 진술이다."},
        }]
        self.private_rows = []
        self.sequence_limit = 20 + sample_index
        self.submissions = []
        self.transport_calls = []
        self.mutate_context = None

    def identifier(self, index):
        """실제 계정·게임 ID를 읽지 않고 표본 안에서 재현 가능한 UUID를 만든다."""

        return UUID(int=self.offset + index)

    def context(self, scope, *, state=None, subject_type="AI_PLAYER", subject_id=None):
        """실제 Backend의 대상 산출과 수신자 필터를 거쳐 scope를 만든다."""

        state = self.state if state is None else state
        subject_id = self.actor.player_id if subject_id is None else subject_id
        private_events = scoped_private_events(
            state, self.private_rows, self.actor.player_id, self.sequence_limit
        )
        return build_context(
            state, subject_type=subject_type, subject_id=subject_id, scope=scope,
            window_id=self.window_id, window=self.window, now=self.now,
            valid_target_ids=_actor_target_ids(state, self.actor.player_id),
            scenario=self.scenario, facts=self.facts[self.actor.player_id], persona=self.persona,
            public_events=self.public_events, private_events=private_events,
            last_sequence=self.sequence_limit,
            eliminated={p.player_id: ("NIGHT_ACTION", max(1, state.round))
                        for p in state.players if not p.alive},
        )

    def contexts(self):
        """각 scope를 새로 만들어 공유 dict 변경으로 오류를 숨기지 않는다."""

        return {scope: self.context(scope) for scope in ("public", "me", "turn", "persona")}

    def spec(self):
        """현재 합성 원장의 창·버전·actor와 일치하는 실제 job 계약을 반환한다."""

        return AgentJobSpec(
            game_id=self.state.game_id, player_id=self.actor.player_id,
            window_id=self.window_id,
            job_kind={"SPEECH": "SPEECH", "VOTE": "VOTE", "NIGHT": "NIGHT_ACTION"}[
                self.window["window_kind"]
            ],
            phase=self.state.phase.value, state_version=self.state.state_version,
            window_deadline=self.window["deadline_at"], day_number=self.state.day_number,
        )

    def apply(self, proposal):
        """판정 결과를 만들지 않고 실제 Engine이 성공한 뒤에만 합성 제출을 기록한다."""

        before_version = self.state.state_version
        engine = GameEngine()
        if proposal.type == "SPEAK":
            engine.speak(self.state, self.actor.player_id, proposal.message)
        elif proposal.type == "PASS":
            engine.pass_turn(self.state, self.actor.player_id)
        elif proposal.type == "NIGHT_ACTION":
            engine.submit_night_action(
                self.state, self.actor.player_id,
                role_action(self.state, self.actor.player_id), proposal.target_player_id,
            )
        else:
            engine.submit_vote(self.state, self.actor.player_id, proposal.target_player_id)
        operation = self.state.operations[-1]
        self.submissions.append({
            "game_id": self.state.game_id, "window_id": self.window_id,
            "actor_player_id": operation.actor_id, "action_type": operation.command,
            "target_player_id": operation.target_id, "message": operation.text,
            "source": "AGENT", "observed_state_version": before_version,
        })
        return {
            "status": "accepted", "source": "backend", "accepted": True, "replayed": False,
            "result": {"command_type": operation.command,
                       "accepted_state_version": before_version,
                       "result_state_version": self.state.state_version,
                       "sync_url": f"/api/v1/games/{self.state.game_id}/sync"},
        }

    def handle_request(self, request):
        """HTTP만 대체하며 Resource는 실제 projection, Tool은 실제 Engine으로 전달한다."""

        body = json.loads(request.content)
        method = body["method"]
        self.transport_calls.append(deepcopy(body))
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {},
                      "serverInfo": {"name": "synthetic", "version": "1"}}
        elif method == "resources/read":
            uri = body["params"]["uri"]
            scope = uri.rsplit("/", 1)[-1]
            assert uri == (f"mafia://context/scoped/{self.state.game_id}/"
                           f"{self.owner_id}/{self.actor.player_id}/{scope}")
            payload = self.context(scope)
            if scope in {"me", "persona"}:
                # MCP 지침 생성의 문체는 범위 밖이므로 전송용 합성 지침만 추가한다.
                payload["data"]["agent_instruction"] = "허용된 합성 게임 정보만 사용한다."
            if self.mutate_context is not None:
                self.mutate_context(payload)
            result = {"contents": [{"uri": uri, "mimeType": "application/json",
                                    "text": json.dumps(payload, ensure_ascii=False)}]}
        elif method == "tools/call":
            assert body["params"]["name"] == "submit_action"
            arguments = body["params"]["arguments"]
            assert arguments["game_id"] == str(self.state.game_id)
            assert arguments["user_id"] == str(self.owner_id)
            assert arguments["player_id"] == str(self.actor.player_id)
            assert arguments["window_id"] == str(self.window_id)
            assert arguments["expected_state_version"] == self.state.state_version
            proposal = normalize_agent_proposal({
                "type": arguments["action"], "message": arguments["message"],
                "target_player_id": arguments["target_player_id"],
            })
            receipt = self.apply(proposal)
            result = {"isError": False, "content": [{"type": "text",
                                                       "text": json.dumps(receipt)}]}
        else:
            raise AssertionError(f"시험이 허용하지 않은 MCP method: {method}")
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": body["id"], "result": result},
            headers={"mcp-session-id": "synthetic-session"},
        )

    def client(self, http_client):
        """실제 MCP client의 binding·폐쇄형 검증을 그대로 사용한다."""

        return FastMcpGameContextClient(
            "http://synthetic.invalid", user_id=self.owner_id, game_id=self.state.game_id,
            player_id=self.actor.player_id, phase=self.state.phase.value,
            state_version=self.state.state_version, window_id=self.window_id, client=http_client,
        )


class SyntheticRepository:
    """job 저장 호출만 기록하며 DB 예약·transaction의 정확성은 주장하지 않는다."""

    def __init__(self, case):
        self.case = case
        self.completed = []
        self.revoked = []

    def reserve_job(self, **kwargs):
        return AgentReservation(
            job_id=self.case.identifier(1100), game_id=kwargs["game_id"],
            player_id=kwargs["player_id"], window_id=kwargs["window_id"],
            job_kind=kwargs["job_kind"], state_version=kwargs["state_version"],
            lease_token=self.case.identifier(1101),
            lease_expires_at=self.case.now + timedelta(seconds=40),
        )

    def issue_capability(self, reservation, **kwargs):
        return CapabilityGrant("synthetic-unused-capability", "synthetic-hash", reservation.lease_expires_at)

    def complete_job(self, reservation, **kwargs):
        self.completed.append(deepcopy(kwargs))
        return True

    def revoke_capability(self, token_hash, **kwargs):
        self.revoked.append(token_hash)


class SyntheticProvider:
    """명시된 응답만 순서대로 반환하고 예기치 않은 추가 교정 요청은 실패시킨다."""

    def __init__(self, outputs):
        self.outputs = deepcopy(outputs)
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        assert len(self.requests) <= len(self.outputs), "허용된 Provider 호출 상한을 넘었습니다."
        return LLMResponse(
            provider="synthetic", model="synthetic", output=self.outputs[len(self.requests) - 1]
        )


@pytest.fixture
def make_case(sample_index, monkeypatch):
    """실행 시각과 로그 sink만 격리하며 판정 대상 함수는 바꾸지 않는다."""

    from backend.app.agent import activity, orchestrator
    from backend.app.game_engine.phases import transition

    frozen = datetime(2026, 9, 9, 6, tzinfo=UTC) + timedelta(seconds=sample_index)

    class FrozenDatetime(datetime):
        """Engine의 상태 갱신 시간이 표본별 고정 시각을 사용하게 한다."""

        @classmethod
        def now(cls, tz=None):
            return frozen.astimezone(tz) if tz is not None else frozen.replace(tzinfo=None)

    logger = logging.Logger(f"agt-synthetic-{sample_index}")
    logger.addHandler(logging.NullHandler())
    monkeypatch.setattr(transition, "datetime", FrozenDatetime)
    monkeypatch.setattr(activity, "datetime", FrozenDatetime)
    monkeypatch.setattr(activity, "progress_logger", lambda: logger)
    monkeypatch.setattr(orchestrator, "progress_logger", lambda: logger)

    def create(**kwargs):
        return SyntheticCase(sample_index, **kwargs)

    return create


async def run_and_submit(case, outputs, *, expected_type, expected_target=None, expected_message=None):
    """정규화·교정·완료 뒤 실제 MCP 제출과 Engine 원장까지 확인한다.

Orchestrator의 SUCCEEDED만으로 적용 성공을 주장하지 않는다. 전송 전에는 게임
상태가 그대로이고 전송 뒤에는 Engine 상태·operation·합성 제출이 일치해야 한다.
"""

    before = deepcopy(case.state)
    repository = SyntheticRepository(case)
    provider = SyntheticProvider(outputs)
    async with httpx.AsyncClient(transport=httpx.MockTransport(case.handle_request)) as http_client:
        client = case.client(http_client)
        orchestrator = AgentOrchestrator(
            repository, provider, client, clock=lambda: case.now,
            owner_user_id=case.owner_id, close_context=False, activity=AgentActivity(),
        )
        result = await orchestrator.run(case.spec())
        assert result.status == "SUCCEEDED"
        assert result.failure_code is None
        assert result.proposal is not None
        assert result.proposal.type == expected_type
        assert result.proposal.target_player_id == expected_target
        assert result.proposal.message == expected_message
        assert case.state == before
        assert case.submissions == []
        assert len(provider.requests) == len(outputs)
        assert len(repository.completed) == 1
        assert repository.completed[0]["status"] == "SUCCEEDED"
        assert repository.completed[0]["normalized_proposal"] == result.proposal.model_dump(mode="json")
        assert repository.revoked == ["synthetic-hash"]
        receipt = await client.submit_action(
            game_id=case.state.game_id, player_id=case.actor.player_id,
            action=result.proposal.model_dump(mode="json"),
        )
    assert receipt["accepted"] is True
    assert receipt["result"]["accepted_state_version"] == before.state_version
    assert receipt["result"]["result_state_version"] == before.state_version + 1
    assert case.state.state_version == before.state_version + 1
    assert len(case.state.operations) == len(before.operations) + 1
    operation = case.state.operations[-1]
    command = {"NIGHT_ACTION": "SUBMIT_NIGHT_ACTION", "VOTE": "SUBMIT_VOTE"}.get(
        expected_type, expected_type
    )
    assert operation.command == command
    assert operation.actor_id == case.actor.player_id
    assert operation.target_id == expected_target
    assert operation.text == expected_message
    assert case.submissions == [{
        "game_id": case.state.game_id, "window_id": case.window_id,
        "actor_player_id": case.actor.player_id, "action_type": command,
        "target_player_id": expected_target, "message": expected_message,
        "source": "AGENT", "observed_state_version": before.state_version,
    }]
    assert len([c for c in case.transport_calls if c["method"] == "tools/call"]) == 1
    if expected_type in {"SPEAK", "PASS"}:
        assert case.actor.player_id in case.state.speech_actors
    elif expected_type == "VOTE":
        assert case.state.votes[case.actor.player_id].target_id == expected_target
    else:
        action = case.state.night_actions[case.actor.player_id]
        assert action.target_id == expected_target
        assert action.action_type is ROLE_ACTIONS[case.actor.role]
    return SimpleNamespace(result=result, provider=provider, repository=repository, receipt=receipt)


def assert_invalid_proposal(case, payload):
    """거부의 고정 Provider 코드·운영 분류와 입력·상태 미변경을 동시에 확인한다."""

    context = case.contexts()
    original_context, original_payload, original_state = deepcopy(context), deepcopy(payload), deepcopy(case.state)
    with pytest.raises(LLMResponseError) as failure:
        AgentOrchestrator._validate_proposal(case.spec(), payload, context)
    assert failure.value.code == "LLM_RESPONSE_ERROR"
    assert AgentOrchestrator._failure_code(failure.value) == "PROPOSAL_INVALID"
    assert context == original_context
    assert payload == original_payload
    assert case.state == original_state
    assert case.submissions == []
    return failure.value


@SAMPLES
@pytest.mark.parametrize("text_variant", ["plain", "one", "199", "200", "nfc", "whitespace"])
def test_agt_001_discussion_speak_is_normalized_and_submitted(make_case, sample_index, text_variant):
    """1~200자·NFC·공백 변형이 첫날과 이후 토론에서 실제 발언으로 한 번 반영된다."""

    case = make_case(day=1 + sample_index % 5)
    payloads = {
        "plain": (f"합성 단서 {sample_index}의 근거를 확인하자.", f"합성 단서 {sample_index}의 근거를 확인하자."),
        "one": ("가", "가"), "199": ("가" * 199, "가" * 199),
        "200": ("나" * 200, "나" * 200), "nfc": ("가나 증거", "가나 증거"),
        "whitespace": (f"  단서\n\t{sample_index}\u00a0  확인  ", f"단서 {sample_index} 확인"),
    }
    raw, normalized = payloads[text_variant]
    asyncio.run(run_and_submit(case, [{"type": "SPEAK", "message": raw}],
                               expected_type="SPEAK", expected_message=normalized))


@SAMPLES
def test_agt_002_later_day_pass_is_submitted(make_case, sample_index):
    """둘째 날 이후 PASS는 내용을 만들지 않고 실제 차례 완료로 제출된다."""

    case = make_case(day=2 + (sample_index // 4) % 4)
    rationale = "NO_NEW_INFORMATION" if sample_index % 2 else None
    asyncio.run(run_and_submit(case, [{"type": "PASS", "public_rationale": rationale}],
                               expected_type="PASS"))
    assert case.state.speech_had_content is False


@SAMPLES
def test_agt_002_first_day_pass_is_rejected_without_mutation(make_case):
    """허용 조건에서 제외되는 첫날 PASS는 proposal과 Engine 양쪽에서 거부된다."""

    case = make_case(day=1)
    assert case.context("turn")["data"]["allowed_tools"] == ["propose_speech"]
    assert_invalid_proposal(case, {"type": "PASS"})
    before = deepcopy(case.state)
    with pytest.raises(RuleViolation) as failure:
        GameEngine().pass_turn(case.state, case.actor.player_id)
    assert str(failure.value) == "ACTION_NOT_ALLOWED"
    assert case.state == before
    assert case.submissions == []


@SAMPLES
def test_agt_003_live_vote_target_is_submitted(make_case, sample_index):
    """인원수·좌석·생존 후보를 바꿔 자기 제외 유효 투표가 실제 표로 저장되는지 확인한다."""

    case = make_case(phase=GamePhase.DAY_VOTE)
    targets = _actor_target_ids(case.state, case.actor.player_id)
    target = targets[sample_index % len(targets)]
    assert case.actor.player_id not in targets
    assert all(case.state.player_by_id[identifier].alive for identifier in targets)
    asyncio.run(run_and_submit(case, [{"type": "VOTE", "target_player_id": str(target)}],
                               expected_type="VOTE", expected_target=target))


@SAMPLES
@pytest.mark.parametrize("role", NIGHT_ROLES)
def test_agt_004_role_night_action_is_checked_and_submitted(make_case, sample_index, role):
    """마피아·탐정·의사의 올바른 행동만 반영되고 불일치 능력은 먼저 거부된다."""

    case = make_case(phase=GamePhase.NIGHT_ACTION, role=role)
    targets = _actor_target_ids(case.state, case.actor.player_id)
    target = targets[sample_index % len(targets)]
    expected_action = ROLE_ACTIONS[role]
    wrong_action = next(action for action in NightActionType if action is not expected_action)
    before = deepcopy(case.state)
    with pytest.raises(RuleViolation) as failure:
        GameEngine().submit_night_action(case.state, case.actor.player_id, wrong_action, target)
    assert str(failure.value) == "ROLE_ACTION_INVALID"
    assert rule_error(failure.value).code == "ACTION_NOT_ALLOWED"
    assert case.state == before
    asyncio.run(run_and_submit(case, [{"type": "NIGHT_ACTION", "target_player_id": str(target)}],
                               expected_type="NIGHT_ACTION", expected_target=target))


@SAMPLES
def test_agt_004_nine_living_doctor_can_submit_self_protection(make_case):
    """9인 전원 생존·의사 자기 보호의 후보 상한 충돌을 각 표본에서 숨김없이 확인한다.

    제품 규칙과 Backend projection은 자기 자신을 포함한 9명을 허용한다. 전송
    계층이 이 정상 후보 집합을 거부하면 성공 기대를 유지해 회귀 실패로 기록한다.
    """

    case = make_case(phase=GamePhase.NIGHT_ACTION, role=PlayerRole.DOCTOR,
                     day=1, player_count=9)
    targets = _actor_target_ids(case.state, case.actor.player_id)
    assert len(case.state.alive_players) == len(targets) == 9
    assert case.actor.player_id in targets
    assert len(case.context("turn")["data"]["valid_targets"]) == 9
    asyncio.run(run_and_submit(
        case, [{"type": "NIGHT_ACTION", "target_player_id": str(case.actor.player_id)}],
        expected_type="NIGHT_ACTION", expected_target=case.actor.player_id,
    ))


@SAMPLES
@pytest.mark.parametrize("forbidden_type", ["VOTE", "NIGHT_ACTION"])
def test_agt_005_discussion_rejects_wrong_action_at_each_boundary(make_case, forbidden_type):
    """토론의 투표·밤 행동을 Orchestrator·MCP allowlist·Engine에서 각각 거부한다."""

    case = make_case(role=PlayerRole.MAFIA)
    target = next(p.player_id for p in case.state.alive_players if p is not case.actor)
    payload = {"type": forbidden_type, "target_player_id": str(target)}
    assert_invalid_proposal(case, payload)
    before = deepcopy(case.state)
    with pytest.raises(RuleViolation) as failure:
        if forbidden_type == "VOTE":
            GameEngine().submit_vote(case.state, case.actor.player_id, target)
        else:
            GameEngine().submit_night_action(case.state, case.actor.player_id, NightActionType.ATTACK, target)
    assert str(failure.value) == "INVALID_PHASE"
    assert rule_error(failure.value).code == "INVALID_PHASE"
    assert case.state == before

    async def reject_submission():
        async with httpx.AsyncClient(transport=httpx.MockTransport(case.handle_request)) as http_client:
            client = case.client(http_client)
            await client.get_context(capability="synthetic-unused", scope="turn")
            call_count = len(case.transport_calls)
            with pytest.raises(ValueError, match="^MCP action is not allowed in this window$"):
                await client.submit_action(game_id=case.state.game_id,
                                           player_id=case.actor.player_id, action=payload)
            assert len(case.transport_calls) == call_count

    asyncio.run(reject_submission())
    assert case.state == before
    assert case.submissions == []


@SAMPLES
@pytest.mark.parametrize("action_role", ["VOTE", "MAFIA", "DETECTIVE", "DOCTOR"])
@pytest.mark.parametrize("target_kind", ["dead", "self", "foreign"])
def test_agt_006_target_rejection_and_doctor_self_exception(make_case, action_role, target_kind):
    """사망·자기·다른 게임 대상을 검사하되 의사 자기 보호는 허용 결과까지 확인한다."""

    voting = action_role == "VOTE"
    case = make_case(
        phase=GamePhase.DAY_VOTE if voting else GamePhase.NIGHT_ACTION,
        role=PlayerRole.CITIZEN if voting else PlayerRole(action_role),
    )
    if target_kind == "self":
        target = case.actor.player_id
    elif target_kind == "foreign":
        target = case.identifier(5000)
    else:
        player = next(p for p in case.state.players if p is not case.actor)
        player.alive = False
        target = player.player_id
    action_type = "VOTE" if voting else "NIGHT_ACTION"
    payload = {"type": action_type, "target_player_id": str(target)}
    if action_role == "DOCTOR" and target_kind == "self":
        assert target in _actor_target_ids(case.state, case.actor.player_id)
        asyncio.run(run_and_submit(case, [payload], expected_type=action_type, expected_target=target))
        assert case.state.night_actions[target].action_type is NightActionType.PROTECT
        return
    assert target not in _actor_target_ids(case.state, case.actor.player_id)
    assert_invalid_proposal(case, payload)
    before = deepcopy(case.state)
    with pytest.raises(RuleViolation) as failure:
        if voting:
            GameEngine().submit_vote(case.state, case.actor.player_id, target)
        else:
            GameEngine().submit_night_action(case.state, case.actor.player_id, ROLE_ACTIONS[case.actor.role], target)
    assert str(failure.value) == {"dead": "TARGET_DEAD", "self": "SELF_TARGET_INVALID",
                                 "foreign": "PLAYER_NOT_FOUND"}[target_kind]
    assert rule_error(failure.value).code == (
        "ACTION_NOT_ALLOWED" if target_kind == "foreign" else "TARGET_INVALID"
    )
    assert case.state == before
    assert case.submissions == []


@SAMPLES
@pytest.mark.parametrize("action_type,missing_kind", [
    ("SPEAK", "omitted"), ("SPEAK", "null"), ("SPEAK", "blank"),
    ("VOTE", "omitted"), ("VOTE", "null"),
    ("NIGHT_ACTION", "omitted"), ("NIGHT_ACTION", "null"),
])
def test_agt_007_missing_message_or_target_is_repaired_before_submission(make_case, action_type, missing_kind):
    """필수 message·target의 누락·null·빈 문자열은 거부되고 단 한 번 교정 후 제출된다."""

    phase = {"SPEAK": GamePhase.DAY_DISCUSSION, "VOTE": GamePhase.DAY_VOTE,
             "NIGHT_ACTION": GamePhase.NIGHT_ACTION}[action_type]
    case = make_case(phase=phase, role=PlayerRole.DETECTIVE)
    field = "message" if action_type == "SPEAK" else "target_player_id"
    malformed = {"type": action_type}
    if missing_kind != "omitted":
        malformed[field] = "  \n\t " if missing_kind == "blank" else None
    original = deepcopy(malformed)
    with pytest.raises(LLMResponseError) as failure:
        normalize_agent_proposal(malformed)
    assert failure.value.code == "LLM_RESPONSE_ERROR"
    assert str(failure.value) == ("SPEAK proposal requires message" if action_type == "SPEAK"
                                 else f"{action_type} proposal requires target")
    assert malformed == original
    assert_invalid_proposal(case, malformed)
    target = None if action_type == "SPEAK" else _actor_target_ids(case.state, case.actor.player_id)[-1]
    message = "합성 공개 근거를 확인하자." if action_type == "SPEAK" else None
    corrected = {"type": action_type, "message": message,
                 "target_player_id": str(target) if target is not None else None}
    run = asyncio.run(run_and_submit(
        case, [malformed, corrected], expected_type=action_type,
        expected_target=target, expected_message=message,
    ))
    assert len(run.provider.requests) == 2
    assert "한 번 교정한다" in run.provider.requests[1].messages[1]["content"]
    assert "한 번 교정한다" not in run.provider.requests[0].messages[1]["content"]


@SAMPLES
@pytest.mark.parametrize("denial", ["ai-gm-guide", "gm-me", "gm-turn", "gm-persona", "foreign-ai", "human-ai"])
def test_agt_008_forbidden_subject_scope_is_denied_without_mutation(make_case, denial):
    """GM의 개인 scope·AI의 GM scope·비소속/인간 actor를 실제 projection이 거부한다."""

    case = make_case()
    subject_type, subject_id, scope = "AI_PLAYER", case.actor.player_id, "me"
    if denial == "ai-gm-guide":
        scope = "gm-guide"
    elif denial.startswith("gm-"):
        subject_type, subject_id, scope = "GM", case.state.game_id, denial.removeprefix("gm-")
    elif denial == "foreign-ai":
        subject_id = case.identifier(5000)
    else:
        subject_id = next(p.player_id for p in case.state.players if p.kind is PlayerKind.HUMAN)
    before = deepcopy(case.state)
    with pytest.raises(PermissionError) as failure:
        case.context(scope, subject_type=subject_type, subject_id=subject_id)
    assert str(failure.value) == "CAPABILITY_DENIED"
    assert case.state == before
    assert case.submissions == []
    assert case.transport_calls == []


@SAMPLES
@pytest.mark.parametrize("violation", ["subject_id", "me_player_id", "extra_private_field"])
def test_agt_008_mcp_client_rejects_foreign_context_binding(make_case, violation):
    """합성 전송의 다른 actor·추가 비공개 필드를 실제 MCP client가 고정 코드로 거부한다."""

    case = make_case()
    before = deepcopy(case.state)

    def corrupt(payload):
        if violation == "subject_id":
            payload["subject_id"] = str(case.identifier(5000))
        elif violation == "me_player_id":
            payload["data"]["player_id"] = str(case.identifier(5000))
        else:
            payload["data"]["other_player_private"] = "다른 참가자의 합성 비공개 자료"

    case.mutate_context = corrupt

    async def read_rejected_context():
        async with httpx.AsyncClient(transport=httpx.MockTransport(case.handle_request)) as http_client:
            client = case.client(http_client)
            with pytest.raises(McpContextError) as failure:
                await client.get_context(capability="synthetic-unused", scope="me")
            assert failure.value.code == "MCP_CONTEXT_CONTRACT"
            assert client._last_context is None

    asyncio.run(read_rejected_context())
    assert case.state == before
    assert case.submissions == []
    assert not any(call["method"] == "tools/call" for call in case.transport_calls)


@SAMPLES
@pytest.mark.parametrize("phase", [GamePhase.DAY_DISCUSSION, GamePhase.DAY_VOTE, GamePhase.NIGHT_ACTION])
def test_agt_008_private_changes_do_not_interfere_with_actor_context(make_case, sample_index, phase):
    """다른 사람의 역할·개인 자료·수신자 위조가 공개·본인·행동 Context를 바꾸지 않는다.

본인 조사 결과는 실제로 보존되는 양성 대조군이다. 다른 수신자·게임·PUBLIC
audience·미래 원장 행은 실제 scoped_private_events가 제거하므로 단순 빈 목록
비교만으로 정보 격리 성공을 주장하지 않는다.
"""

    case = make_case(phase=phase, role=PlayerRole.DETECTIVE, day=2 + (sample_index // 4) % 4)
    target = next(p.player_id for p in case.state.players if p is not case.actor)
    own = {
        "id": case.identifier(1200), "game_id": case.state.game_id,
        "audience": "PLAYER", "audience_player_id": case.actor.player_id,
        "schema_version": 1, "sequence": 1, "state_version": case.state.state_version,
        "event_type": "INVESTIGATION_RESULT", "created_at": case.now,
        "payload": {"round": case.state.round - 1 if phase is GamePhase.NIGHT_ACTION else case.state.round,
                    "target_player_id": str(target),
                    "is_mafia": bool(sample_index % 2)},
    }
    case.private_rows = [deepcopy(own)]
    before_state = deepcopy(case.state)
    baseline = case.contexts()
    assert len(baseline["me"]["data"]["private_events"]) == 1
    assert baseline["me"]["data"]["private_events"][0]["data"]["is_mafia"] is bool(sample_index % 2)
    changed = deepcopy(case.state)
    others = [p for p in changed.players if p.player_id != case.actor.player_id and p.alive]
    different_role = next(player for player in others if player.role is not others[0].role)
    original_roles = (others[0].role, different_role.role)
    others[0].role, different_role.role = different_role.role, others[0].role
    assert (others[0].role, different_role.role) != original_roles
    for player in others:
        case.facts[player.player_id] = {"alibi": "변경된 타인 합성 알리바이", "observation": "변경된 타인 합성 관찰"}
    bad_rows = []
    for index, mutation in enumerate((
        {"audience_player_id": target}, {"game_id": case.identifier(5000)},
        {"audience": "PUBLIC"}, {"sequence": case.sequence_limit + 1},
        {"state_version": case.state.state_version + 1},
    ), start=1):
        row = deepcopy(own)
        row.update(mutation, id=case.identifier(1200 + index))
        row["payload"]["is_mafia"] = not own["payload"]["is_mafia"]
        bad_rows.append(row)
    case.private_rows.extend(bad_rows)
    for scope in ("public", "me", "turn", "persona"):
        assert case.context(scope, state=changed) == baseline[scope]
    assert case.state == before_state
    assert case.submissions == []
    assert case.transport_calls == []
