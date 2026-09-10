"""역할 공개 phase의 실행 진입점을 제공한다."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.app.game_engine.errors import RuleViolation
from backend.app.game_engine.phases.transition import touch
from backend.app.models.enums import GamePhase, GameStatus
from backend.app.models.game_state import GameState

if TYPE_CHECKING:
    from backend.app.game_engine.engine import GameEngine


def begin(state: GameState) -> GameState:
    """역할 공개를 종료하고 첫 토론 phase를 시작한다."""

    if state.status is not GameStatus.IN_PROGRESS or state.phase is not GamePhase.ROLE_REVEAL:
        raise RuleViolation("INVALID_PHASE")
    state.phase = GamePhase.DAY_DISCUSSION
    touch(state)
    return state
