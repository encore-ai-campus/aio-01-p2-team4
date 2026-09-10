"""플레이어 식별자와 생존 상태를 검증하는 순수 규칙."""

from __future__ import annotations

from uuid import UUID

from backend.app.game_engine.errors import RuleViolation
from backend.app.models.game_state import GameState, PlayerState


def find_player(state: GameState, player_id: UUID | None) -> PlayerState:
    """상태에 포함된 플레이어만 반환하고 외부 입력 오류를 공통 코드로 바꾼다."""

    if player_id is None or player_id not in state.player_by_id:
        raise RuleViolation("PLAYER_NOT_FOUND")
    return state.player_by_id[player_id]


def require_alive_player(state: GameState, player_id: UUID | None) -> PlayerState:
    """명령 실행 주체가 존재하고 생존 중인지 확인한다."""

    player = find_player(state, player_id)
    if not player.alive:
        raise RuleViolation("PLAYER_DEAD")
    return player


def eliminate_player(state: GameState, target_id: UUID) -> None:
    """생존 플레이어를 사망 처리하고 이미 죽은 대상은 중복 처리하지 않는다."""

    target = state.player_by_id.get(target_id)
    if target is None or not target.alive:
        raise RuleViolation("TARGET_DEAD")
    target.alive = False

