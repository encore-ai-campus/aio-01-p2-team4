"""command_receipts 멱등성 원장 저장소."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PostgresReceiptRepository:
    """같은 principal의 idempotency key를 불변 결과와 연결한다."""

    def find(
        self,
        cursor: Any,
        *,
        principal_type: str,
        principal_id: UUID,
        idempotency_key: UUID,
    ) -> Mapping[str, Any] | None:
        """기존 receipt를 찾는다. 없으면 쓰기를 자동으로 수행하지 않는다."""

        cursor.execute(
            """
            SELECT id, principal_type, principal_id, idempotency_key, route_scope,
                   game_id, request_hash, result_state_version, http_status,
                   result_body, created_at
            FROM public.command_receipts
            WHERE principal_type = %s
              AND principal_id = %s
              AND idempotency_key = %s
            """,
            (principal_type, principal_id, idempotency_key),
        )
        return cursor.fetchone()

    def insert(
        self,
        cursor: Any,
        *,
        principal_type: str,
        principal_id: UUID,
        idempotency_key: UUID,
        route_scope: str,
        game_id: UUID | None,
        request_hash: str,
        result_state_version: int | None,
        http_status: int,
        result_body: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """terminal 응답을 저장한다. UNIQUE 충돌은 호출자가 replay로 처리한다."""

        if not SHA256_RE.fullmatch(request_hash):
            raise ValueError("request_hash는 소문자 SHA-256 형식이어야 합니다.")
        if not result_body:
            raise ValueError("result_body는 비어 있지 않은 object여야 합니다.")

        cursor.execute(
            """
            INSERT INTO public.command_receipts (
                principal_type, principal_id, idempotency_key, route_scope,
                game_id, request_hash, result_state_version, http_status, result_body
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, principal_type, principal_id, idempotency_key, route_scope,
                      game_id, request_hash, result_state_version, http_status,
                      result_body, created_at
            """,
            (
                principal_type,
                principal_id,
                idempotency_key,
                route_scope,
                game_id,
                request_hash,
                result_state_version,
                http_status,
                Jsonb(dict(result_body)),
            ),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("command receipt 저장 결과가 반환되지 않았습니다.")
        return row
