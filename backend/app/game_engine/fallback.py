"""AI나 타이머가 응답하지 않을 때 사용할 규칙 기반 선택."""

from __future__ import annotations

from backend.app.game_engine.rng import DeterministicRng
from backend.app.game_engine.rules.vote_rules import valid_targets
from backend.app.models.enums import NightActionType, PlayerRole
from backend.app.models.game_state import GameState, PlayerState


def auto_night_target(state: GameState, actor: PlayerState, action_type: NightActionType) -> PlayerState:
    """미제출 밤 행동의 대상을 결정한다.

    외부 모델을 호출하지 않고 생존자와 역할 규칙만 사용한다. 선택 기준은 seed로
    고정하므로 타임아웃이 발생해도 같은 게임 replay에서 결과가 달라지지 않는다.
    """

    candidates = [player for player in state.alive_players if player.player_id != actor.player_id]
    if action_type is NightActionType.ATTACK:
        # 마피아 전원 무응답의 진영 fallback에만 쓴다. 수동 공격은 동료도 허용한다.
        candidates = [player for player in candidates if player.role is not PlayerRole.MAFIA]
    if not candidates:
        raise ValueError("no valid night target")
    return DeterministicRng(state.seed).choice(
        candidates,
        (
            f"auto-night:{state.round}:mafia-faction"
            if action_type is NightActionType.ATTACK
            else f"auto-night:{state.round}:{actor.player_id}:{action_type.value}"
        ),
    )


def auto_vote_target(state: GameState, actor: PlayerState) -> PlayerState:
    """숨겨진 역할을 읽지 않고 해당 phase의 유효 후보 중 결정적으로 선택한다."""

    candidates = valid_targets(state, actor)
    if not candidates:
        raise ValueError("no valid vote target")

    return DeterministicRng(state.seed).choice(
        candidates,
        f"auto-vote:{state.round}:{state.phase.value}:{actor.player_id}",
    )
