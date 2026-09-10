"""게임 phase에서 다음 행동 주체와 순서를 계산하는 모듈."""

from __future__ import annotations

from backend.app.models.enums import GamePhase
from backend.app.models.game_state import GameState, PlayerState


def next_speech_actor(state: GameState) -> PlayerState | None:
    """현재 토론 순환에서 아직 발언하지 않은 첫 생존자를 반환한다."""

    if state.phase not in {GamePhase.DAY_DISCUSSION, GamePhase.FINAL_DISCUSSION}:
        return None
    return next(
        (player for player in state.alive_players if player.player_id not in state.speech_actors),
        None,
    )


def speech_cycle(state: GameState) -> int:
    """둘째 날 이후 전원 PASS의 추가 순환만 cycle 2로 복원한다."""

    return 2 if state.phase is GamePhase.DAY_DISCUSSION and state.day_number >= 2 and state.speech_question_cycle_used else 1



__all__ = ["next_speech_actor", "speech_cycle"]
