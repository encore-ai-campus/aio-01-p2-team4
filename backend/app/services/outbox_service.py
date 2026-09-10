"""commit된 event_outbox를 Redis event stream으로 전달하는 publisher."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from backend.app.infrastructure.redis.streams import RedisEventStream
from backend.app.infrastructure.transaction import TransactionManager
from backend.app.repositories.event_repository import PostgresEventRepository
from backend.app.repositories.outbox_repository import PostgresOutboxRepository


def _row_value(row: Mapping[str, Any] | Any, key: str, index: int) -> Any:
    """psycopg dict row와 tuple row를 publisher에서 동일하게 읽는다."""

    if isinstance(row, Mapping):
        return row[key]
    return row[index]


class PostgresOutboxPublisher:
    """DB를 원본으로 유지하면서 Redis fan-out을 재시도 가능하게 한다."""

    def __init__(
        self,
        transaction_manager: TransactionManager,
        event_stream: RedisEventStream,
        *,
        outbox_repository: PostgresOutboxRepository | None = None,
        event_repository: PostgresEventRepository | None = None,
    ) -> None:
        self._transactions = transaction_manager
        self._stream = event_stream
        self._outbox = outbox_repository or PostgresOutboxRepository()
        self._events = event_repository or PostgresEventRepository()

    def publish_once(self, *, limit: int = 50) -> int:
        """claim → Redis publish → published mark 순서로 한 번 처리한다."""

        with self._transactions.transaction() as connection:
            with connection.cursor() as cursor:
                claimed = self._outbox.claim_available(cursor, limit=limit)
        if not claimed:
            return 0

        grouped: dict[tuple[UUID, int], list[tuple[int, UUID]]] = defaultdict(list)
        internal_only: list[int] = []
        for row in claimed:
            outbox_id = int(_row_value(row, "id", 0))
            event_id = _row_value(row, "game_event_id", 1)
            with self._transactions.transaction() as connection:
                with connection.cursor() as cursor:
                    event = self._events.get_by_id(cursor, event_id)
            if event is None:
                internal_only.append(outbox_id)
                continue
            front_sequence = _row_value(event, "front_sequence", 3)
            game_id = _row_value(event, "game_id", 1)
            if front_sequence is None:
                internal_only.append(outbox_id)
            else:
                grouped[(game_id, int(front_sequence))].append((outbox_id, event_id))

        published_ids = list(internal_only)
        failed_ids: list[int] = []
        for (game_id, front_sequence), items in grouped.items():
            try:
                self._stream.publish_batch(
                    str(game_id),
                    front_sequence,
                    [str(event_id) for _, event_id in items],
                )
            except Exception:
                failed_ids.extend(outbox_id for outbox_id, _ in items)
            else:
                published_ids.extend(outbox_id for outbox_id, _ in items)

        if published_ids:
            with self._transactions.transaction() as connection:
                with connection.cursor() as cursor:
                    for outbox_id in published_ids:
                        self._outbox.mark_published(cursor, outbox_id)
        if failed_ids:
            with self._transactions.transaction() as connection:
                with connection.cursor() as cursor:
                    for outbox_id in failed_ids:
                        self._outbox.mark_failed(cursor, outbox_id, "REDIS_PUBLISH_FAILED")
        return len(published_ids)

