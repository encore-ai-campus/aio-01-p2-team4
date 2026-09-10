"""PostgreSQL 게임 command가 공유하는 원장 복원·멱등성 helper."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from backend.app.core.errors import ApiError
from backend.app.models.enums import Faction, GamePhase, GameStatus, NightActionType, PlayerKind, PlayerRole, WinReason
from backend.app.models.game_state import GameState, NightAction, PlayerState, Vote


def find_replay(
    service: Any,
    cursor: Any,
    *,
    owner_user_id: UUID,
    idempotency_key: UUID,
    request_hash: str,
    route_scope: str,
) -> dict[str, Any] | None:
    """사용자·멱등 key·route가 모두 같은 이전 결과만 재사용한다."""

    previous = service._receipts.find(
        cursor,
        principal_type="USER",
        principal_id=owner_user_id,
        idempotency_key=idempotency_key,
    )
    if previous is None:
        return None
    if previous["request_hash"] != request_hash or previous["route_scope"] != route_scope:
        raise ApiError(
            status_code=409,
            code="IDEMPOTENCY_KEY_REUSED",
            message="같은 Idempotency-Key가 다른 요청에 사용되었습니다.",
        )
    result_body = previous["result_body"]
    if not isinstance(result_body, dict):
        raise RuntimeError("Stored command receipt is invalid")
    return copy.deepcopy(result_body)


def restore_locked_game(
    service: Any,
    cursor: Any,
    game_row: Mapping[str, Any],
) -> tuple[GameState, UUID]:
    """FOR UPDATE game row와 player row를 순수 엔진 상태로 복원한다."""

    game_id = UUID(str(game_row["id"]))
    seed = service._keyring.decrypt_seed(
        ciphertext=bytes(game_row["seed_ciphertext"]),
        nonce=bytes(game_row["seed_nonce"]),
        key_id=str(game_row["seed_key_id"]),
    )
    players: list[PlayerState] = []
    human_player_id: UUID | None = None
    player_rows = service._players.list_players(cursor, game_id=game_id)
    validate_custom_player_rows(game_row, player_rows)
    for row in player_rows:
        player_id = UUID(str(row["id"]))
        kind = PlayerKind(str(row["kind"]))
        custom_ids = row.get("custom_ability_ids")
        players.append(PlayerState(
            player_id=player_id, seat=int(row["seat"]), role=PlayerRole(str(row["role"])),
            kind=kind, display_name=str(row["display_name"]), alive=bool(row["alive"]),
            custom_role_name=row.get("custom_role_name"),
            custom_role_catalog_version=row.get("custom_role_catalog_version"),
            custom_ability_ids=tuple(custom_ids or ()),
            custom_faction=Faction(str(row["faction"])) if custom_ids else None,
        ))
        if kind is PlayerKind.HUMAN:
            if human_player_id is not None or row["user_id"] is None:
                raise RuntimeError("Persisted human player is invalid")
            human_player_id = player_id
    if human_player_id is None or len(players) != int(game_row["player_count"]):
        raise RuntimeError("Persisted players are incomplete")
    if not isinstance(game_row["updated_at"], datetime):
        raise RuntimeError("Persisted game timestamp is invalid")
    state = GameState(game_id=game_id, seed=seed, players=players, phase=GamePhase(str(game_row["phase"])), status=GameStatus(str(game_row["status"])), round=int(game_row["round"]), day_number=int(game_row["day_number"]), state_version=int(game_row["state_version"]), updated_at=game_row["updated_at"], winner=Faction(game_row["winner"]) if game_row.get("winner") else None, win_reason=WinReason(game_row["win_reason"]) if game_row.get("win_reason") else None, mode=str(game_row.get("mode") or "STANDARD"))
    state.fast_forward_enabled = game_row.get("fast_forward_enabled") is True
    # 구형 엔진은 지난 밤 수를 round로 저장했다. 새 계약과 구분되는 밤 상태만
    # 메모리에서 정규화하고 제출 window·마감·이미 확정된 원장은 건드리지 않는다.
    if state.phase is GamePhase.NIGHT_ACTION and 1 <= state.day_number <= 5 and state.round == state.day_number - 1:
        state.round = state.day_number
    if state.phase is GamePhase.REVOTE:
        restore_revote_candidates(state, service._actions.list_resolutions(cursor, game_id=game_id, through_state_version=state.state_version))
    return state, human_player_id


def restore_revote_candidates(state: GameState, resolutions: list[Mapping[str, Any]]) -> None:
    """같은 round의 직전 확정 DAY_VOTE 집계로 재투표 후보만 복원한다."""

    if state.phase is not GamePhase.REVOTE:
        return
    from backend.app.services.game.result_service import resolution_payload

    for row in reversed(resolutions):
        payload = resolution_payload(state, row)
        if payload["phase"] == "DAY_VOTE" and payload["round"] == state.round and payload["needs_revote"]:
            state.revote_candidates = {UUID(value) for value in payload["tied_candidates"]}
            return
    raise RuntimeError("재투표의 확정 후보 원장이 없습니다.")


def restore_action_submissions(state: GameState, submissions: list[Mapping[str, Any]]) -> None:
    """현재 window의 첫 유효 제출을 버전 증가나 자동 해소 없이 복원한다.

    DB 행도 외부 데이터로 취급한다. actor·역할·생존·대상·중복을 확인하며 이전
    선택을 새로운 command처럼 제출해 최종 지목이 조기 종료되는 일을 막는다.
    """

    from backend.app.game_engine.rules.night_rules import ability_action
    from backend.app.game_engine.errors import RuleViolation
    from backend.app.game_engine.rules.vote_rules import valid_targets, vote_weight

    state.night_actions.clear()
    state.votes.clear()
    seen = set()
    for row in submissions:
        actor_id = UUID(str(row["actor_player_id"]))
        target_id = UUID(str(row["target_player_id"]))
        actor = state.player_by_id[actor_id]
        target = state.player_by_id[target_id]
        if actor_id in seen or not actor.alive or not target.alive:
            raise ValueError("저장된 행동의 actor 또는 대상이 올바르지 않습니다.")
        seen.add(actor_id)
        if state.phase is GamePhase.NIGHT_ACTION:
            action = NightActionType(row["action_type"])
            try:
                expected = ability_action(state, actor_id, row.get("ability_id"))
            except RuleViolation as exc:
                raise ValueError("저장된 능력 ID가 actor와 다릅니다.") from exc
            if action is not expected or (actor_id == target_id and action is not NightActionType.PROTECT):
                raise ValueError("저장된 밤 행동이 역할 규칙과 다릅니다.")
            state.night_actions[actor_id] = NightAction(actor_id, action, target_id)
        elif state.phase in {GamePhase.DAY_VOTE, GamePhase.REVOTE, GamePhase.FINAL_ACCUSATION}:
            ability_id = row.get("ability_id")
            try:
                vote_weight(state, actor_id, ability_id)
            except RuleViolation as exc:
                raise ValueError("저장된 투표 능력이 actor 또는 단계와 다릅니다.") from exc
            if (row["action_type"] != "VOTE" or target not in valid_targets(state, actor)
                    or ability_id is not None and row.get("source") != "HUMAN"):
                raise ValueError("저장된 투표 대상이 유효 후보가 아닙니다.")
            state.votes[actor_id] = Vote(actor_id, target_id, ability_id)
        else:
            raise ValueError("현재 단계에는 행동 제출을 복원할 수 없습니다.")


def validate_custom_player_rows(game: Mapping[str, Any], rows: list[Mapping[str, Any]]) -> None:
    """두 DB 복원 경계에서 부분 snapshot과 지원하지 않는 AI 능력을 거부한다.

    NULL과 빈 배열을 구분하고 생성 catalog 검증을 재사용하여 저장 오염을
    표준 역할로 조용히 강등하지 않는다.
    """

    from pydantic import ValidationError
    from backend.app.schemas.game_schema import CustomRoleRequest

    mode = game.get("mode", "STANDARD")
    if mode not in {"STANDARD", "CUSTOM_ROLE"}:
        raise ValueError("저장된 게임 mode가 올바르지 않습니다.")
    custom_count = 0
    for row in rows:
        values = [row.get(key) for key in (
            "custom_role_name", "custom_role_catalog_version", "custom_ability_ids"
        )]
        expected = mode == "CUSTOM_ROLE" and row["kind"] == "HUMAN"
        if not expected:
            if any(value is not None for value in values):
                raise ValueError("표준 actor의 custom snapshot은 NULL이어야 합니다.")
            continue
        if any(value is None for value in values) or not isinstance(values[2], list):
            raise ValueError("저장된 custom snapshot이 불완전합니다.")
        try:
            snapshot = CustomRoleRequest(name=values[0], catalog_version=values[1],
                                         ability_ids=values[2], faction=row["faction"])
        except ValidationError as exc:
            raise ValueError("저장된 custom snapshot이 catalog와 다릅니다.") from exc
        if snapshot.name != values[0]:
            raise ValueError("저장된 custom 직업명이 정규화되지 않았습니다.")
        custom_count += 1
    if mode == "CUSTOM_ROLE" and custom_count != 1:
        raise ValueError("CUSTOM_ROLE에는 정확히 한 인간 snapshot이 필요합니다.")
