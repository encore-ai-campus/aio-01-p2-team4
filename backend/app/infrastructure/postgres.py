"""검증된 Backend 설정으로 PostgreSQL 연결과 저장소를 조립한다."""

from collections.abc import Callable

import psycopg

from backend.app.core.config import Settings
from backend.app.repositories.user_repository import PostgresUserRepository


def build_user_repository(settings: Settings) -> PostgresUserRepository:
    """원본 DB URL 대신 대상 DB가 강제된 URL로 저장소를 생성한다."""

    return PostgresUserRepository(settings.effective_database_url)


def build_connection(settings: Settings, *, row_factory=None):
    """모든 Backend 저장소가 같은 검증된 대상 DB로 연결하게 한다.

    ``DATABASE_URL``에 다른 데이터베이스 경로가 들어 있어도 config가
    ``DATABASE_NAME``으로 교체한 URL만 사용한다. 반환된 연결은 호출자가
    반드시 transaction context 안에서 닫아야 한다.
    """

    kwargs = {"row_factory": row_factory} if row_factory is not None else {}
    return psycopg.connect(settings.effective_database_url, **kwargs)


ConnectionFactory = Callable[..., object]
