"""암호화된 game snapshot 저장소."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PostgresSnapshotRepository:
    """snapshot 원문을 해석하지 않고 암호문·nonce·checksum만 저장한다."""

    def save(
        self,
        cursor: Any,
        *,
        game_id: UUID,
        state_version: int,
        last_front_sequence: int,
        schema_version: int,
        state_ciphertext: bytes,
        nonce: bytes,
        key_id: str,
        checksum: str,
    ) -> Mapping[str, Any]:
        """한 state version에는 하나의 snapshot만 존재하도록 저장한다."""

        if not state_ciphertext or not nonce:
            raise ValueError("snapshot 암호문과 nonce는 비어 있을 수 없습니다.")
        if not SHA256_RE.fullmatch(checksum):
            raise ValueError("snapshot checksum은 소문자 SHA-256 형식이어야 합니다.")
        cursor.execute(
            """
            INSERT INTO public.game_snapshots (
                game_id, state_version, last_front_sequence, schema_version,
                state_ciphertext, nonce, key_id, checksum
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (game_id, state_version) DO UPDATE
            SET last_front_sequence = EXCLUDED.last_front_sequence,
                schema_version = EXCLUDED.schema_version,
                state_ciphertext = EXCLUDED.state_ciphertext,
                nonce = EXCLUDED.nonce,
                key_id = EXCLUDED.key_id,
                checksum = EXCLUDED.checksum
            RETURNING id, game_id, state_version, last_front_sequence,
                      schema_version, state_ciphertext, nonce, key_id,
                      checksum, created_at
            """,
            (
                game_id,
                state_version,
                last_front_sequence,
                schema_version,
                state_ciphertext,
                nonce,
                key_id,
                checksum,
            ),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("snapshot 저장 결과가 반환되지 않았습니다.")
        return row

    def latest(self, cursor: Any, game_id: UUID) -> Mapping[str, Any] | None:
        """가장 최신 snapshot을 반환한다. 암호문은 여기서 복호화하지 않는다."""

        cursor.execute(
            """
            SELECT id, game_id, state_version, last_front_sequence, schema_version,
                   state_ciphertext, nonce, key_id, checksum, created_at
            FROM public.game_snapshots
            WHERE game_id = %s
            ORDER BY state_version DESC
            LIMIT 1
            """,
            (game_id,),
        )
        return cursor.fetchone()
