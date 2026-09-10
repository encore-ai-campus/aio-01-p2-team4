"""정본 ``users`` 테이블만 다루는 PostgreSQL 사용자 저장소."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol, cast
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from backend.app.models.identity import UserRecord


class CursorLike(Protocol):
    """실제 psycopg 커서와 테스트용 가짜 커서가 함께 지켜야 할 계약."""

    def __enter__(self) -> "CursorLike": ...

    def __exit__(self, *args: object) -> bool | None: ...

    def execute(self, query: str, params: object = None) -> "CursorLike": ...

    def fetchone(self) -> Mapping[str, Any] | None: ...


class ConnectionLike(Protocol):
    """사용자 저장소가 필요한 최소 DB 연결 기능."""

    def __enter__(self) -> "ConnectionLike": ...

    def __exit__(self, *args: object) -> bool | None: ...

    def cursor(self, *args: object, **kwargs: object) -> CursorLike: ...


ConnectionFactory = Callable[..., ConnectionLike]


class PostgresUserRepository:
    """UUID 사용자 생성·조회만 담당한다.

    최초 쓰기 요청은 ``ensure_user``를 사용한다. 같은 UUID로 여러 번
    요청해도 한 행만 남도록 DB의 PK와 ``ON CONFLICT``를 함께 사용한다.
    조회 요청은 ``get_user``를 사용하며, 알 수 없는 UUID를 자동 생성하지
    않는다. 이 구분이 있어 단순 조회만으로 사용자 데이터가 생기지 않는다.
    """

    def __init__(
        self,
        database_url: str,
        *,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        """운영에서는 psycopg를 사용하고 테스트에서는 연결 대역을 받는다."""

        self._database_url = database_url
        self._connection_factory = connection_factory or cast(
            ConnectionFactory, psycopg.connect
        )

    @property
    def database_url(self) -> str:
        """배선 확인용 URL을 반환한다. 로그나 API 응답에 기록하면 안 된다."""

        return self._database_url

    def ensure_user(
        self,
        user_id: UUID,
        *,
        now: datetime | None = None,
    ) -> UserRecord:
        """사용자를 멱등 생성하고 최근 확인 시각을 갱신한다.

        ``now``는 테스트에서만 주입해 결과를 고정할 수 있다. 운영에서는
        PostgreSQL의 ``NOW()``를 사용해 DB 시간을 기준으로 기록한다.
        ``users.id``에 DB default를 두지 않고 API가 받은 UUID를 그대로 넣는다.
        """

        if now is None:
            query = """
                INSERT INTO users (id, created_at, last_seen_at)
                VALUES (%s, NOW(), NOW())
                ON CONFLICT (id) DO UPDATE
                    SET last_seen_at = EXCLUDED.last_seen_at
                RETURNING id, created_at, last_seen_at
            """
            params: tuple[object, ...] = (user_id,)
        else:
            # 고정 시각은 테스트용 경로다. timezone 없는 값을 DB에 넣지 않도록
            # UTC로 정규화해 운영 데이터와 같은 timestamptz 의미를 유지한다.
            if now.tzinfo is None:
                now = now.replace(tzinfo=UTC)
            now = now.astimezone(UTC)
            query = """
                INSERT INTO users (id, created_at, last_seen_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (id) DO UPDATE
                    SET last_seen_at = EXCLUDED.last_seen_at
                RETURNING id, created_at, last_seen_at
            """
            params = (user_id, now, now)

        with self._connection_factory(self._database_url) as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, params)
                row = _required_row(cursor.fetchone(), "ensured user")

        return _row_to_user(row)

    def ensure_user_in_transaction(self, cursor: CursorLike, user_id: UUID) -> UserRecord:
        """이미 열린 게임 생성 transaction 안에서 사용자를 멱등 준비한다.

        게임 생성은 users, games, players, facts, event, receipt가 모두 성공해야만
        commit되어야 한다. 별도 연결을 여는 ``ensure_user``와 달리 이 메서드는
        호출자가 가진 cursor만 사용해 중간 실패 시 users 행까지 함께 rollback한다.
        """

        cursor.execute(
            """
            INSERT INTO users (id, created_at, last_seen_at)
            VALUES (%s, NOW(), NOW())
            ON CONFLICT (id) DO UPDATE
                SET last_seen_at = EXCLUDED.last_seen_at
            RETURNING id, created_at, last_seen_at
            """,
            (user_id,),
        )
        return _row_to_user(_required_row(cursor.fetchone(), "ensured user"))

    def get_user(self, user_id: UUID) -> UserRecord | None:
        """사용자 행을 조회한다. 행이 없으면 생성하지 않고 ``None``을 반환한다."""

        with self._connection_factory(self._database_url) as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, created_at, last_seen_at
                    FROM users
                    WHERE id = %s
                    """,
                    (user_id,),
                )
                row = cursor.fetchone()

        return _row_to_user(row) if row is not None else None


def _required_row(
    row: Mapping[str, Any] | None,
    operation: str,
) -> Mapping[str, Any]:
    """쓰기 결과가 없으면 불완전한 사용자 객체를 만들지 않는다."""

    if row is None:
        raise RuntimeError(f"사용자 저장 결과가 반환되지 않았습니다: {operation}")
    return row


def _row_to_user(row: Mapping[str, Any]) -> UserRecord:
    """DB 행을 타입이 명확한 내부 모델로 변환한다."""

    user_id = row["id"]
    if not isinstance(user_id, UUID):
        user_id = UUID(str(user_id))

    created_at = row["created_at"]
    last_seen_at = row["last_seen_at"]
    if not isinstance(created_at, datetime) or not isinstance(last_seen_at, datetime):
        raise TypeError("users의 created_at과 last_seen_at은 datetime이어야 합니다.")

    return UserRecord(
        id=user_id,
        created_at=created_at,
        last_seen_at=last_seen_at,
    )
