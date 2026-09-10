"""밤 행동에 필요한 역할별 규칙을 제공한다."""

from __future__ import annotations

from backend.app.game_engine.errors import RuleViolation
from backend.app.models.enums import NightActionType, PlayerKind, PlayerRole
from backend.app.models.game_state import GameState, PlayerState

ABILITY_ACTIONS = {
    "night.attack.v1": NightActionType.ATTACK,
    "night.investigate.v1": NightActionType.INVESTIGATE,
    "night.protect.v1": NightActionType.PROTECT,
}


def role_action(state: GameState, actor_id) -> NightActionType:
    """플레이어 역할에 대응하는 밤 행동을 반환한다."""

    actor = state.player_by_id.get(actor_id)
    if actor is None:
        raise RuleViolation("PLAYER_NOT_FOUND")
    if actor.custom_ability_ids:
        # 저장 순서는 기본 밤 능력 선택에만 사용하고 낮·조회 능력은 건너뛴다.
        for ability_id in actor.custom_ability_ids:
            if ability_id in ABILITY_ACTIONS:
                return ABILITY_ACTIONS[ability_id]
        raise RuleViolation("ROLE_ACTION_NOT_ALLOWED")
    actions = {
        PlayerRole.MAFIA: NightActionType.ATTACK,
        PlayerRole.DETECTIVE: NightActionType.INVESTIGATE,
        PlayerRole.DOCTOR: NightActionType.PROTECT,
    }
    try:
        return actions[actor.role]
    except KeyError as exc:
        raise RuleViolation("ROLE_ACTION_NOT_ALLOWED") from exc


def ability_action(state: GameState, actor_id, ability_id: str | None) -> NightActionType:
    """CUSTOM_ROLE은 저장 snapshot의 능력만 내부 행동으로 변환한다."""

    actor = state.player_by_id.get(actor_id)
    if actor is None:
        raise RuleViolation("PLAYER_NOT_FOUND")
    if state.mode == "STANDARD" or actor.kind is not PlayerKind.HUMAN:
        if ability_id is not None:
            raise RuleViolation("ABILITY_ID_INVALID")
        return role_action(state, actor_id)
    if ability_id is None or ability_id not in actor.custom_ability_ids:
        raise RuleViolation("ABILITY_ID_INVALID")
    try:
        return ABILITY_ACTIONS[ability_id]
    except KeyError as exc:
        raise RuleViolation("ABILITY_ID_INVALID") from exc


def required_actors(state: GameState) -> list[PlayerState]:
    """마감 전 해소에 필요한 모든 생존 역할 행동자를 좌석순으로 반환한다.

    마피아 한 명의 응답만으로 창을 닫으면 다른 마피아의 첫 제출 기회가 사라진다.
    부분 응답과 전원 무응답의 차이는 마감 후 밤 해소에서 따로 처리한다.
    """

    return [
        player
        for player in state.alive_players
        if (
            any(ability_id in ABILITY_ACTIONS for ability_id in player.custom_ability_ids)
            if player.custom_ability_ids
            else player.role in {PlayerRole.MAFIA, PlayerRole.DETECTIVE, PlayerRole.DOCTOR}
        )
    ]
