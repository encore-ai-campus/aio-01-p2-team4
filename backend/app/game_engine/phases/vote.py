"""일반 투표·재투표 phase의 실행 진입점을 제공한다."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from backend.app.game_engine.errors import RuleViolation
from backend.app.game_engine.fallback import auto_vote_target
from backend.app.game_engine.phases.transition import after_vote, touch
from backend.app.game_engine.rules.player_rules import eliminate_player, find_player, require_alive_player
from backend.app.game_engine.rules.vote_rules import leaders, valid_targets, vote_weight
from backend.app.models.enums import GamePhase
from backend.app.models.game_state import GameState, Vote

if TYPE_CHECKING:
    from backend.app.game_engine.engine import GameEngine


def submit(state: GameState, actor_id: UUID, target_id: UUID,
           *, ability_id: str | None = None) -> GameState:
    """투표 한 건을 검증하고 상태에 반영한다."""

    if state.phase not in {GamePhase.DAY_VOTE, GamePhase.REVOTE}:
        raise RuleViolation("INVALID_PHASE")
    actor = require_alive_player(state, actor_id)
    if actor.player_id in state.votes:
        raise RuleViolation("DUPLICATE_ACTION")
    target = find_player(state, target_id)
    if not target.alive:
        raise RuleViolation("TARGET_DEAD")
    if actor.player_id == target.player_id:
        raise RuleViolation("SELF_TARGET_INVALID")
    if target not in valid_targets(state, actor):
        raise RuleViolation("TARGET_INVALID")
    vote_weight(state, actor.player_id, ability_id)
    state.votes[actor.player_id] = Vote(actor.player_id, target_id, ability_id)
    touch(state)
    return state


def resolve(state: GameState, *, force: bool = False) -> GameState:
    """투표를 집계하고 처형 또는 재투표로 전환한다."""

    if state.phase not in {GamePhase.DAY_VOTE, GamePhase.REVOTE}:
        raise RuleViolation("INVALID_PHASE")
    vote_phase = state.phase
    alive = state.alive_players
    if not force and any(player.player_id not in state.votes for player in alive):
        raise RuleViolation("WINDOW_NOT_READY")
    for actor in alive:
        if actor.player_id not in state.votes:
            target = auto_vote_target(state, actor)
            state.votes[actor.player_id] = Vote(actor.player_id, target.player_id)
    vote_leaders = leaders(state.votes)
    if len(vote_leaders) > 1 and state.phase is GamePhase.DAY_VOTE:
        state.revote_candidates = set(vote_leaders)
        state.phase = GamePhase.REVOTE
        state.votes.clear()
        touch(state)
        return state
    if len(vote_leaders) == 1:
        eliminate_player(state, vote_leaders[0])
    state.votes.clear()
    state.revote_candidates.clear()
    touch(state)
    after_vote(state)
    return state
