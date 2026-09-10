"""Backend 프로세스와 필수 저장소의 상태를 확인하는 endpoint."""

import psycopg
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from redis import Redis
from redis.exceptions import RedisError

from backend.app.schemas.common_schema import HealthResponse, ReadinessResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """프로세스가 HTTP 요청을 처리할 수 있음을 고정 응답으로 알린다."""

    return HealthResponse()


def _postgresql_ready(database_url: str) -> bool:
    """테이블이나 데이터를 바꾸지 않고 PostgreSQL 연결만 확인한다.

    ``SELECT 1``은 저장·수정 작업이 없는 가장 작은 확인 쿼리다. 연결이 오래
    멈추면 readiness 요청 전체가 지연되므로 2초 안에 연결되지 않으면 실패로
    판단한다. 예외 원문에는 접속 정보가 들어갈 수 있어 호출자에게 반환하지 않는다.
    """

    try:
        with psycopg.connect(database_url, connect_timeout=2) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                row = cursor.fetchone()
        return row is not None and int(row[0]) == 1
    except (psycopg.Error, OSError, TypeError, ValueError):
        return False


def _redis_ready(redis_url: str) -> bool:
    """Redis에 값을 쓰지 않고 PING 응답만 확인한다.

    Redis는 원본 DB가 아니지만 lock과 공개 event 전달에 필요하다. 준비 확인에서는
    key를 생성하지 않으며, 확인이 끝나면 연결 pool도 즉시 닫는다.
    """

    try:
        client = Redis.from_url(
            redis_url,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    except (RedisError, OSError, TypeError, ValueError):
        return False
    try:
        ping_succeeded = bool(client.ping())
    except (RedisError, OSError, TypeError, ValueError):
        ping_succeeded = False
    try:
        client.close()
    except RedisError:
        # 연결 종료조차 실패했다면 해당 Redis는 준비된 상태로 볼 수 없다.
        return False
    return ping_succeeded


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
)
def ready(request: Request) -> JSONResponse:
    """PostgreSQL과 Redis가 모두 연결될 때만 새 요청을 받을 준비가 됐다고 알린다.

    LLM Provider와 MCP 서버는 게임 도중 실패해도 규칙 기반 fallback을 사용할 수
    있으므로 readiness 조건에 넣지 않는다. 이 구분 덕분에 외부 AI 서비스 장애가
    게임 생성 자체를 불필요하게 막지 않는다.
    """

    settings = request.app.state.settings
    postgresql_ok = _postgresql_ready(settings.effective_database_url)
    redis_ok = _redis_ready(settings.redis_url)
    all_ready = postgresql_ok and redis_ok
    body = ReadinessResponse(
        status="ready" if all_ready else "not_ready",
        dependencies={
            "postgresql": "ok" if postgresql_ok else "error",
            "redis": "ok" if redis_ok else "error",
        },
    )
    return JSONResponse(
        status_code=200 if all_ready else 503,
        content=body.model_dump(mode="json"),
    )
