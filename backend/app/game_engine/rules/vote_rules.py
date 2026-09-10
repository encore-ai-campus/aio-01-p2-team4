"""투표 결과를 계산하는 순수 규칙."""

from __future__ import annotations

from collections import Counter
from uuid import UUID

from backend.app.game_engine.errors import RuleViolation
from backend.app.models.enums import GamePhase, PlayerKind
from backend.app.models.game_state import GameState, PlayerState, Vote


def valid_targets(state: GameState, actor: PlayerState) -> list[PlayerState]:
    """공개된 생존·후보 정보만으로 수동 제출과 자동 선택의 같은 경계를 만든다.

    재투표 후보가 복원되지 않았다면 전체 생존자로 넓히지 않는다. 잘못 복원한
    상태에서 이전 투표의 동률 후보 밖을 선택하는 것을 막기 위해 빈 목록을 유지한다.
    """

    return [
        player
        for player in state.alive_players
        if player.player_id != actor.player_id
        and (state.phase is not GamePhase.REVOTE or player.player_id in state.revote_candidates)
    ]


def leaders(votes: dict[UUID, Vote]) -> list[UUID]:
    """제출한 표의 검증된 가중치를 합산해 가장 많은 표를 받은 대상을 반환한다."""

    counts = Counter()
    for vote in votes.values():
        counts[vote.target_id] += vote.weight
    highest = max(counts.values()) if counts else 0
    return [target_id for target_id, count in counts.items() if count == highest]


def vote_weight(state: GameState, actor_id: UUID, ability_id: str | None,
                *, phase: GamePhase | None = None) -> int:
    """능력 사용을 저장 snapshot과 대조하고 처형·재투표에만 3표를 허용한다.

    종료 원장도 같은 함수를 사용하므로 현재 생존 여부는 검사하지 않는다.
    실시간 제출과 복원 경계가 각각 당시 생존·대상·중복을 별도로 검증한다.
    """

    if ability_id is None:
        return 1
    actor = state.player_by_id.get(actor_id)
    if (ability_id != "vote.triple.v1"
            or (phase or state.phase) not in {GamePhase.DAY_VOTE, GamePhase.REVOTE}
            or state.mode != "CUSTOM_ROLE" or actor is None
            or actor.kind is not PlayerKind.HUMAN
            or actor.custom_role_catalog_version != "custom-role-v1"
            or ability_id not in actor.custom_ability_ids):
        raise RuleViolation("ABILITY_ID_INVALID")
    return 3
