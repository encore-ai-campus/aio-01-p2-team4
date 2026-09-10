"""확정 해소 원장에서 종료 결과를 복원하며 진행 중 개인 선택을 숨긴다."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from backend.app.game_engine.errors import RuleViolation
from backend.app.game_engine.rules.vote_rules import vote_weight
from backend.app.models.enums import GamePhase, GameStatus
from backend.app.models.game_state import GameState


def resolution_payload(state: GameState, row: Mapping[str, Any]) -> dict[str, Any]:
    """승인된 원장 v1을 명시적 필드로 복사하고 게임·버전·참가자 경계를 검사한다."""

    if UUID(str(row["game_id"])) != state.game_id:
        raise ValueError("다른 게임의 해소 원장입니다.")
    version = row["resolved_state_version"]
    payload = row["result_payload"]
    if type(version) is not int or not 1 <= version <= state.state_version or not isinstance(payload, Mapping):
        raise ValueError("해소 원장 버전이 올바르지 않습니다.")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ValueError("지원하지 않는 해소 원장입니다.")
    round_number = payload["round"]
    if type(round_number) is not int or not 1 <= round_number <= 5:
        raise ValueError("해소 round가 올바르지 않습니다.")
    phase = GamePhase(payload["phase"])
    kinds = {GamePhase.NIGHT_ACTION: "NIGHT", GamePhase.DAY_VOTE: "VOTE", GamePhase.REVOTE: "REVOTE", GamePhase.FINAL_ACCUSATION: "FINAL_VOTE"}
    if kinds.get(phase) != row["resolution_type"]:
        raise ValueError("해소 단계와 원장 종류가 다릅니다.")

    def identifier(value: Any, *, nullable: bool = False) -> str | None:
        """null 허용 필드 외에는 같은 게임 참가자의 UUID만 반환한다."""

        if value is None and nullable:
            return None
        parsed = UUID(str(value))
        if parsed not in state.player_by_id:
            raise ValueError("해소 원장 참가자가 올바르지 않습니다.")
        return str(parsed)

    def choices(value: Any, *, investigation: bool = False, ballots: bool = False) -> list[dict[str, Any]]:
        """개별 기록의 actor 중복과 boolean 암묵 변환을 차단한다."""

        if not isinstance(value, list):
            raise ValueError("해소 행동 목록 형식이 올바르지 않습니다.")
        result = []
        seen = set()
        for item in value:
            actor = identifier(item["actor_player_id"])
            if actor in seen or type(item["is_auto"]) is not bool:
                raise ValueError("해소 행동 중복 또는 자동 선택 형식이 올바르지 않습니다.")
            seen.add(actor)
            entry = {"actor_player_id": actor, "target_player_id": identifier(item["target_player_id"]), "is_auto": item["is_auto"]}
            if ballots:
                # 저장된 숫자를 신뢰하지 않고 당시 phase와 불변 actor 능력으로
                # 가중치를 재계산한다. 구형 ballot에는 ability_id가 없어도 된다.
                if set(item) - {"actor_player_id", "target_player_id", "is_auto", "ability_id"}:
                    raise ValueError("개별 표에 허용되지 않은 필드가 있습니다.")
                ability_id = item.get("ability_id")
                try:
                    vote_weight(state, UUID(actor), ability_id, phase=phase)
                except RuleViolation as exc:
                    raise ValueError("확정 표의 능력이 actor 또는 단계와 다릅니다.") from exc
                if ability_id is not None:
                    if item["is_auto"]:
                        raise ValueError("자동 표에는 능력을 적용할 수 없습니다.")
                    entry["ability_id"] = ability_id
            if investigation:
                if type(item["is_mafia"]) is not bool:
                    raise ValueError("조사 결과 형식이 올바르지 않습니다.")
                entry["is_mafia"] = item["is_mafia"]
            result.append(entry)
        return result

    result = {"schema_version": 1, "round": round_number, "phase": phase.value}
    if phase is GamePhase.NIGHT_ACTION:
        raw_protected = payload.get("protect_player_ids")
        protected = (
            [identifier(value) for value in raw_protected]
            if isinstance(raw_protected, list)
            else ([identifier(payload["protect_player_id"])] if payload["protect_player_id"] else [])
        )
        if len(set(protected)) != len(protected):
            raise ValueError("보호 대상 집합에 중복이 있습니다.")
        result.update({
            "attack_choices": choices(payload["attack_choices"]),
            "resolved_attack_target_player_id": identifier(payload["resolved_attack_target_player_id"], nullable=True),
            "protect_player_id": identifier(payload["protect_player_id"], nullable=True),
            "protect_player_ids": protected,
            "investigations": choices(payload["investigations"], investigation=True),
            "killed_player_id": identifier(payload["killed_player_id"], nullable=True),
        })
    else:
        # 공개 집계도 같은 검증 함수를 거쳐 필드·좌석순·동률 상태를 일치시킨다.
        from backend.app.services.game.game_read_service import _public_event_data
        from backend.app.services.game.models import CanonicalGameRecord

        human_id = next(player.player_id for player in state.players if player.kind.value == "HUMAN")
        record = CanonicalGameRecord(state, {}, human_id, UUID(int=0), "", "")
        public = _public_event_data("VOTE_RESOLVED", payload, record)
        ballots = choices(payload["ballots"], ballots=True)
        counts = public["counts"]
        weighted = [(ballot, vote_weight(state, UUID(ballot["actor_player_id"]),
                                        ballot.get("ability_id"), phase=phase)) for ballot in ballots]
        for item in counts:
            if item["vote_count"] != sum(weight for ballot, weight in weighted
                                          if ballot["target_player_id"] == item["target_player_id"]):
                raise ValueError("개별 표와 확정 득표수가 다릅니다.")
        if sum(weight for _, weight in weighted) != sum(item["vote_count"] for item in counts):
            raise ValueError("확정 표 합계가 다릅니다.")
        tied_candidates = payload["tied_candidates"]
        maximum = max(item["vote_count"] for item in counts)
        leaders = {item["target_player_id"] for item in counts if item["vote_count"] == maximum}
        if not isinstance(tied_candidates, list) or len(set(tied_candidates)) != len(tied_candidates) or set(tied_candidates) != (leaders if public["tied"] else set()):
            raise ValueError("확정 동률 후보가 집계와 다릅니다.")
        result.update(public)
        result.update({"ballots": ballots, "eliminated_player_id": identifier(payload["eliminated_player_id"], nullable=True), "tied_candidates": [identifier(value) for value in tied_candidates], "final_target_player_id": identifier(payload["final_target_player_id"], nullable=True)})
    return result


def build_result(state: GameState, *, resolutions: list[Mapping[str, Any]] | None = None,
                 eliminated: Mapping[UUID, tuple[str, int]] | None = None,
                 public_events: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """종료 게임에만 확정된 밤·표를 공개하고 없는 과거 이력은 추정하지 않는다."""

    if state.status is not GameStatus.COMPLETED:
        return None
    eliminated = eliminated or {}
    nights = []
    votes = []
    for row in resolutions or []:
        payload = resolution_payload(state, row)
        if payload["phase"] == "NIGHT_ACTION":
            nights.append({key: value for key, value in payload.items() if key not in {"schema_version", "phase"}})
        else:
            votes.append({key: payload[key] for key in ("round", "phase", "ballots", "counts", "eliminated_player_id")})
    return {
        "winner": state.winner.value if state.winner else None,
        "win_reason": state.win_reason.value if state.win_reason else None,
        "finished_at": state.updated_at.isoformat(),
        "players": [
            {"player_id": str(player.player_id), "display_name": player.display_name,
             "role": player.role.value, "alive": player.alive,
             "role_name": player.custom_role_name,
             "faction": player.faction.value,
             "eliminated_phase": eliminated[player.player_id][0] if player.player_id in eliminated else None,
             "eliminated_round": eliminated[player.player_id][1] if player.player_id in eliminated else None}
            for player in sorted(state.players, key=lambda item: item.seat)
        ],
        "nights": nights,
        "votes": votes,
        "public_event_ids": [event["event_id"] for event in public_events or []],
    }
