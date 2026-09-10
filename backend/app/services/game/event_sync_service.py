"""저장된 event를 검증하고 완전한 Front batch만 내보내는 읽기 경계."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg import IsolationLevel
from psycopg.rows import dict_row

from backend.app.core.errors import ApiError
from backend.app.models.enums import GamePhase, GameStatus
from backend.app.services.game.actor_context import private_event_data


def build_operation_batches(
    rows: Sequence[Mapping[str, Any]], *, record: Any = None,
    after_sequence: int = 0, after_state_version: int = 0,
) -> list[dict[str, Any]]:
    """수신자·schema·cursor를 검증하고 잘린 batch나 불명확한 payload는 통째로 거부한다.

    원장의 index를 재배정하거나 위험한 event만 빼면 클라이언트 cursor가 실제 상태와
    달라진다. 하나라도 복원할 수 없으면 호출자가 authoritative snapshot으로 재조회한다.
    """

    if record is None:
        raise ValueError("검증할 게임 원본이 필요합니다.")
    batches: dict[int, dict[str, Any]] = {}
    seen_ids = set()
    previous_sequence = 0
    for row in rows:
        if (UUID(str(row["game_id"])) != record.state.game_id
            or type(row["schema_version"]) is not int or row["schema_version"] != 1):
            raise ValueError("동기화 event의 게임 또는 schema가 올바르지 않습니다.")
        identifier = UUID(str(row["id"]))
        sequence = _integer(row["sequence"], 1)
        if identifier in seen_ids or sequence <= previous_sequence:
            raise ValueError("동기화 event가 중복되거나 순서가 다릅니다.")
        seen_ids.add(identifier)
        previous_sequence = sequence
        front_sequence = _integer(row["front_sequence"], after_sequence + 1, record.front_sequence)
        version = _integer(row["state_version"], max(after_state_version, 1), record.state.state_version)
        index = _integer(row["operation_index"], 0, 32767)
        batch = batches.setdefault(front_sequence, {
            "front_sequence": front_sequence, "state_version": version, "operations": [],
        })
        if batch["state_version"] != version or index != len(batch["operations"]):
            raise ValueError("동기화 batch가 완전하지 않습니다.")
        operation = row["operation_type"]
        payload = row["payload"]
        if not isinstance(payload, Mapping):
            raise ValueError("동기화 payload가 올바르지 않습니다.")
        batch["operations"].append({
            "schema_version": row["schema_version"],
            "operation_index": index, "type": operation,
            "payload": _operation_payload(row, operation, payload, record),
        })
    expected_sequence = after_sequence + 1
    previous_version = after_state_version
    for sequence, batch in batches.items():
        if sequence != expected_sequence or batch["state_version"] <= previous_version:
            raise ValueError("동기화 cursor에 누락이 있습니다.")
        expected_sequence += 1
        previous_version = batch["state_version"]
    return list(batches.values())


def _operation_payload(row: Mapping, operation: str, payload: Mapping, record: Any) -> dict:
    """공개 필드 allowlist와 인간 본인 private audience를 함께 검사한다."""

    from backend.app.services.game.game_read_service import _public_event_data

    if operation == "APPEND_PRIVATE_EVENT":
        if row["audience"] != "PLAYER" or UUID(str(row["audience_player_id"])) != record.human_player_id:
            raise ValueError("다른 플레이어의 개인 event는 동기화할 수 없습니다.")
        data = private_event_data(record.state, row["event_type"], payload, player_id=record.human_player_id)
        if data != payload:
            raise ValueError("개인 event에 미승인 필드가 있습니다.")
        return _event_wrapper(row, data)
    if row["audience"] != "PUBLIC" or row["audience_player_id"] is not None:
        raise ValueError("공개 operation의 audience가 올바르지 않습니다.")
    if operation == "APPEND_PUBLIC_EVENT":
        if row["event_type"] in {"NIGHT_RESOLVED", "VOTE_RESOLVED", "PLAYER_EXECUTED", "GAME_ENDED"}:
            # 현재 writer의 해소 batch에는 생존자 교체와 최종 결과 operation이 없다.
            # 공개 문장만 적용한 채 cursor를 전진시키지 않고 최신 snapshot을 복원한다.
            raise ValueError("해소 결과는 완전한 snapshot이 필요합니다.")
        data = _public_event_data(row["event_type"], payload, record)
        if data != payload:
            raise ValueError("공개 event에 미승인 필드가 있습니다.")
        return _event_wrapper(row, data)
    if operation == "SET_GAME_STATE":
        _fields(payload, {"status", "phase", "round", "day_number", "state_version", "fast_forward_enabled"})
        GameStatus(payload["status"])
        GamePhase(payload["phase"])
        _integer(payload["round"], 0, 5)
        _integer(payload["day_number"], 1, 6)
        if _integer(payload["state_version"], 1) != row["state_version"] or type(payload["fast_forward_enabled"]) is not bool:
            raise ValueError("공개 상태 변경이 원장과 일치하지 않습니다.")
        return dict(payload)
    if operation == "CLEAR_ACTION_WINDOW":
        _fields(payload, {"window_id"})
        if payload["window_id"] is not None:
            raise ValueError("닫힌 window에 ID가 남아 있습니다.")
        return {"window_id": None}
    if operation == "SET_ACTION_WINDOW":
        return _window_payload(payload, row, record)
    # 과거 REPLACE_PLAYERS·SET_PRIVATE_STATE·SET_RESULT 원문을 그대로 통과시키지
    # 않는다. 현재 snapshot presenter에서 같은 게임과 인간 소유권으로 재조립한다.
    raise ValueError("검증할 수 없는 동기화 operation입니다.")


def _event_wrapper(row: Mapping, data: dict) -> dict:
    """확정된 event 메타데이터만 사용해 공개·개인 공통 wrapper를 만든다."""

    created = row["created_at"]
    if not isinstance(created, datetime) or created.utcoffset() is None:
        raise ValueError("event 시각이 올바르지 않습니다.")
    return {"event_id": str(UUID(str(row["id"]))), "event_type": row["event_type"],
            "created_at": created.astimezone(UTC).isoformat().replace("+00:00", "Z"), "data": data}


def _window_payload(payload: Mapping, row: Mapping, record: Any) -> dict:
    """행동 window의 폐쇄형 공개 필드를 검사하고 미승인 후보 정보를 차단한다."""

    _fields(payload, {"window_id", "kind", "cycle", "paused", "opened_state_version", "server_time",
                      "deadline_at", "remaining_ms", "turn_player_id", "has_submitted", "legal_actions", "valid_targets"})
    UUID(payload["window_id"])
    if payload["kind"] not in {"SPEECH", "NIGHT", "VOTE", "REVOTE", "FINAL_VOTE"}:
        raise ValueError("window 종류가 올바르지 않습니다.")
    _integer(payload["cycle"], 1, 2)
    _integer(payload["opened_state_version"], 1, row["state_version"])
    for name in ("paused", "has_submitted"):
        if type(payload[name]) is not bool:
            raise ValueError("window 상태가 올바르지 않습니다.")
    for name in ("server_time", "deadline_at"):
        if payload[name] is None and name == "deadline_at":
            continue
        parsed = datetime.fromisoformat(payload[name].replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError("window 시각에 시간대가 없습니다.")
    if payload["remaining_ms"] is not None:
        _integer(payload["remaining_ms"], 0)
    if payload["turn_player_id"] is not None and UUID(payload["turn_player_id"]) not in record.state.player_by_id:
        raise ValueError("다른 게임의 발언자입니다.")
    actions = payload["legal_actions"]
    if not isinstance(actions, list) or any(action not in {"SPEAK", "PASS", "SUBMIT_NIGHT_ACTION", "SUBMIT_VOTE", "SAVE_AND_EXIT", "FAST_FORWARD", "RESUME", "BEGIN_GAME"} for action in actions):
        raise ValueError("window의 공개 행동 목록이 올바르지 않습니다.")
    if not actions:
        raise ValueError("저장된 window hint는 인간용 완전한 snapshot이 필요합니다.")
    targets = payload["valid_targets"]
    if not isinstance(targets, list) or len(targets) > 8 or (payload["kind"] == "SPEECH" and targets):
        raise ValueError("window의 후보 목록이 올바르지 않습니다.")
    seats = []
    for target in targets:
        _fields(target, {"player_id", "display_name"})
        player = record.state.player_by_id[UUID(target["player_id"])]
        if not player.alive or target["display_name"] != player.display_name:
            raise ValueError("현재 공개 참가자와 다른 후보입니다.")
        seats.append(player.seat)
    if seats != sorted(set(seats)):
        raise ValueError("window 후보가 중복되거나 순서가 다릅니다.")
    # 인물의 숨은 role로 달라지는 NIGHT 후보와 legal_actions는 인간 전용 조회에서
    # 다시 계산한다. 저장된 공개 window가 이 값을 갖고 있다면 snapshot을 사용한다.
    if payload["kind"] == "NIGHT" and (targets or actions):
        raise ValueError("개인 역할별 window는 snapshot에서 조회해야 합니다.")
    return {**payload, "valid_targets": [dict(target) for target in targets], "legal_actions": list(actions)}


def _fields(value: Mapping, names: set[str]) -> None:
    """중첩 object도 정본에 없는 필드를 통과시키지 않는다."""

    if not isinstance(value, Mapping) or set(value) != names:
        raise ValueError("동기화 object에 허용되지 않은 필드가 있습니다.")


def _integer(value: Any, minimum: int, maximum: int | None = None) -> int:
    """bool·문자열을 숫자로 암묵 변환하지 않고 cursor와 버전 범위를 검사한다."""

    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValueError("동기화 정수 범위가 올바르지 않습니다.")
    return value


def read_sync(reader: Any, owner_user_id: Any, game_id: Any, *, after_state_version: int, after_sequence: int) -> dict[str, Any]:
    """같은 읽기 snapshot에서 batch를 검증하고 안전한 delta 또는 최신 snapshot을 반환한다."""

    from backend.app.services.game.game_read_service import initial_record_from_rows

    if after_state_version < 0 or after_sequence < 0:
        raise ApiError(status_code=422, code="INVALID_REQUEST", message="sync cursor가 올바르지 않습니다.")
    try:
        with reader._transactions.transaction() as connection:
            connection.isolation_level = IsolationLevel.REPEATABLE_READ
            connection.read_only = True
            with connection.cursor(row_factory=dict_row) as cursor:
                game = reader._games.get_owned_game(cursor, owner_user_id=owner_user_id, game_id=game_id)
                if game is None or UUID(str(game["id"])) != game_id or UUID(str(game["owner_user_id"])) != owner_user_id:
                    raise ApiError(status_code=404, code="GAME_NOT_FOUND", message="게임을 찾을 수 없습니다.")
                current_version = int(game["state_version"])
                current_sequence = max(int(game["next_front_sequence"]) - 1, 0)
                needs_snapshot = (after_state_version > current_version or after_sequence > current_sequence
                                  or (after_sequence == current_sequence and after_state_version != current_version))
                operations = []
                if not needs_snapshot and after_sequence != current_sequence:
                    players = reader._players.list_players(cursor, game_id=game_id)
                    record = initial_record_from_rows(keyring=reader._keyring, game=game, player_rows=players)
                    rows = reader._events.list_front_events(cursor, game_id=game_id, after_front_sequence=after_sequence,
                                                           human_player_id=record.human_player_id, limit=500)
                    try:
                        operations = build_operation_batches(rows, record=record, after_sequence=after_sequence,
                                                             after_state_version=after_state_version)
                        # LIMIT에 걸린 마지막 batch는 index가 연속이어도 끝부분이 빠질 수
                        # 있다. 이후 batch를 재번호화하지 않고 snapshot으로 안전하게 복원한다.
                        needs_snapshot = (len(rows) >= 500 or not operations
                                          or operations[-1]["front_sequence"] != current_sequence
                                          or operations[-1]["state_version"] != current_version)
                    except (KeyError, ValueError, TypeError, AttributeError):
                        needs_snapshot = True
        if needs_snapshot:
            snapshot = reader.snapshot(owner_user_id, game_id)
            return {"game_id": str(game_id), "mode": "SNAPSHOT", "from_state_version": after_state_version,
                    "state_version": snapshot["game"]["state_version"], "last_sequence": snapshot["game"]["last_sequence"],
                    "operations": [], "snapshot": snapshot}
        return {"game_id": str(game_id), "mode": "DELTA", "from_state_version": after_state_version,
                "state_version": operations[-1]["state_version"] if operations else after_state_version,
                "last_sequence": operations[-1]["front_sequence"] if operations else after_sequence,
                "operations": operations, "snapshot": None}
    except ApiError:
        raise
    except Exception as error:
        raise ApiError(status_code=503, code="DEPENDENCY_UNAVAILABLE", message="게임 동기화를 사용할 수 없습니다.", retryable=True) from error
