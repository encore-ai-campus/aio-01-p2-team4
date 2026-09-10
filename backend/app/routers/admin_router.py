"""관리자 조회의 권한·입력 검증과 공개 응답을 연결한다.

저장소 호출은 동기식이므로 handler를 일반 함수로 두어 FastAPI의 작업 스레드에서
실행한다. 관리자 집계가 지연돼도 MCP·게임 요청의 공용 이벤트 루프를 점유하지 않는다.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from backend.app.core.errors import ApiError
from backend.app.core.responses import api_success_response, request_trace_id
from backend.app.routers.game_router import user_id_header
from backend.app.schemas.admin_schema import (
    AdminAgentJobQuery,
    AdminAuditQuery,
    AdminFeedbackQuery,
    AdminGameListQuery,
    AdminInsightQuery,
    AdminMetricsQuery,
    AdminSpeechAnalyticsQuery,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def _validation_error(error: ValidationError) -> ApiError:
    """관리자 query의 내부 검증 원문 대신 위치와 유형만 공개한다."""

    return ApiError(
        status_code=422,
        code="INVALID_REQUEST",
        message="요청 형식이 올바르지 않습니다.",
        details=[{"location": list(item["loc"]), "type": item["type"]} for item in error.errors()],
    )


def _admin_service(request: Request):
    """앱 생성 시 주입한 관리자 서비스를 사용한다."""

    return request.app.state.admin_service


@router.get("/games", response_model=None)
def list_admin_games(
    request: Request,
    x_user_id: str | None = Header(default=None),
    status: str | None = Query(default=None),
    phase: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> JSONResponse:
    """관리자 allowlist를 통과한 경우 게임 요약 목록만 반환한다."""

    try:
        query = AdminGameListQuery(status=status, phase=phase, cursor=cursor, limit=limit)
    except ValidationError as error:
        raise _validation_error(error) from error
    data = _admin_service(request).list_games(
        user_id_header(x_user_id),
        status=query.status,
        phase=query.phase,
        cursor=query.cursor,
        limit=query.limit,
        request_id=UUID(request_trace_id(request)),
    )
    return api_success_response(request, data)


@router.get("/role-win-rates", response_model=None)
def get_role_win_rates(
    request: Request,
    x_user_id: str | None = Header(default=None),
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
) -> JSONResponse:
    """화면용 직업별 집계만 반환하고 개별 AI의 역할은 노출하지 않는다."""

    admin_id = user_id_header(x_user_id)
    _admin_service(request).require_admin(admin_id)
    try:
        query = AdminMetricsQuery.model_validate({"from": from_, "to": to})
    except ValidationError as error:
        raise _validation_error(error) from error
    data = _admin_service(request).role_win_rates(
        admin_id, from_time=query.from_, to_time=query.to,
        request_id=UUID(request_trace_id(request)),
    )
    return api_success_response(request, data)


@router.get("/persona-win-rates", response_model=None)
def get_persona_win_rates(
    request: Request,
    x_user_id: str | None = Header(default=None),
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
) -> JSONResponse:
    """에이전트 페르소나별 승률만 반환하고 원본 성격 파라미터는 노출하지 않는다."""

    admin_id = user_id_header(x_user_id)
    _admin_service(request).require_admin(admin_id)
    try:
        query = AdminMetricsQuery.model_validate({"from": from_, "to": to})
    except ValidationError as error:
        raise _validation_error(error) from error
    data = _admin_service(request).persona_win_rates(
        admin_id, from_time=query.from_, to_time=query.to,
        request_id=UUID(request_trace_id(request)),
    )
    return api_success_response(request, data)


@router.get("/speech-analytics", response_model=None)
def get_speech_analytics(
    request: Request,
    x_user_id: str | None = Header(default=None),
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    game_id: str | None = Query(default=None),
    persona_id: str | None = Query(default=None),
    round: str | None = Query(default=None),
    analysis_version: str | None = Query(default=None),
    limit: str = Query(default="12"),
) -> JSONResponse:
    """공개 AI 발언의 임베딩·claims 집계를 관리자에게 read-only로 반환한다."""

    admin_id = user_id_header(x_user_id)
    _admin_service(request).require_admin(admin_id)
    try:
        query = AdminSpeechAnalyticsQuery.model_validate({
            "from": from_,
            "to": to,
            "game_id": game_id,
            "persona_id": persona_id,
            "round": round,
            "analysis_version": analysis_version,
            "limit": limit,
        })
    except ValidationError as error:
        raise _validation_error(error) from error
    data = _admin_service(request).speech_analytics(
        admin_id,
        from_time=query.from_,
        to_time=query.to,
        game_id=query.game_id,
        persona_id=query.persona_id,
        round_number=query.round,
        analysis_version=query.analysis_version,
        topic_limit=query.limit,
        request_id=UUID(request_trace_id(request)),
    )
    return api_success_response(request, data)


@router.get("/feedback", response_model=None)
def list_admin_feedback(
    request: Request,
    x_user_id: str | None = Header(default=None),
    feedback_type: str | None = Query(default=None),
    rating: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: str = Query(default="20"),
) -> JSONResponse:
    """필터와 커서를 검증한 뒤 피드백의 공개 목록 필드만 조회한다."""

    admin_id = user_id_header(x_user_id)
    _admin_service(request).require_admin(admin_id)
    try:
        query = AdminFeedbackQuery(feedback_type=feedback_type, rating=rating,
                                   cursor=cursor, limit=limit)
    except ValidationError as error:
        raise _validation_error(error) from error
    data = _admin_service(request).list_feedback(
        admin_id, **query.model_dump(), request_id=UUID(request_trace_id(request)),
    )
    return api_success_response(request, data)


@router.get("/agent-jobs", response_model=None)
def list_admin_agent_jobs(
    request: Request,
    x_user_id: str | None = Header(default=None),
    game_id: str | None = Query(default=None),
    job_kind: str | None = Query(default=None),
    status: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: str = Query(default="20"),
) -> JSONResponse:
    """권한을 먼저 확인한 뒤 Agent 작업 분류·UUID·페이지 크기를 검증한다."""

    admin_id = user_id_header(x_user_id)
    _admin_service(request).require_admin(admin_id)
    try:
        query = AdminAgentJobQuery(
            game_id=game_id, job_kind=job_kind, status=status, cursor=cursor, limit=limit,
        )
    except ValidationError as error:
        raise _validation_error(error) from error
    data = _admin_service(request).list_agent_jobs(
        admin_id, **query.model_dump(), request_id=UUID(request_trace_id(request)),
    )
    response = api_success_response(request, data)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/audit-logs", response_model=None)
def list_admin_audit_logs(
    request: Request,
    x_user_id: str | None = Header(default=None),
    event_type: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: str = Query(default="20"),
) -> JSONResponse:
    """관리자 감사 분류와 bigint 커서만 허용한다."""

    admin_id = user_id_header(x_user_id)
    _admin_service(request).require_admin(admin_id)
    try:
        query = AdminAuditQuery(event_type=event_type, cursor=cursor, limit=limit)
    except ValidationError as error:
        raise _validation_error(error) from error
    data = _admin_service(request).list_audit_logs(
        admin_id, **query.model_dump(), request_id=UUID(request_trace_id(request)),
    )
    return api_success_response(request, data)


@router.post("/insights/query", response_model=None)
def query_admin_insights(
    request: Request,
    query: AdminInsightQuery,
    x_user_id: str | None = Header(default=None),
) -> JSONResponse:
    """승인된 운영 자료를 검색해 근거·신뢰도만 반환하는 관리자 질문 API다."""

    admin_id = user_id_header(x_user_id)
    data = _admin_service(request).query_insights(
        admin_id,
        question=query.question,
        source_types=query.filters.source_types,
        rating_lte=query.filters.rating_lte,
        from_time=query.filters.from_,
        to_time=query.filters.to,
        top_k=query.top_k,
        request_id=UUID(request_trace_id(request)),
    )
    return api_success_response(request, data)


@router.get("/games/{game_id}", response_model=None)
def get_admin_game(
    request: Request,
    game_id: UUID,
    x_user_id: str | None = Header(default=None),
) -> JSONResponse:
    """관리자에게도 role·개인 사실·개별 행동·seed를 보내지 않는다."""

    data = _admin_service(request).get_game(
        user_id_header(x_user_id), game_id, request_id=UUID(request_trace_id(request))
    )
    return api_success_response(request, data)


@router.get("/metrics", response_model=None)
def get_admin_metrics(
    request: Request,
    x_user_id: str | None = Header(default=None),
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
) -> JSONResponse:
    """최대 31일 범위의 운영 지표만 반환한다."""

    try:
        query = AdminMetricsQuery.model_validate({"from": from_, "to": to})
    except ValidationError as error:
        raise _validation_error(error) from error
    data = _admin_service(request).metrics(
        user_id_header(x_user_id),
        from_time=query.from_,
        to_time=query.to,
        request_id=UUID(request_trace_id(request)),
    )
    return api_success_response(request, data)
