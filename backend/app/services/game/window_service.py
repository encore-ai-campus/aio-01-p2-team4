"""순서·시간 계산 결과를 저장용 action window로 조합하는 adapter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from backend.app.core.errors import ApiError
from backend.app.models.enums import GamePhase, GameStatus
from backend.app.models.game_state import GameState
from backend.app.repositories.action_repository import ActionWindowInsert
from backend.app.schemas.command_schema import GameCommandRequest
from backend.app.services.game.action_timer_service import deadline_for, timed_window_kind
from backend.app.services.game.helpers import window_id as uuid5_for_window
from backend.app.services.game.turn_order_service import next_speech_actor, speech_cycle


def next_window(state: GameState, now: datetime) -> ActionWindowInsert | None:
    """엔진이 확정한 phase에 맞는 단 하나의 다음 window를 만든다."""

    if state.phase in {GamePhase.DAY_DISCUSSION, GamePhase.FINAL_DISCUSSION}:
        next_actor = next((p for p in state.alive_players if p.kind.value == "AI"), None) or next_speech_actor(state)
        if next_actor is None:
            return None
        return ActionWindowInsert(
            window_id=uuid5_for_window(state.game_id, state.state_version),
            game_id=state.game_id,
            window_kind="SPEECH",
            phase=state.phase.value,
            round=state.round,
            cycle=speech_cycle(state),
            turn_player_id=next_actor.player_id,
            opened_state_version=state.state_version,
            deadline_at=now + timedelta(seconds=105),
        )
    window_kind = timed_window_kind(state.phase)
    if window_kind is None:
        return None
    return ActionWindowInsert(
        window_id=uuid5_for_window(state.game_id, state.state_version),
        game_id=state.game_id,
        window_kind=window_kind,
        phase=state.phase.value,
        round=state.round,
        cycle=1,
        turn_player_id=None,
        opened_state_version=state.state_version,
        deadline_at=deadline_for(state.phase, now),
    )


def validate_action_window(
    state: Any,
    window: Mapping[str, Any] | None,
    payload: GameCommandRequest,
    *,
    now: datetime | None = None,
) -> None:
    """행동 command가 현재 phase와 열린 window에 맞는지 검증한다.

    window의 저장 형식과 phase별 허용 종류는 게임 상태를 저장하는 서비스의
    공통 경계이므로 개별 command가 같은 검증을 복제하지 않게 한다. 실제 행동
    가능 여부와 대상 유효성은 GameEngine이 최종 판정한다.
    """

    expected_kind = {
        GamePhase.NIGHT_ACTION: "NIGHT",
        GamePhase.DAY_VOTE: "VOTE",
        GamePhase.REVOTE: "REVOTE",
        GamePhase.FINAL_ACCUSATION: "FINAL_VOTE",
    }.get(state.phase)
    if expected_kind is None:
        raise ApiError(status_code=409, code="INVALID_PHASE", message="현재 행동 단계가 아닙니다.")
    if (
        state.status is not GameStatus.IN_PROGRESS
        or window is None
        or payload.window_id is None
        or UUID(str(window["id"])) != payload.window_id
        or window["status"] != "OPEN"
        or window["window_kind"] != expected_kind
        or window["phase"] != state.phase.value
    ):
        raise ApiError(status_code=409, code="WINDOW_CLOSED", message="현재 행동 window가 더 이상 유효하지 않습니다.")
    deadline = window["deadline_at"]
    if not isinstance(deadline, datetime) or deadline.utcoffset() is None or deadline <= (now or datetime.now(UTC)):
        raise ApiError(status_code=409, code="WINDOW_CLOSED", message="행동 제출 시간이 마감되었습니다.")
    if payload.target_player_id is None:
        raise ApiError(status_code=422, code="INVALID_REQUEST", message="대상을 선택해야 합니다.")


def is_expired_window(state: GameState, window: Mapping[str, Any] | None, now: datetime) -> bool:
    """잠금 획득 뒤에도 현재 활성 window가 실제로 마감된 경우만 자동 해소한다."""

    return bool(
        state.status is GameStatus.IN_PROGRESS
        and window is not None
        and window["status"] == "OPEN"
        and window["phase"] == state.phase.value
        and window["window_kind"] == {GamePhase.NIGHT_ACTION: "NIGHT", GamePhase.DAY_VOTE: "VOTE", GamePhase.REVOTE: "REVOTE", GamePhase.FINAL_ACCUSATION: "FINAL_VOTE"}.get(state.phase)
        and isinstance(window["deadline_at"], datetime)
        and window["deadline_at"].utcoffset() is not None
        and window["deadline_at"] <= now
    )
