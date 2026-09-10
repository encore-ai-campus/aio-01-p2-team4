"""PostgreSQL transaction과 advisory lock의 공통 경계."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from hashlib import sha256
from typing import Any, Protocol, cast

import psycopg


class TransactionConnection(Protocol):
    """운영 연결과 테스트용 연결이 제공해야 하는 최소 기능."""

    def __enter__(self) -> "TransactionConnection": ...

    def __exit__(self, *args: object) -> bool | None: ...


ConnectionFactory = Callable[..., TransactionConnection]


class TransactionManager:
    """짧은 DB transaction을 열고 정상 종료 시 commit, 예외 시 rollback한다.

    외부 LLM·MCP·HTTP 호출은 이 context 안에서 실행하지 않는다. transaction이
    오래 잡히면 다른 게임의 진행을 막을 수 있으므로 DB 읽기·검증·쓰기만
    포함해야 한다.
    """

    def __init__(
        self,
        database_url: str,
        *,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self._database_url = database_url
        self._connection_factory = connection_factory or cast(
            ConnectionFactory, psycopg.connect
        )

    @contextmanager
    def transaction(self) -> Iterator[TransactionConnection]:
        """하나의 연결 context를 transaction 경계로 제공한다."""

        with self._connection_factory(self._database_url) as connection:
            yield connection


def advisory_lock_key(*parts: object) -> int:
    """같은 논리 작업이 같은 PostgreSQL advisory lock을 사용하게 한다.

    UUID와 idempotency key를 문자열로 합칠 때 구분자를 넣고 SHA-256 앞
    8바이트를 signed bigint로 바꾼다. 해시 충돌은 작업을 잠시 직렬화할 뿐,
    실제 중복 방지는 command_receipts의 UNIQUE 제약이 담당한다.
    """

    material = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(sha256(material).digest()[:8], byteorder="big", signed=True)


def lock_idempotency(cursor: Any, *parts: object) -> None:
    """현재 transaction 동안 idempotency 작업을 직렬화한다."""

    cursor.execute(
        "SELECT pg_advisory_xact_lock(%s)",
        (advisory_lock_key(*parts),),
    )


def lock_game(cursor: Any, game_id: object) -> None:
    """게임 단위 advisory lock을 잡는다.

    실제 게임 행 잠금은 ``GameRepository.lock_game``의 ``FOR UPDATE``가
    담당하며, 이 함수는 서로 다른 생성·command 경로의 순서를 맞추는
    보조 잠금이다.
    """

    cursor.execute(
        "SELECT pg_advisory_xact_lock(%s)",
        (advisory_lock_key("GAME", game_id),),
    )
