"""게임 phase 전이와 승패 판정만 담당하는 작은 상태 머신."""

from __future__ import annotations

from datetime import datetime, timezone

from backend.app.game_engine.rules.victory_rules import finish, standard_winner
from backend.app.models.enums import Faction, GamePhase, WinReason
from backend.app.models.game_state import GameState


def check_standard_winner(state: GameState) -> tuple[Faction, WinReason] | None:
    """현재 생존자 수로 표준 승패를 계산한다."""
    return standard_winner(state)


def finish_game(state: GameState, winner: Faction, reason: WinReason) -> None:
    """승패와 종료 상태를 한 번에 기록한다."""
    finish(state, winner, reason)


def after_night(state: GameState) -> None:
    """밤 결과 이후 표준 승패 또는 다음 낮을 선택한다."""

    winner = check_standard_winner(state)
    if winner:
        finish_game(state, *winner)
        return
    state.speech_question_cycle_used = False
    state.speech_had_content = False
    # 마지막 밤 뒤에도 아침은 새 날짜다. 여섯째 날에는 일반 투표 대신 최종 판정을 연다.
    state.day_number += 1
    if state.round >= 5:
        state.phase = GamePhase.FINAL_DISCUSSION
        state.speech_actors.clear()
        return
    state.phase = GamePhase.DAY_DISCUSSION
    state.speech_actors.clear()


def after_vote(state: GameState) -> None:
    """처형 뒤 승패가 없으면 밤 행동 단계로 넘긴다."""

    winner = check_standard_winner(state)
    if winner:
        finish_game(state, *winner)
        return
    # 재투표가 남아 있거나 처형으로 종료될 때는 증가하지 않고 실제 다음 밤 진입에서만 센다.
    state.round += 1
    state.phase = GamePhase.NIGHT_ACTION
    state.night_actions.clear()


def touch(state: GameState) -> None:
    """Client-visible 변경에만 state_version을 1 증가시킨다."""

    state.state_version += 1
    state.updated_at = datetime.now(timezone.utc)
