"""최종 고발 phase의 실행 진입점을 제공한다."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from backend.app.game_engine.errors import RuleViolation
from backend.app.game_engine.fallback import auto_vote_target
from backend.app.game_engine.phases.transition import touch
from backend.app.game_engine.rng import DeterministicRng
from backend.app.game_engine.rules.player_rules import find_player, require_alive_player
from backend.app.game_engine.rules.vote_rules import leaders
from backend.app.game_engine.rules.victory_rules import finish
from backend.app.models.enums import Faction, GamePhase, PlayerRole, WinReason
from backend.app.models.game_state import GameState, Vote

if TYPE_CHECKING:
    from backend.app.game_engine.engine import GameEngine


def submit(state: GameState, actor_id: UUID, target_id: UUID) -> GameState:
    """생존자별 첫 유효 지목을 누적하고 전원이 제출했을 때만 최종 판정한다."""

    if state.phase is not GamePhase.FINAL_ACCUSATION:
        raise RuleViolation("INVALID_PHASE")
    actor = require_alive_player(state, actor_id)
    if actor.player_id in state.votes:
        raise RuleViolation("DUPLICATE_ACTION")
    target = find_player(state, target_id)
    if not target.alive or target.player_id == actor.player_id:
        raise RuleViolation("TARGET_INVALID")
    state.votes[actor.player_id] = Vote(actor.player_id, target_id)
    touch(state)
    if all(player.player_id in state.votes for player in state.alive_players):
        resolve(state)
    return state


def resolve(state: GameState, *, force: bool = False) -> GameState:
    """전원 표를 집계하고 최다 득표자 또는 동률 후보의 결정적 추첨으로 종료한다.

    마감 여부는 서비스 계층이 검증하고 force로 전달한다. 이미 제출한 표는
    그대로 보존하며 미제출자만 자동 선택하므로 재접속이 판정을 바꾸지 않는다.
    """

    if state.phase is not GamePhase.FINAL_ACCUSATION:
        raise RuleViolation("INVALID_PHASE")
    missing = [player for player in state.alive_players if player.player_id not in state.votes]
    if missing and not force:
        raise RuleViolation("WINDOW_NOT_READY")
    for actor in missing:
        target = auto_vote_target(state, actor)
        state.votes[actor.player_id] = Vote(actor.player_id, target.player_id)
    # 표 제출 순서가 아니라 후보 집합이 난수 입력을 결정해야 replay가 동일하다.
    candidates = sorted(leaders(state.votes))
    target_id = DeterministicRng(state.seed).choice(candidates, f"final-accusation:{state.round}")
    target = find_player(state, target_id)
    state.final_accusation_target = target_id
    winner = Faction.CITIZEN if target.faction is Faction.MAFIA else Faction.MAFIA
    reason = WinReason.FINAL_MAFIA_SELECTED if target.faction is Faction.MAFIA else WinReason.FINAL_NON_MAFIA_SELECTED
    touch(state)
    finish(state, winner, reason)
    return state
