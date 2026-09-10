"""event_outbox 영속 전달 큐 저장소."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID


class PostgresOutboxRepository:
    """commit된 game_event를 Redis publisher가 안전하게 재처리하도록 보관한다."""

    def enqueue(self, cursor: Any, game_event_id: UUID) -> Mapping[str, Any]:
        """event 본문을 복사하지 않고 event ID만 outbox에 추가한다."""

        cursor.execute(
            """
            INSERT INTO public.event_outbox (game_event_id)
            VALUES (%s)
            ON CONFLICT (game_event_id) DO NOTHING
            RETURNING id, game_event_id, available_at, published_at,
                      attempt_count, last_error_code
            """,
            (game_event_id,),
        )
        row = cursor.fetchone()
        if row is None:
            # 이미 같은 event가 enqueue된 경우에도 현재 원장을 조회해
            # 호출부가 동일한 outbox를 계속 다루게 한다.
            cursor.execute(
                """
                SELECT id, game_event_id, available_at, published_at,
                       attempt_count, last_error_code
                FROM public.event_outbox
                WHERE game_event_id = %s
                """,
                (game_event_id,),
            )
            row = cursor.fetchone()
        if row is None:
            raise RuntimeError("event outbox 저장 결과가 반환되지 않았습니다.")
        return row

    def claim_available(self, cursor: Any, *, limit: int = 50) -> list[Mapping[str, Any]]:
        """동시에 실행된 publisher 중 한 작업만 outbox 행을 claim한다."""

        if not 1 <= limit <= 500:
            raise ValueError("outbox claim limit은 1~500이어야 합니다.")
        cursor.execute(
            """
            WITH claimed AS (
                SELECT id
                FROM public.event_outbox
                WHERE published_at IS NULL
                  AND available_at <= CURRENT_TIMESTAMP
                ORDER BY id
                FOR UPDATE SKIP LOCKED
                LIMIT %s
            )
            UPDATE public.event_outbox AS outbox
            SET attempt_count = outbox.attempt_count + 1
            FROM claimed
            WHERE outbox.id = claimed.id
            RETURNING outbox.id, outbox.game_event_id, outbox.available_at,
                      outbox.published_at, outbox.attempt_count,
                      outbox.last_error_code
            """,
            (limit,),
        )
        return list(cursor.fetchall())

    def mark_published(self, cursor: Any, outbox_id: int) -> Mapping[str, Any]:
        """publish 성공을 기록하고 이미 성공한 행의 시각은 덮어쓰지 않는다."""

        cursor.execute(
            """
            UPDATE public.event_outbox
            SET published_at = COALESCE(published_at, CURRENT_TIMESTAMP),
                last_error_code = NULL
            WHERE id = %s
            RETURNING id, game_event_id, available_at, published_at,
                      attempt_count, last_error_code
            """,
            (outbox_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise LookupError("outbox를 찾을 수 없습니다.")
        return row

    def mark_failed(self, cursor: Any, outbox_id: int, error_code: str) -> Mapping[str, Any]:
        """비밀 없는 오류 코드만 남기고 published_at은 비워 둔다."""

        if not error_code.strip() or len(error_code) > 64:
            raise ValueError("outbox 오류 코드는 1~64자여야 합니다.")
        cursor.execute(
            """
            UPDATE public.event_outbox
            SET last_error_code = %s
            WHERE id = %s
            RETURNING id, game_event_id, available_at, published_at,
                      attempt_count, last_error_code
            """,
            (error_code, outbox_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise LookupError("outbox를 찾을 수 없습니다.")
        return row
