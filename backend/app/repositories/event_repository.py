"""append-only game_events 저장소."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from backend.app.repositories.game_repository import PostgresGameRepository


class PostgresEventRepository:
    """게임별 내부 sequence와 Front-visible cursor를 보존하며 event를 추가한다."""

    def __init__(self, game_repository: PostgresGameRepository | None = None) -> None:
        self._games = game_repository or PostgresGameRepository()

    def append(
        self,
        cursor: Any,
        *,
        game_id: UUID,
        state_version: int,
        event_type: str,
        audience: str,
        payload: Mapping[str, Any],
        audience_player_id: UUID | None = None,
        schema_version: int = 1,
        operation_type: str | None = None,
        front_sequence: int | None = None,
        operation_index: int | None = None,
    ) -> Mapping[str, Any]:
        """event 한 건을 추가한다. 기존 event는 UPDATE·DELETE하지 않는다."""

        if audience == "PLAYER" and audience_player_id is None:
            raise ValueError("PLAYER event에는 audience_player_id가 필요합니다.")
        if audience != "PLAYER" and audience_player_id is not None:
            raise ValueError("PLAYER가 아닌 event에는 audience_player_id를 넣을 수 없습니다.")
        front_fields = (front_sequence, operation_index, operation_type)
        if any(field is not None for field in front_fields) and not all(
            field is not None for field in front_fields
        ):
            raise ValueError("Front-visible event의 cursor 필드는 모두 필요합니다.")
        sequence = self._games.next_event_sequence(cursor, game_id)
        cursor.execute(
            """
            INSERT INTO public.game_events (
                game_id, sequence, front_sequence, operation_index, state_version,
                event_type, audience, audience_player_id, schema_version,
                operation_type, payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, game_id, sequence, front_sequence, operation_index,
                      state_version, event_type, audience, audience_player_id,
                      schema_version, operation_type, payload, created_at
            """,
            (
                game_id,
                sequence,
                front_sequence,
                operation_index,
                state_version,
                event_type,
                audience,
                audience_player_id,
                schema_version,
                operation_type,
                Jsonb(dict(payload)),
            ),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("game event 저장 결과가 반환되지 않았습니다.")
        return row

    def get_by_id(self, cursor: Any, event_id: UUID) -> Mapping[str, Any] | None:
        """publisher가 event_outbox의 ID만으로 Front event를 다시 읽는다."""

        cursor.execute(
            """
            SELECT id, game_id, sequence, front_sequence, operation_index,
                   state_version, event_type, audience, audience_player_id,
                   schema_version, operation_type, payload, created_at
            FROM public.game_events
            WHERE id = %s
            """,
            (event_id,),
        )
        return cursor.fetchone()

    def list_front_events(
        self,
        cursor: Any,
        *,
        game_id: UUID,
        after_front_sequence: int,
        human_player_id: UUID | None = None,
        limit: int = 100,
    ) -> list[Mapping[str, Any]]:
        """마지막 Front sequence 다음 event를 순서대로 읽는다.

        한 batch의 일부만 내려보내지 않도록 실제 sync service가 operation index를
        다시 검사한다. 이 repository는 SQL 조회만 담당하고 snapshot 판단은 하지
        않는다.
        """

        if after_front_sequence < 0 or not 1 <= limit <= 500:
            raise ValueError("event cursor 또는 limit이 올바르지 않습니다.")
        cursor.execute(
            """
            SELECT id, game_id, sequence, front_sequence, operation_index,
                   state_version, event_type, audience, audience_player_id,
                   schema_version, operation_type, payload, created_at
            FROM public.game_events
            WHERE game_id = %s
              AND (audience = 'PUBLIC' OR (audience = 'PLAYER' AND audience_player_id = %s))
              AND front_sequence > %s
            ORDER BY front_sequence, operation_index
            LIMIT %s
            """,
            (game_id, human_player_id, after_front_sequence, limit),
        )
        return list(cursor.fetchall())

    def list_snapshot_public_events(
        self,
        cursor: Any,
        *,
        game_id: UUID,
        through_sequence: int,
        through_state_version: int,
        through_front_sequence: int,
    ) -> list[Mapping[str, Any]]:
        """읽은 game 행의 상한 안에서 공개 대화 이력 전체를 내부 확정 순서로 읽는다.

        READ COMMITTED에서 후속 조회 전에 새 command가 commit돼도 최초 snapshot
        cursor 이후의 이벤트를 섞지 않는다. snapshot은 delta와 달리 이력 전체가
        필요하므로 sync의 500건 제한을 적용하지 않는다. payload 공개 여부는 서비스의
        폐쇄형 projection이 다시 검증하며 PUBLIC 표기만으로 신뢰하지 않는다.
        """

        if through_sequence < 0 or through_state_version < 1 or through_front_sequence < 0:
            raise ValueError("snapshot event 조회 상한이 올바르지 않습니다.")
        cursor.execute(
            """
            SELECT id, game_id, sequence, front_sequence, operation_index,
                   state_version, event_type, audience, audience_player_id,
                   schema_version, operation_type, payload, created_at
            FROM public.game_events
            WHERE game_id = %s
              AND sequence > 0 AND sequence <= %s
              AND state_version > 0 AND state_version <= %s
              AND front_sequence > 0 AND front_sequence <= %s
              AND audience = 'PUBLIC'
              AND audience_player_id IS NULL
              AND operation_type = 'APPEND_PUBLIC_EVENT'
              AND schema_version = 1
            ORDER BY sequence
            """,
            (game_id, through_sequence, through_state_version, through_front_sequence),
        )
        return list(cursor.fetchall())

    def list_snapshot_private_events(self, cursor: Any, *, game_id: UUID, player_id: UUID,
                                     through_sequence: int, through_state_version: int,
                                     through_front_sequence: int | None = None) -> list[Mapping[str, Any]]:
        """수신자별 private event를 읽고 인간 Front 조회에는 추가 cursor 상한을 적용한다."""

        if through_sequence < 0 or through_state_version < 1 or (through_front_sequence is not None and through_front_sequence < 0):
            raise ValueError("snapshot event 조회 상한이 올바르지 않습니다.")
        cursor.execute(
            """
            SELECT id, game_id, sequence, front_sequence, operation_index,
                   state_version, event_type, audience, audience_player_id,
                   schema_version, operation_type, payload, created_at
            FROM public.game_events
            WHERE game_id = %s AND audience = 'PLAYER' AND audience_player_id = %s
              AND sequence > 0 AND sequence <= %s
              AND state_version > 0 AND state_version <= %s
              AND (%s::bigint IS NULL OR (
                  front_sequence > 0 AND front_sequence <= %s
                  AND operation_type = 'APPEND_PRIVATE_EVENT'
              ))
              AND schema_version = 1
            ORDER BY sequence
            """,
            (game_id, player_id, through_sequence, through_state_version, through_front_sequence, through_front_sequence),
        )
        return list(cursor.fetchall())
