"""FastAPI Backend 생성, 공통 오류 처리, router 등록 진입점."""

from contextlib import asynccontextmanager
import logging
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError

from backend.app.core.config import Settings, get_settings
from backend.app.core.errors import ApiError
from backend.app.core.logging import configure_logging
from backend.app.core.responses import api_error_response
from backend.app.repositories.admin_repository import PostgresAdminRepository
from backend.app.routers import game_router as game_module
from backend.app.routers.admin_router import router as admin_router
from backend.app.routers.health_router import router as health_router
from backend.app.routers.mcp_registry_router import router as minimal_mcp_router
from backend.app.services.admin_service import AdminService
from backend.app.services.game.runtime_factory import build_postgres_runtime, build_vote_insight_service


def _trace_id_from_header(value: str | None) -> str:
    """정규 UUID request id만 추적 ID로 재사용하고 나머지는 새 UUID로 대체한다."""

    if value is not None:
        try:
            parsed = UUID(value)
        except ValueError:
            pass
        else:
            if str(parsed) == value.lower():
                return str(parsed)
    return str(uuid4())


def create_app(
    *,
    settings: Settings | None = None,
    admin_repository=None,
    enable_background_worker: bool = True,
) -> FastAPI:
    """서버별 router와 비밀정보 비노출 오류 계약을 가진 앱을 생성한다."""

    configure_logging()
    effective_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        """앱별 게임·분석 worker를 독립 생성하고 역순으로 정리한다."""

        runtime = application.state.game_runtime
        analysis_worker = None
        try:
            if enable_background_worker and effective_settings.speech_analysis_enabled:
                try:
                    from functools import partial

                    import psycopg

                    from backend.app.infrastructure.transaction import TransactionManager
                    from backend.app.llm_provider.speech_analysis_provider import SpeechAnalysisProvider
                    from backend.app.repositories.speech_analysis_repository import (
                        PostgresSpeechAnalysisRepository,
                    )
                    from backend.app.services.game.speech_analysis_worker import SpeechAnalysisWorker

                    analysis_worker = SpeechAnalysisWorker(
                        PostgresSpeechAnalysisRepository(
                            TransactionManager(
                                effective_settings.effective_database_url,
                                # 게임용 연결과 분리하여 분석 DB 장애가 진행·종료를
                                # 무기한 지연시키지 않도록 각 대기 시간을 제한한다.
                                connection_factory=partial(
                                    psycopg.connect, connect_timeout=5,
                                    options="-c statement_timeout=5000 -c lock_timeout=1000",
                                ),
                            ),
                        ),
                        SpeechAnalysisProvider(effective_settings),
                        effective_settings,
                    )
                    analysis_worker.start()
                    application.state.speech_analysis_worker = analysis_worker
                    if hasattr(runtime, "configure_speech_analysis"):
                        runtime.configure_speech_analysis(analysis_worker.repository)
                except Exception:
                    # 선택적 분석 의존성의 초기화 오류는 게임 서버 전체 실패로
                    # 전파하지 않는다. 예외 원문에는 secret이 포함될 수 있다.
                    application.state.speech_analysis_start_failed = True
                    logging.getLogger(__name__).warning("SPEECH_ANALYSIS_START_FAILED")
            # 분석 준비 연결을 먼저 끝내야 기동 직후 마감된 토론이 대기를 건너뛰지 않는다.
            if enable_background_worker and hasattr(runtime, "start_background_worker"):
                runtime.start_background_worker()
            yield
        finally:
            try:
                if analysis_worker is not None:
                    try:
                        await analysis_worker.stop()
                    except Exception:
                        logging.getLogger(__name__).warning("SPEECH_ANALYSIS_STOP_FAILED")
            finally:
                if enable_background_worker and hasattr(runtime, "stop_background_worker"):
                    await runtime.stop_background_worker()

    application = FastAPI(
        title="Team4 Backend",
        version="1.0.0",
        lifespan=lifespan,
    )
    # Streamlit browser component은 인증·추적 header를 포함한 fetch를 사용하므로
    # 단순 GET이 아닌 CORS preflight가 발생한다. Front의 host·port를 사전 등록하지
    # 않도록 모든 origin을 허용하되 cookie 인증으로 오인되지 않게 credentials는 막는다.
    # 사용자 소유권과 관리자 권한은 각 API service가 별도로 계속 검사한다.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", "X-User-Id", "X-Request-Id", "Idempotency-Key", "Last-Event-ID"],
        expose_headers=["X-Request-Id"],
    )
    application.state.settings = effective_settings
    application.state.speech_analysis_worker = None
    application.state.speech_analysis_start_failed = False
    application.state.vote_insight_service = build_vote_insight_service(effective_settings)

    @application.middleware("http")
    async def attach_trace_id(request: Request, call_next):
        """요청 전체에 상관관계 ID를 유지하고 응답 헤더에도 같은 값을 제공한다."""

        # 공개 요청은 X-Request-Id만 추적 번호로 사용한다.
        # X-Internal-Request-Id는 내부 API 전용이므로 공개 경계에서 받지 않는다.
        request.state.trace_id = _trace_id_from_header(request.headers.get("X-Request-Id"))
        response = await call_next(request)
        response.headers["X-Request-Id"] = request.state.trace_id
        return response

    @application.exception_handler(ApiError)
    async def handle_api_error(request: Request, error: ApiError):
        """예상된 애플리케이션 오류를 공통 JSON 계약으로 변환한다."""

        return api_error_response(request, error)

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, error: RequestValidationError):
        """Pydantic 입력값을 되돌려주지 않고 실패 위치와 유형만 공개한다."""

        details = [{"location": list(item["loc"]), "type": item["type"]} for item in error.errors()]
        return api_error_response(
            request,
            ApiError(
                status_code=422,
                code="INVALID_REQUEST",
                message="요청 형식이 올바르지 않습니다.",
                details=details,
            ),
        )

    application.include_router(health_router)
    application.include_router(minimal_mcp_router)
    # 사용자 식별은 공개 요청의 X-User-Id(UUID v4)로만 처리한다.
    application.include_router(game_module.feedback_router)
    application.include_router(game_module.config_router)
    runtime = build_postgres_runtime(effective_settings)
    application.state.game_runtime = runtime
    # 운영 기본값은 실제 정본 PostgreSQL을 읽는다. 계약 테스트처럼 메모리
    # 게임을 주입한 경우에만 호출자가 같은 저장소의 adapter를 명시적으로
    # 전달한다. 그래야 관리자 화면이 테스트용 데이터와 운영 데이터를 섞지 않는다.
    effective_admin_repository = admin_repository or PostgresAdminRepository(
        effective_settings.effective_database_url
    )
    application.state.admin_service = AdminService(
        effective_admin_repository, effective_settings.admin_user_ids
    )
    application.include_router(game_module.router)
    application.include_router(admin_router)
    return application


app = create_app()
