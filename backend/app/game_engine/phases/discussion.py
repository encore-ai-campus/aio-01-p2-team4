"""일반·최종 토론 phase의 실행 진입점을 제공한다."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from backend.app.game_engine.errors import RuleViolation
from backend.app.game_engine.phases.transition import touch
from backend.app.game_engine.rules.discussion_rules import is_first_day_discussion, normalize_speech
from backend.app.game_engine.rules.player_rules import require_alive_player
from backend.app.models.enums import GamePhase
from backend.app.models.game_state import GameState

if TYPE_CHECKING:
    from backend.app.game_engine.engine import GameEngine


def advance_if_done(state: GameState) -> None:
    """생존자 발언이 끝났을 때 다음 토론 또는 다음 phase로 전환한다."""

    alive_ids = {player.player_id for player in state.alive_players}
    if alive_ids - state.speech_actors:
        return
    if state.phase is GamePhase.FINAL_DISCUSSION:
        state.phase = GamePhase.FINAL_ACCUSATION
        state.speech_actors.clear()
        return
    if state.day_number > 1 and not state.speech_had_content and not state.speech_question_cycle_used:
        # 둘째 날 이후 기본 순환이 전원 PASS일 때만 추가 기회를 한 번 연다.
        # 첫날과 최종 토론은 내용에 관계없이 한 순환으로 끝내야 한다.
        state.speech_question_cycle_used = True
        state.speech_actors.clear()
        return
    if state.day_number == 1:
        # round는 해소 횟수가 아니라 현재 밤 번호이므로 첫 입력 창을 열 때 1이 된다.
        state.round = 1
        state.phase = GamePhase.NIGHT_ACTION
    else:
        state.phase = GamePhase.DAY_VOTE
    state.speech_actors.clear()


def speak(state: GameState, actor_id: UUID, text: str) -> str:
    """생존 플레이어의 발언을 반영하고 정규화된 본문을 반환한다."""

    if state.phase not in {GamePhase.DAY_DISCUSSION, GamePhase.FINAL_DISCUSSION}:
        raise RuleViolation("INVALID_PHASE")
    actor = require_alive_player(state, actor_id)
    if actor.player_id in state.speech_actors:
        raise RuleViolation("DUPLICATE_ACTION")
    normalized = normalize_speech(text)
    state.speech_actors.add(actor.player_id)
    state.speech_had_content = True
    touch(state)
    advance_if_done(state)
    return normalized


def pass_turn(state: GameState, actor_id: UUID) -> None:
    """생존 플레이어의 PASS를 반영한다."""

    if state.phase not in {GamePhase.DAY_DISCUSSION, GamePhase.FINAL_DISCUSSION}:
        raise RuleViolation("INVALID_PHASE")
    actor = require_alive_player(state, actor_id)
    if actor.player_id in state.speech_actors:
        raise RuleViolation("DUPLICATE_ACTION")
    if is_first_day_discussion(state.phase, state.day_number):
        raise RuleViolation("ACTION_NOT_ALLOWED")
    state.speech_actors.add(actor.player_id)
    touch(state)
    advance_if_done(state)


def advance_final(engine: GameEngine, state: GameState) -> GameState:
    """최종 토론을 최종 고발 phase로 넘긴다."""

    return engine.advance_final_discussion(state)
