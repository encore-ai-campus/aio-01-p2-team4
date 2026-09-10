"""Front operation batch와 SSE 재연결에 공통으로 사용하는 순수 유틸리티."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any


def _value(row: Mapping[str, Any] | Any, key: str, index: int) -> Any:
    """dict row와 기본 tuple row를 모두 안전하게 읽는다."""

    if isinstance(row, Mapping):
        return row[key]
    return row[index]


def build_complete_operation_batches(
    rows: Iterable[Mapping[str, Any] | Any],
) -> list[dict[str, Any]]:
    """같은 Front sequence의 0부터 연속된 operation만 batch로 묶는다.

    중간 index가 빠진 batch는 일부 적용하면 화면 상태가 깨질 수 있으므로
    결과에서 제외한다. 호출자는 이 경우 snapshot fallback을 선택해야 한다.
    """

    grouped: dict[int, list[Mapping[str, Any] | Any]] = defaultdict(list)
    for row in rows:
        front_sequence = _value(row, "front_sequence", 3)
        operation_index = _value(row, "operation_index", 4)
        if front_sequence is None or operation_index is None:
            continue
        grouped[int(front_sequence)].append(row)

    batches: list[dict[str, Any]] = []
    for front_sequence in sorted(grouped):
        ordered = sorted(grouped[front_sequence], key=lambda row: _value(row, "operation_index", 4))
        indexes = [_value(row, "operation_index", 4) for row in ordered]
        if indexes != list(range(len(indexes))):
            continue
        batches.append(
            {
                "front_sequence": front_sequence,
                "operations": [
                    {
                        "event_id": str(_value(row, "id", 0)),
                        "operation_index": int(_value(row, "operation_index", 4)),
                        "operation_type": _value(row, "operation_type", 10),
                        "state_version": int(_value(row, "state_version", 5)),
                        "payload": dict(_value(row, "payload", 11)),
                    }
                    for row in ordered
                ],
            }
        )
    return batches


def has_front_sequence_gap(*, after_front_sequence: int, batches: list[dict[str, Any]]) -> bool:
    """첫 batch부터 Front sequence가 연속인지 확인한다."""

    expected = after_front_sequence + 1
    return any(
        batch["front_sequence"] != expected + index
        for index, batch in enumerate(batches)
    )


def build_sync_response(
    *,
    after_front_sequence: int,
    rows: Iterable[Mapping[str, Any] | Any],
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """DELTA와 SNAPSHOT의 상호 배타적 envelope를 만든다."""

    materialized_rows = list(rows)
    batches = build_complete_operation_batches(materialized_rows)
    all_sequences = {
        int(_value(row, "front_sequence", 3))
        for row in materialized_rows
        if _value(row, "front_sequence", 3) is not None
    }
    complete_sequences = {int(batch["front_sequence"]) for batch in batches}
    has_incomplete_batch = all_sequences != complete_sequences
    if has_incomplete_batch or has_front_sequence_gap(
        after_front_sequence=after_front_sequence, batches=batches
    ):
        return {"mode": "SNAPSHOT", "snapshot": snapshot, "operations": []}
    return {"mode": "DELTA", "snapshot": None, "operations": batches}


def encode_sse_batch(batch: Mapping[str, Any]) -> str:
    """polling과 같은 operations envelope를 하나의 SSE event로 직렬화한다."""

    payload = json.dumps(dict(batch), ensure_ascii=False, separators=(",", ":"))
    return (
        f"id: {int(batch['front_sequence'])}\n"
        "event: operations\n"
        f"data: {payload}\n\n"
    )


def encode_sse_snapshot(snapshot: Mapping[str, Any]) -> str:
    """보존 범위를 벗어난 재연결에 snapshot event를 보낸다."""

    payload = json.dumps(
        {"mode": "SNAPSHOT", "snapshot": dict(snapshot), "operations": []},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"event: snapshot\ndata: {payload}\n\n"
