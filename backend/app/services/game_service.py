"""PostgreSQL 게임 service의 compatibility facade와 공통 저장소 경계.

실제 생성·읽기·lifecycle·discussion·action orchestration은
``services.game`` 하위 모듈이 소유한다. 이 파일은 기존 import 경로와
PostgreSQL service 사이의 호환 경계를 유지한다.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from psycopg.rows import dict_row

from backend.app.game_engine.engine import GameEngine
from backend.app.game_engine.errors import RuleViolation
from backend.app.game_engine.rng import DeterministicRng
from backend.app.core.errors import ApiError
from backend.app.infrastructure.transaction import TransactionManager, lock_idempotency
from backend.app.models.enums import (
    Faction,
    GamePhase,
    GameStatus,
    NightActionType,
    PlayerKind,
    PlayerRole,
    WinReason,
)
from backend.app.models.game_state import GameState, PlayerState
from backend.app.repositories.agent_repository import PostgresAgentRepository
from backend.app.repositories.action_repository import (
    ActionSubmissionInsert,
    ActionWindowInsert,
    PostgresActionRepository,
)
from backend.app.repositories.event_repository import PostgresEventRepository
from backend.app.repositories.game_repository import GameStateKeyring, PostgresGameRepository
from backend.app.repositories.outbox_repository import PostgresOutboxRepository
from backend.app.repositories.player_repository import (
    PlayerInsert,
    PostgresPlayerRepository,
    ScenarioFactInsert,
)
from backend.app.repositories.receipt_repository import PostgresReceiptRepository
from backend.app.repositories.scenario_repository import PostgresScenarioRepository
from backend.app.repositories.user_repository import PostgresUserRepository
from backend.app.schemas.command_schema import GameCommandRequest
from backend.app.schemas.feedback_schema import FeedbackRequest
from backend.app.schemas.game_schema import CreateGameRequest
from backend.app.services.game.constants import INTRO_MESSAGE, SCENARIOS
from backend.app.services.game.helpers import (
    create_game_result as _create_game_result,
    request_hash as _request_hash,
    window_id as uuid5_for_window,
)
# 기존 import 경로를 유지하되 실제 읽기 구현은 snapshot service가 소유한다.
from backend.app.services.game.game_read_service import PostgresGameReadService
from backend.app.services.game.protocols import UserWriteService
from backend.app.services.game.window_service import next_window as build_next_window
from backend.app.services.game.event_sync_service import build_operation_batches
from backend.app.services.game.result_service import build_result

class PostgresGameCreationService:
    """새 게임에 필요한 모든 DB 행을 하나의 transaction으로 만드는 서비스.

    이 클래스는 아직 공개 router의 기본 구현을 바꾸지 않는다. 생성된 게임을 DB에서
    snapshot으로 복원하는 read adapter가 연결되기 전까지는 메모리 API와 섞이면 안 되기
    때문이다. 단, 이 클래스의 create는 실제 전환 때 그대로 사용할 완전한 원자 단위다.
    """

    ROUTE_SCOPE = "POST /api/v1/games"
    AGENT_CONFIG_VERSION = "agent-config-v1"

    def __init__(
        self,
        *,
        transactions: TransactionManager,
        keyring: GameStateKeyring,
        users: PostgresUserRepository | None = None,
        games: PostgresGameRepository | None = None,
        scenarios: PostgresScenarioRepository | None = None,
        players: PostgresPlayerRepository | None = None,
        agents: PostgresAgentRepository | None = None,
        events: PostgresEventRepository | None = None,
        outbox: PostgresOutboxRepository | None = None,
        receipts: PostgresReceiptRepository | None = None,
    ) -> None:
        """각 테이블 저장소를 주입해 테스트가 실제 DB 없이도 흐르게 한다."""

        self._transactions = transactions
        self._keyring = keyring
        self._users = users or PostgresUserRepository("")
        self._games = games or PostgresGameRepository()
        self._scenarios = scenarios or PostgresScenarioRepository()
        self._players = players or PostgresPlayerRepository()
        self._agents = agents or PostgresAgentRepository()
        self._events = events or PostgresEventRepository(self._games)
        self._outbox = outbox or PostgresOutboxRepository()
        self._receipts = receipts or PostgresReceiptRepository()

    def create(
        self,
        owner_user_id: UUID,
        payload: CreateGameRequest,
        idempotency_key: UUID,
    ) -> tuple[dict[str, Any], bool]:
        """생성 service에 transaction orchestration을 위임한다."""

        from backend.app.services.game.creation_service import create_game

        return create_game(self, owner_user_id, payload, idempotency_key)

    def _find_replay(
        self,
        cursor: Any,
        *,
        owner_user_id: UUID,
        idempotency_key: UUID,
        request_hash: str,
    ) -> dict[str, Any] | None:
        """동일 idempotency key의 불변 결과만 재사용한다."""

        previous = self._receipts.find(
            cursor,
            principal_type="USER",
            principal_id=owner_user_id,
            idempotency_key=idempotency_key,
        )
        if previous is None:
            return None
        if (
            previous["request_hash"] != request_hash
            or previous["route_scope"] != self.ROUTE_SCOPE
        ):
            raise ApiError(
                status_code=409,
                code="IDEMPOTENCY_KEY_REUSED",
                message="같은 Idempotency-Key가 다른 요청에 사용되었습니다.",
            )
        result_body = previous["result_body"]
        if not isinstance(result_body, dict):
            raise RuntimeError("Stored game creation receipt is invalid")
        return copy.deepcopy(result_body)

    def _build_initial_game(
        self,
        cursor: Any,
        *,
        owner_user_id: UUID,
        payload: CreateGameRequest,
    ) -> tuple[GameState, Mapping[str, Any], list[PlayerInsert], list[ScenarioFactInsert]]:
        """생성 service에 초기 게임 조합을 위임한다."""

        from backend.app.services.game.creation_service import build_initial_game

        return build_initial_game(self, cursor, owner_user_id=owner_user_id, payload=payload)

class PostgresBeginGameService:
    """ROLE_REVEAL에서 첫날 토론을 여는 BEGIN_GAME 전용 DB transaction 서비스."""

    def __init__(
        self,
        *,
        transactions: TransactionManager,
        keyring: GameStateKeyring,
        games: PostgresGameRepository | None = None,
        players: PostgresPlayerRepository | None = None,
        actions: PostgresActionRepository | None = None,
        events: PostgresEventRepository | None = None,
        outbox: PostgresOutboxRepository | None = None,
        receipts: PostgresReceiptRepository | None = None,
    ) -> None:
        """한 명령의 모든 DB 변경을 같은 transaction 안에서 처리한다."""

        self._transactions = transactions
        self._keyring = keyring
        self._games = games or PostgresGameRepository()
        self._players = players or PostgresPlayerRepository()
        self._actions = actions or PostgresActionRepository()
        self._events = events or PostgresEventRepository(self._games)
        self._outbox = outbox or PostgresOutboxRepository()
        self._receipts = receipts or PostgresReceiptRepository()

    def _find_replay(
        self,
        cursor: Any,
        *,
        owner_user_id: UUID,
        idempotency_key: UUID,
        request_hash: str,
        route_scope: str,
    ) -> dict[str, Any] | None:
        """같은 사용자·key의 terminal 명령 결과만 안전하게 재사용한다."""

        previous = self._receipts.find(
            cursor,
            principal_type="USER",
            principal_id=owner_user_id,
            idempotency_key=idempotency_key,
        )
        if previous is None:
            return None
        if previous["request_hash"] != request_hash or previous["route_scope"] != route_scope:
            raise ApiError(
                status_code=409,
                code="IDEMPOTENCY_KEY_REUSED",
                message="같은 Idempotency-Key가 다른 요청에 사용되었습니다.",
            )
        result_body = previous["result_body"]
        if not isinstance(result_body, dict):
            raise RuntimeError("Stored command receipt is invalid")
        return copy.deepcopy(result_body)

    def _state_from_locked_game(
        self,
        cursor: Any,
        game_row: Mapping[str, Any],
    ) -> tuple[GameState, UUID]:
        """FOR UPDATE로 잠근 game과 player 행을 순수 엔진 상태로 복원한다."""

        game_id = UUID(str(game_row["id"]))
        seed = self._keyring.decrypt_seed(
            ciphertext=bytes(game_row["seed_ciphertext"]),
            nonce=bytes(game_row["seed_nonce"]),
            key_id=str(game_row["seed_key_id"]),
        )
        players: list[PlayerState] = []
        human_player_id: UUID | None = None
        for row in self._players.list_players(cursor, game_id=game_id):
            player_id = UUID(str(row["id"]))
            kind = PlayerKind(str(row["kind"]))
            players.append(
                PlayerState(
                    player_id=player_id,
                    seat=int(row["seat"]),
                    role=PlayerRole(str(row["role"])),
                    kind=kind,
                    display_name=str(row["display_name"]),
                    alive=bool(row["alive"]),
                    custom_role_name=row.get("custom_role_name"),
                    custom_role_catalog_version=row.get("custom_role_catalog_version"),
                    custom_ability_ids=tuple(row.get("custom_ability_ids") or ()),
                    custom_faction=Faction(str(row["faction"])) if row.get("custom_ability_ids") else None,
                )
            )
            if kind is PlayerKind.HUMAN:
                if human_player_id is not None or row["user_id"] is None:
                    raise RuntimeError("Persisted human player is invalid")
                human_player_id = player_id
        if human_player_id is None or len(players) != int(game_row["player_count"]):
            raise RuntimeError("Persisted players are incomplete")
        if not isinstance(game_row["updated_at"], datetime):
            raise RuntimeError("Persisted game timestamp is invalid")
        return (
            GameState(
                game_id=game_id,
                seed=seed,
                players=players,
                phase=GamePhase(str(game_row["phase"])),
                status=GameStatus(str(game_row["status"])),
                round=int(game_row["round"]),
                day_number=int(game_row["day_number"]),
                state_version=int(game_row["state_version"]),
                updated_at=game_row["updated_at"],
                mode=str(game_row.get("mode") or "STANDARD"),
            ),
            human_player_id,
        )

    def _append_front_events(
        self,
        cursor: Any,
        *,
        game_id: UUID,
        state: GameState,
        front_sequence: int,
    ) -> None:
        """한 BEGIN_GAME transaction의 complete operation batch를 append-only로 남긴다."""

        state_event = self._events.append(
            cursor,
            game_id=game_id,
            state_version=state.state_version,
            event_type="PHASE_CHANGED",
            audience="PUBLIC",
            front_sequence=front_sequence,
            operation_index=0,
            operation_type="SET_GAME_STATE",
            payload={
                "status": state.status.value,
                "phase": state.phase.value,
                "round": state.round,
                "day_number": state.day_number,
                "state_version": state.state_version,
                "fast_forward_enabled": False,
            },
        )
        began_event = self._events.append(
            cursor,
            game_id=game_id,
            state_version=state.state_version,
            event_type="GAME_BEGAN",
            audience="PUBLIC",
            front_sequence=front_sequence,
            operation_index=1,
            operation_type="APPEND_PUBLIC_EVENT",
            payload={"message": INTRO_MESSAGE},
        )
        self._outbox.enqueue(cursor, UUID(str(state_event["id"])))
        self._outbox.enqueue(cursor, UUID(str(began_event["id"])))

    def begin(
        self,
        owner_user_id: UUID,
        game_id: UUID,
        payload: GameCommandRequest,
        idempotency_key: UUID,
    ) -> tuple[dict[str, Any], bool]:
        """lifecycle 모듈의 BEGIN_GAME transaction orchestration을 호출한다."""

        from backend.app.services.game.lifecycle_service import begin_game

        return begin_game(self, owner_user_id, game_id, payload, idempotency_key)

    def append_front_events(self, cursor: Any, *, game_id: UUID, state: GameState, front_sequence: int) -> None:
        """BEGIN_GAME 공개 event batch를 service port로 기록한다."""

        self._append_front_events(cursor, game_id=game_id, state=state, front_sequence=front_sequence)


class PostgresGameSaveService(PostgresBeginGameService):
    """진행 중 게임을 안전하게 멈추는 SAVE_AND_EXIT DB transaction 서비스."""

    def _remaining_ms(window: Mapping[str, Any] | None, now: datetime) -> int | None:
        """deadline이 없는 상태는 None, timed window는 남은 정수 ms를 계산한다."""

        if window is None or window["window_kind"] == "SPEECH":
            return None
        deadline = window["deadline_at"]
        if not isinstance(deadline, datetime):
            raise RuntimeError("Timed action window deadline is invalid")
        return max(int((deadline - now).total_seconds() * 1000), 0)

    def _append_save_events(
        self,
        cursor: Any,
        *,
        game_id: UUID,
        state: GameState,
        front_sequence: int,
    ) -> None:
        """저장 상태와 GAME_SAVED 공개 event를 끊기지 않는 batch로 기록한다."""

        state_event = self._events.append(
            cursor,
            game_id=game_id,
            state_version=state.state_version,
            event_type="PHASE_CHANGED",
            audience="PUBLIC",
            front_sequence=front_sequence,
            operation_index=0,
            operation_type="SET_GAME_STATE",
            payload={
                "status": state.status.value,
                "phase": state.phase.value,
                "round": state.round,
                "day_number": state.day_number,
                "state_version": state.state_version,
                "fast_forward_enabled": state.fast_forward_enabled,
            },
        )
        saved_event = self._events.append(
            cursor,
            game_id=game_id,
            state_version=state.state_version,
            event_type="GAME_SAVED",
            audience="PUBLIC",
            front_sequence=front_sequence,
            operation_index=1,
            operation_type="APPEND_PUBLIC_EVENT",
            payload={"phase": state.phase.value, "round": state.round},
        )
        self._outbox.enqueue(cursor, UUID(str(state_event["id"])))
        self._outbox.enqueue(cursor, UUID(str(saved_event["id"])))

    def save(
        self,
        owner_user_id: UUID,
        game_id: UUID,
        payload: GameCommandRequest,
        idempotency_key: UUID,
        *,
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """lifecycle 모듈의 SAVE_AND_EXIT transaction orchestration을 호출한다."""

        from backend.app.services.game.lifecycle_service import save_game

        return save_game(self, owner_user_id, game_id, payload, idempotency_key, now=now)

    def append_save_events(self, cursor: Any, *, game_id: UUID, state: GameState, front_sequence: int) -> None:
        """SAVE_AND_EXIT 공개 event batch를 service port로 기록한다."""

        self._append_save_events(cursor, game_id=game_id, state=state, front_sequence=front_sequence)


class PostgresGameResumeService(PostgresBeginGameService):
    """저장된 게임을 같은 DB 원본에서 안전하게 이어 가는 RESUME transaction 서비스."""

    def _saved_remaining_ms(window: Mapping[str, Any] | None) -> int | None:
        """저장된 window의 종류와 PAUSED 상태를 검사해 재개 가능한 시간을 꺼낸다."""

        if window is None:
            return None
        if window["status"] != "PAUSED":
            raise RuntimeError("Saved game action window is not paused")
        window_kind = str(window["window_kind"])
        remaining_ms = window.get("remaining_ms_on_save")
        if window_kind == "SPEECH":
            if remaining_ms is not None:
                raise RuntimeError("Saved speech window contains a remaining time")
            return None
        if window_kind not in {"NIGHT", "VOTE", "REVOTE", "FINAL_VOTE"}:
            raise RuntimeError("Saved action window kind is invalid")
        if isinstance(remaining_ms, bool) or not isinstance(remaining_ms, int) or remaining_ms < 0:
            raise RuntimeError("Saved timed window remaining time is invalid")
        return remaining_ms

    def _append_resume_events(
        self,
        cursor: Any,
        *,
        game_id: UUID,
        state: GameState,
        front_sequence: int,
    ) -> None:
        """재개 상태와 GAME_RESUMED 공개 event를 하나의 순서 있는 batch로 남긴다."""

        state_event = self._events.append(
            cursor,
            game_id=game_id,
            state_version=state.state_version,
            event_type="PHASE_CHANGED",
            audience="PUBLIC",
            front_sequence=front_sequence,
            operation_index=0,
            operation_type="SET_GAME_STATE",
            payload={
                "status": state.status.value,
                "phase": state.phase.value,
                "round": state.round,
                "day_number": state.day_number,
                "state_version": state.state_version,
                "fast_forward_enabled": state.fast_forward_enabled,
            },
        )
        resumed_event = self._events.append(
            cursor,
            game_id=game_id,
            state_version=state.state_version,
            event_type="GAME_RESUMED",
            audience="PUBLIC",
            front_sequence=front_sequence,
            operation_index=1,
            operation_type="APPEND_PUBLIC_EVENT",
            payload={"phase": state.phase.value, "round": state.round},
        )
        self._outbox.enqueue(cursor, UUID(str(state_event["id"])))
        self._outbox.enqueue(cursor, UUID(str(resumed_event["id"])))

    def resume(
        self,
        owner_user_id: UUID,
        game_id: UUID,
        payload: GameCommandRequest,
        idempotency_key: UUID,
        *,
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """lifecycle 모듈의 RESUME transaction orchestration을 호출한다."""

        from backend.app.services.game.lifecycle_service import resume_game

        return resume_game(self, owner_user_id, game_id, payload, idempotency_key, now=now)

    def append_resume_events(self, cursor: Any, *, game_id: UUID, state: GameState, front_sequence: int) -> None:
        """RESUME 공개 event batch를 service port로 기록한다."""

        self._append_resume_events(cursor, game_id=game_id, state=state, front_sequence=front_sequence)


class PostgresDiscussionCommandService(PostgresBeginGameService):
    """사람의 SPEAK·PASS를 DB 원장과 다음 발언 차례에 함께 반영한다."""

    def submit(
        self,
        owner_user_id: UUID,
        game_id: UUID,
        payload: GameCommandRequest,
        idempotency_key: UUID,
        *,
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """discussion command 모듈의 transaction orchestration을 호출한다."""

        from backend.app.services.game.discussion_command import submit_discussion

        return submit_discussion(self, owner_user_id, game_id, payload, idempotency_key, now=now)

    def hydrate_discussion_state(self, cursor: Any, *, state: GameState, window: Mapping[str, Any]) -> None:
        """discussion 원장을 엔진 상태로 복원하는 service port다."""

        self._hydrate_discussion_state(cursor, state=state, window=window)

    def append_discussion_events(
        self,
        cursor: Any,
        *,
        game_id: UUID,
        state: GameState,
        actor_player_id: UUID,
        command_type: str,
        message: str | None,
        next_window: ActionWindowInsert | None,
        front_sequence: int,
        now: datetime,
    ) -> None:
        """discussion 공개 event batch를 service port로 기록한다."""

        self._append_discussion_events(
            cursor,
            game_id=game_id,
            state=state,
            actor_player_id=actor_player_id,
            command_type=command_type,
            message=message,
            next_window=next_window,
            front_sequence=front_sequence,
            now=now,
        )

    def _validate_human_discussion_window(
        *,
        state: GameState,
        human_player_id: UUID,
        window: Mapping[str, Any] | None,
        payload: GameCommandRequest,
    ) -> None:
        """다른 game window·AI 차례·닫힌 window의 발언을 저장 전에 차단한다."""

        if state.phase not in {GamePhase.DAY_DISCUSSION, GamePhase.FINAL_DISCUSSION}:
            raise ApiError(status_code=409, code="INVALID_PHASE", message="현재 발언 단계가 아닙니다.")
        if window is None or payload.window_id is None or UUID(str(window["id"])) != payload.window_id:
            raise ApiError(
                status_code=409,
                code="WINDOW_CLOSED",
                message="현재 행동 window가 더 이상 유효하지 않습니다.",
            )
        if (
            window["status"] != "OPEN"
            or window["window_kind"] != "SPEECH"
            or window["phase"] != state.phase.value
            or UUID(str(window["turn_player_id"])) != human_player_id
        ):
            raise ApiError(
                status_code=409,
                code="ACTION_NOT_ALLOWED",
                message="현재 발언 차례가 아닙니다.",
            )

    def _hydrate_discussion_state(
        self,
        cursor: Any,
        *,
        state: GameState,
        window: Mapping[str, Any],
    ) -> None:
        """원장 발언을 현재 순환의 메모리 규칙 상태로 복원한다."""

        cycle = int(window["cycle"])
        submissions = self._actions.list_discussion_submissions(
            cursor,
            game_id=state.game_id,
            phase=state.phase.value,
            round=state.round,
            cycle=cycle,
        )
        state.speech_actors = {UUID(str(row["actor_player_id"])) for row in submissions}
        state.speech_had_content = any(row["action_type"] == "SPEAK" for row in submissions)
        # 둘째 날 이후 추가 질문 순환은 DB window의 cycle=2가 원본이다. 메모리 기본값을
        # 믿으면 서버 재시작 뒤 같은 질문을 여러 번 열 수 있다.
        state.speech_question_cycle_used = state.day_number >= 2 and cycle == 2

    def _append_discussion_events(
        self,
        cursor: Any,
        *,
        game_id: UUID,
        state: GameState,
        actor_player_id: UUID,
        command_type: str,
        message: str | None,
        next_window: ActionWindowInsert | None,
        front_sequence: int,
        now: datetime,
    ) -> None:
        """상태·공개 발언·다음 window를 끊기지 않는 Front operation batch로 남긴다."""

        events: list[Mapping[str, Any]] = []
        events.append(
            self._events.append(
                cursor,
                game_id=game_id,
                state_version=state.state_version,
                event_type="PHASE_CHANGED",
                audience="PUBLIC",
                front_sequence=front_sequence,
                operation_index=0,
                operation_type="SET_GAME_STATE",
                payload={
                    "status": state.status.value,
                    "phase": state.phase.value,
                    "round": state.round,
                    "day_number": state.day_number,
                    "state_version": state.state_version,
                    "fast_forward_enabled": state.fast_forward_enabled,
                },
            )
        )
        if command_type != "END_DISCUSSION":
            event_payload: dict[str, Any] = {"player_id": str(actor_player_id)}
            if command_type == "SPEAK":
                event_payload["message"] = message
            events.append(
                self._events.append(
                    cursor,
                    game_id=game_id,
                    state_version=state.state_version,
                    event_type="PLAYER_SPOKE" if command_type == "SPEAK" else "PLAYER_PASSED",
                    audience="PUBLIC",
                    front_sequence=front_sequence,
                    operation_index=1,
                    operation_type="APPEND_PUBLIC_EVENT",
                    payload=event_payload,
                )
            )
        if next_window is None:
            window_operation = "CLEAR_ACTION_WINDOW"
            window_payload: dict[str, Any] = {"window_id": None}
        else:
            window_operation = "SET_ACTION_WINDOW"
            window_payload = {
                "window_id": str(next_window.window_id),
                "kind": next_window.window_kind,
                "cycle": next_window.cycle,
                "paused": False,
                "opened_state_version": next_window.opened_state_version,
                "server_time": now.isoformat().replace("+00:00", "Z"),
                "deadline_at": (
                    next_window.deadline_at.isoformat().replace("+00:00", "Z")
                    if next_window.deadline_at is not None
                    else None
                ),
                "remaining_ms": (
                    max(int((next_window.deadline_at - now).total_seconds() * 1000), 0)
                    if next_window.deadline_at is not None
                    else None
                ),
                "turn_player_id": (
                    str(next_window.turn_player_id) if next_window.turn_player_id is not None else None
                ),
                "has_submitted": False,
                "legal_actions": [],
                "valid_targets": [],
            }
        events.append(
            self._events.append(
                cursor,
                game_id=game_id,
                state_version=state.state_version,
                event_type="TURN_OPENED",
                audience="PUBLIC",
                front_sequence=front_sequence,
                operation_index=len(events),
                operation_type=window_operation,
                payload=window_payload,
            )
        )
        for event in events:
            self._outbox.enqueue(cursor, UUID(str(event["id"])))
