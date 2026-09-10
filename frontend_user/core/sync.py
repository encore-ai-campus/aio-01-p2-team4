"""SSE·polling 공통 sync envelope 검증과 원자적 operation 적용."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

ALLOWED_OPERATION_TYPES = {
    "SET_GAME_STATE", "REPLACE_PLAYERS", "SET_PRIVATE_STATE", "SET_ACTION_WINDOW",
    "CLEAR_ACTION_WINDOW", "APPEND_PUBLIC_EVENT", "APPEND_PRIVATE_EVENT", "SET_RESULT",
}


@dataclass(frozen=True, slots=True)
class SyncPolicy:
    """정본에 정의된 polling·실패 전환 timing을 한 곳에서 관리한다."""

    foreground_poll_ms: int = 2_000
    background_poll_ms: int = 10_000
    stale_after_failures: int = 5
    sse_retry_ms: int = 1_000
    max_backoff_ms: int = 30_000
    request_timeout_ms: int = 5_000
    jitter_ratio: float = 0.2


class SyncEnvelopeError(ValueError):
    """부분 적용 없이 snapshot 복구가 필요한 sync 계약 오류."""


def apply_envelope(*, snapshot: dict[str, Any], envelope: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """DELTA를 검증한 뒤 전부 적용하고, SNAPSHOT은 authoritative snapshot으로 교체한다."""

    # 팀 전달 사항: Backend의 /sync와 /events는 동일한 game_id·front_sequence·
    # operation_index를 사용해야 한다. sequence/index gap이나 unknown operation이
    # 있으면 부분 batch가 아니라 mode=SNAPSHOT으로 복구할 수 있는 응답을 제공한다.

    if not isinstance(envelope, dict):
        raise SyncEnvelopeError("SYNC_INVALID")
    data = envelope.get("data", envelope)
    if not isinstance(data, dict) or not isinstance(data.get("mode"), str) or data["mode"] not in {"DELTA", "SNAPSHOT"}:
        raise SyncEnvelopeError("SYNC_INVALID")
    current_game = snapshot.get("game")
    if not isinstance(current_game, dict) or data.get("game_id") != current_game.get("game_id"):
        raise SyncEnvelopeError("SYNC_GAME_MISMATCH")
    current_sequence = _integer(current_game.get("last_sequence"), minimum=0)
    current_version = _integer(current_game.get("state_version"), minimum=1)
    if data["mode"] == "SNAPSHOT":
        replacement = data.get("snapshot")
        if not isinstance(replacement, dict) or not isinstance(replacement.get("game"), dict):
            raise SyncEnvelopeError("SYNC_SNAPSHOT_INVALID")
        game = replacement["game"]
        if game.get("game_id") != current_game["game_id"] or data.get("operations", []) != []:
            raise SyncEnvelopeError("SYNC_SNAPSHOT_INVALID")
        for name, minimum in (("state_version", 1), ("last_sequence", 0)):
            value = _integer(game.get(name), minimum=minimum)
            if name in data and _integer(data[name], minimum=minimum) != value:
                raise SyncEnvelopeError("SYNC_SNAPSHOT_INVALID")
            if value < current_game[name]:
                raise SyncEnvelopeError("SYNC_SNAPSHOT_REVERSED")
        return deepcopy(replacement), "SNAPSHOT"
    raw_operations = data.get("operations")
    if not isinstance(raw_operations, list):
        raise SyncEnvelopeError("SYNC_OPERATIONS_INVALID")
    state_version = _integer(data.get("state_version"), minimum=1)
    last_sequence = _integer(data.get("last_sequence"), minimum=0)
    from_version = _integer(data.get("from_state_version"), minimum=0)
    if from_version > current_version or from_version > state_version:
        raise SyncEnvelopeError("SYNC_VERSION_GAP")
    operations = _flatten_operations(raw_operations)
    expected_sequence, expected_version, expected_index = current_sequence, current_version, -1
    candidate = deepcopy(snapshot)
    seen: dict[tuple[int, int], dict[str, Any]] = {}
    for operation in operations:
        if not isinstance(operation.get("type"), str) or operation["type"] not in ALLOWED_OPERATION_TYPES:
            raise SyncEnvelopeError("SYNC_UNKNOWN_OPERATION")
        if type(operation.get("schema_version")) is not int or operation["schema_version"] != 1:
            raise SyncEnvelopeError("SYNC_SCHEMA_UNSUPPORTED")
        sequence = _integer(operation.get("front_sequence"), minimum=1)
        index = _integer(operation.get("operation_index"), minimum=0)
        version = _integer(operation.get("state_version"), minimum=1)
        if not isinstance(operation.get("payload"), dict):
            raise SyncEnvelopeError("SYNC_PAYLOAD_INVALID")
        if sequence > last_sequence or version > state_version:
            raise SyncEnvelopeError("SYNC_CURSOR_MISMATCH")
        # snapshot의 마지막 sequence는 이미 전체 batch를 반영한 위치다. index 0도
        # 다시 적용하지 않으며, 같은 응답에 뒤따르는 새로운 sequence만 검증한다.
        if sequence <= current_sequence:
            if version > current_version:
                raise SyncEnvelopeError("SYNC_CURSOR_MISMATCH")
            continue
        identity = (sequence, index)
        if identity in seen:
            if seen[identity] != operation:
                raise SyncEnvelopeError("SYNC_DUPLICATE_CONFLICT")
            continue
        if sequence == expected_sequence + 1:
            if index != 0 or version <= expected_version:
                raise SyncEnvelopeError("SYNC_BATCH_INDEX_OR_VERSION_GAP")
            expected_index = -1
        elif sequence != expected_sequence:
            raise SyncEnvelopeError("SYNC_SEQUENCE_GAP")
        elif version != expected_version:
            raise SyncEnvelopeError("SYNC_BATCH_VERSION_MISMATCH")
        if index != expected_index + 1:
            raise SyncEnvelopeError("SYNC_BATCH_INDEX_GAP")
        seen[identity] = operation
        expected_sequence, expected_version, expected_index = sequence, version, index
        try:
            _apply_operation(candidate, operation)
        except (TypeError, ValueError, AttributeError, KeyError) as error:
            # 잘못된 컨테이너가 기존 projection과 합쳐지지 않게 고정 오류만 전달한다.
            # payload나 원문 예외는 UI에 노출하지 않고 caller의 GET 복구를 사용한다.
            raise SyncEnvelopeError("SYNC_PAYLOAD_INVALID") from error
    if not seen and operations and last_sequence <= current_sequence and state_version <= current_version:
        return deepcopy(snapshot), "DELTA"
    # 비어 있는 delta로 cursor를 전진시키거나 마지막 batch 뒤를 추정하지 않는다.
    # 이 검사가 실패하면 caller가 원본 snapshot을 유지한 채 authoritative GET을 한다.
    if (last_sequence, state_version) != (expected_sequence, expected_version):
        raise SyncEnvelopeError("SYNC_CURSOR_MISMATCH")
    candidate["game"]["last_sequence"] = last_sequence
    candidate["game"]["state_version"] = state_version
    return candidate, "DELTA"


def _integer(value: Any, *, minimum: int) -> int:
    """bool과 숫자 문자열을 cursor로 허용하지 않아 잘못된 위치의 묵시적 적용을 막는다."""

    if type(value) is not int or value < minimum:
        raise SyncEnvelopeError("SYNC_CURSOR_INVALID")
    return value


def _flatten_operations(raw_operations: list[Any]) -> list[dict[str, Any]]:
    """평탄한 정본과 sequence별 batch를 지원하되 누락 index·schema를 만들어 넣지 않는다.

    중첩 형식은 batch가 명시한 schema와 state version만 상속한다. 내부 operation이
    다른 sequence나 version을 주장하면 부분 적용 대신 snapshot 복구로 전환한다.
    """

    flattened: list[dict[str, Any]] = []
    for item in raw_operations:
        if not isinstance(item, dict):
            raise SyncEnvelopeError("SYNC_OPERATION_INVALID")
        if "operations" not in item:
            flattened.append(item)
            continue
        sequence = _integer(item.get("front_sequence"), minimum=1)
        version = _integer(item.get("state_version"), minimum=1)
        if "schema_version" in item and (type(item["schema_version"]) is not int or item["schema_version"] != 1):
            raise SyncEnvelopeError("SYNC_SCHEMA_UNSUPPORTED")
        nested = item["operations"]
        if not isinstance(nested, list) or not nested:
            raise SyncEnvelopeError("SYNC_OPERATION_BATCH_INVALID")
        for operation in nested:
            if not isinstance(operation, dict):
                raise SyncEnvelopeError("SYNC_OPERATION_INVALID")
            for name, expected in (("front_sequence", sequence), ("state_version", version)):
                if name in operation and _integer(operation[name], minimum=1) != expected:
                    raise SyncEnvelopeError("SYNC_OPERATION_BATCH_INVALID")
            flattened.append({
                "schema_version": item.get("schema_version"),
                **operation, "front_sequence": sequence, "state_version": version,
            })
    return flattened


def _apply_operation(snapshot: dict[str, Any], operation: dict[str, Any]) -> None:
    """허용된 operation만 projection의 해당 영역에 적용한다."""

    # 팀 전달 사항: 아래 operation type과 payload는 API 정본의 폐쇄형 union이다.
    # 다른 AI의 private event, capability, prompt, 개별 투표는 Front operation으로
    # 전달하지 않는다.

    payload = operation.get("payload")
    if not isinstance(payload, dict):
        raise SyncEnvelopeError("SYNC_PAYLOAD_INVALID")
    operation_type = operation["type"]
    if operation_type == "SET_GAME_STATE":
        snapshot["game"].update({key: payload[key] for key in ("status", "phase", "round", "day_number", "state_version", "fast_forward_enabled") if key in payload})
    elif operation_type == "REPLACE_PLAYERS":
        snapshot["players"] = deepcopy(payload.get("players", []))
    elif operation_type == "SET_PRIVATE_STATE":
        snapshot["me"] = deepcopy(payload.get("me", {}))
    elif operation_type == "SET_ACTION_WINDOW":
        snapshot["action_window"] = deepcopy(payload)
    elif operation_type == "CLEAR_ACTION_WINDOW":
        snapshot["action_window"] = None
    elif operation_type == "APPEND_PUBLIC_EVENT":
        snapshot.setdefault("public_events", []).append(deepcopy(payload))
    elif operation_type == "APPEND_PRIVATE_EVENT":
        snapshot.setdefault("me", {}).setdefault("private_events", []).append(deepcopy(payload))
    elif operation_type == "SET_RESULT":
        snapshot["result"] = deepcopy(payload)
