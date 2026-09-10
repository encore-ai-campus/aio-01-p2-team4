"""정본 mystery-v1 공개 게임·피드백 API를 제공하는 router다."""

from __future__ import annotations

import asyncio
import json
from uuid import UUID
from typing import Literal

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ValidationError

from backend.app.core.errors import ApiError
from backend.app.core.responses import api_error_response, api_success_response
from backend.app.schemas.command_schema import GameCommandRequest
from backend.app.schemas.feedback_schema import FeedbackRequest
from backend.app.schemas.game_schema import (
    CUSTOM_ROLE_ABILITIES, CUSTOM_ROLE_CATALOG_VERSION, CreateGameRequest,
)
router = APIRouter(prefix="/api/v1/games", tags=["games"])
feedback_router = APIRouter(prefix="/api/v1", tags=["feedback"])
config_router = APIRouter(prefix="/api/v1/game-config", tags=["game-config"])


@config_router.get("/custom-role-abilities")
async def custom_role_abilities(
    request: Request, x_user_id: str | None = Header(default=None),
) -> JSONResponse:
    """인증 식별자를 확인한 뒤 DB 호출 없이 고정 catalog를 반환한다."""

    user_id_header(x_user_id)
    abilities = [
        {"id": ability_id, "label": item["label"], "factions": item["factions"]}
        for ability_id, item in CUSTOM_ROLE_ABILITIES.items()
    ]
    return api_success_response(request, {
        "catalog_version": CUSTOM_ROLE_CATALOG_VERSION,
        "abilities": abilities,
    })

def game_runtime(request: Request):
    """전역 변수가 아닌 현재 FastAPI 앱의 게임 runtime을 반환한다."""

    return request.app.state.game_runtime


def user_id_header(value: str | None) -> UUID:
    """X-User-Id를 인증 토큰이 아닌 UUID v4 식별자로만 검증한다."""

    if value is None:
        raise ApiError(status_code=400, code="MISSING_USER_ID", message="X-User-Id 헤더가 필요합니다.")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as error:
        raise ApiError(status_code=400, code="INVALID_REQUEST", message="X-User-Id는 UUID 형식이어야 합니다.") from error
    if parsed.version != 4 or str(parsed) != value.lower():
        raise ApiError(status_code=400, code="INVALID_REQUEST", message="X-User-Id는 UUID v4여야 합니다.")
    return parsed


def idempotency_header(value: str | None) -> UUID:
    """변경 요청의 멱등 key를 UUID v4로 검증한다."""

    if value is None:
        raise ApiError(status_code=400, code="MISSING_IDEMPOTENCY_KEY", message="Idempotency-Key 헤더가 필요합니다.")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as error:
        raise ApiError(status_code=400, code="INVALID_REQUEST", message="Idempotency-Key는 UUID 형식이어야 합니다.") from error
    if parsed.version != 4 or str(parsed) != value.lower():
        raise ApiError(status_code=400, code="INVALID_REQUEST", message="Idempotency-Key는 UUID v4여야 합니다.")
    return parsed


@router.post("", status_code=201)
async def create_game(
    request: Request,
    x_user_id: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
    """canonical mystery-v1 게임만 생성한다."""

    owner = user_id_header(x_user_id)
    payload = _validate_body(CreateGameRequest, await request.json())
    key = idempotency_header(idempotency_key)
    # 동기 DB 대기가 같은 앱의 MCP context 접수·응답을 막지 않도록 분리한다.
    # 요청 식별자와 본문은 스레드 작업을 시작하기 전에 검증한다.
    data, replayed = await asyncio.to_thread(game_runtime(request).create, owner, payload, key)
    return api_success_response(request, data, status_code=201, replayed=replayed)


@router.get("")
async def list_games(
    request: Request,
    x_user_id: str | None = Header(default=None),
    status: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> JSONResponse:
    """현재 UUID가 소유한 canonical 게임만 목록으로 반환한다."""

    owner = user_id_header(x_user_id)
    if status is not None and status not in {"IN_PROGRESS", "SAVED", "COMPLETED", "FAILED"}:
        raise ApiError(status_code=422, code="INVALID_REQUEST", message="status 값이 올바르지 않습니다.")
    del cursor
    items = await asyncio.to_thread(game_runtime(request).list_games, owner, status=status, limit=limit)
    return api_success_response(request, {"items": items, "next_cursor": None})


@router.get("/{game_id}")
async def get_game(request: Request, game_id: UUID, x_user_id: str | None = Header(default=None)) -> JSONResponse:
    """canonical snapshot만 반환하고 legacy 게임으로 fallback하지 않는다."""

    owner = user_id_header(x_user_id)
    data = await asyncio.to_thread(game_runtime(request).snapshot, owner, game_id)
    return api_success_response(request, data)


@router.get("/{game_id}/special-roles")
async def special_roles(
    request: Request, game_id: str, x_user_id: str | None = Header(default=None),
) -> JSONResponse:
    """본인 전용 조회를 공통 권위 검증에 위임하고 입력 오류까지 캐시 저장을 막는다."""

    try:
        owner = user_id_header(x_user_id)
        try:
            parsed_game_id = UUID(game_id)
        except ValueError:
            raise ApiError(status_code=422, code="INVALID_REQUEST", message="게임 ID는 UUID 형식이어야 합니다.") from None
        if request.query_params or await request.body():
            raise ApiError(status_code=422, code="INVALID_REQUEST", message="조회 형식이 올바르지 않습니다.")
        data = await asyncio.to_thread(game_runtime(request).special_roles, owner, parsed_game_id)
        response = api_success_response(request, data)
    except ApiError as error:
        response = api_error_response(request, error)
    except Exception:
        # 예상 밖의 adapter 오류에도 저장소 원문이나 비공개 역할이 응답에 섞이지 않게 한다.
        response = api_error_response(request, ApiError(
            status_code=503, code="DEPENDENCY_UNAVAILABLE",
            message="능력 정보를 조회할 수 없습니다.", retryable=True,
        ))
    response.headers["Cache-Control"] = "no-store"
    return response


@router.delete("/{game_id}")
async def delete_game(
    request: Request,
    game_id: UUID,
    expected_state_version: int = Query(..., ge=1),
    x_user_id: str | None = Header(default=None),
) -> JSONResponse:
    """사용자가 확인한 버전의 소유 게임 하나만 삭제하도록 업무 서비스에 위임한다."""

    owner = user_id_header(x_user_id)
    data = await asyncio.to_thread(
        game_runtime(request).delete_game, owner, game_id,
        expected_state_version=expected_state_version,
    )
    return api_success_response(request, data)


@router.get("/{game_id}/vote-insights")
async def vote_insights(
    request: Request,
    game_id: UUID,
    window_id: UUID = Query(...),
    scope: Literal["current_discussion", "game"] = Query(default="current_discussion"),
    x_user_id: str | None = Header(default=None),
) -> JSONResponse:
    """앱에 주입된 읽기 서비스의 동기 조회를 이벤트 루프 밖에서 수행한다."""
    owner = user_id_header(x_user_id)
    service = request.app.state.vote_insight_service
    data = await asyncio.to_thread(
        service.get, owner, game_id, window_id=window_id, scope=scope,
        analysis_available=not getattr(request.app.state, "speech_analysis_start_failed", False),
    )
    return api_success_response(request, data)


@router.post("/{game_id}/commands")
async def command(
    request: Request,
    game_id: UUID,
    x_user_id: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
    """정본 command type만 검증하고 Engine-backed service에 위임한다."""

    payload = _validate_body(GameCommandRequest, await request.json())
    owner = user_id_header(x_user_id)
    key = idempotency_header(idempotency_key)
    data, replayed = await asyncio.to_thread(game_runtime(request).command, owner, game_id, payload, key)
    return api_success_response(request, data, replayed=replayed)


@router.get("/{game_id}/sync")
async def sync_game(
    request: Request,
    game_id: UUID,
    after_state_version: int = Query(..., ge=0),
    after_sequence: int = Query(..., ge=0),
    x_user_id: str | None = Header(default=None),
) -> JSONResponse:
    """polling과 SSE가 공유하는 canonical operations envelope를 반환한다."""

    owner = user_id_header(x_user_id)
    data = await asyncio.to_thread(
        game_runtime(request).sync, owner, game_id,
        after_state_version=after_state_version, after_sequence=after_sequence,
    )
    return api_success_response(request, data)


@router.get("/{game_id}/events")
async def events(
    request: Request,
    game_id: UUID,
    x_user_id: str | None = Header(default=None),
    last_event_id: int = Header(default=0, alias="Last-Event-ID"),
) -> StreamingResponse:
    """연결을 유지하며 변경된 canonical sync batch만 SSE로 전달한다.

    현재 runtime은 동기 PostgreSQL transaction을 사용하므로 stream loop의 DB 조회는
    별도 thread에서 수행한다. 변경 없는 cursor 응답은 전송하지 않아 브라우저가
    Streamlit rerun을 발생시키지 않으며, heartbeat만 연결 생존 확인용으로 보낸다.
    """

    principal_id = user_id_header(x_user_id)
    initial = await asyncio.to_thread(
        game_runtime(request).sync,
        principal_id,
        game_id,
        after_state_version=0,
        after_sequence=max(last_event_id, 0),
    )

    async def stream():
        """초기 batch 이후 cursor가 전진한 변경분만 push하고 연결을 유지한다."""

        cursor_state_version = 0
        cursor_sequence = max(last_event_id, 0)
        first_read = True
        last_heartbeat = asyncio.get_running_loop().time()

        while not await request.is_disconnected():
            data = initial if first_read else await asyncio.to_thread(
                game_runtime(request).sync,
                principal_id,
                game_id,
                after_state_version=cursor_state_version,
                after_sequence=cursor_sequence,
            )
            mode = data.get("mode") if isinstance(data, dict) else None
            operations = data.get("operations") if isinstance(data, dict) else None
            next_state_version = data.get("state_version", cursor_state_version) if isinstance(data, dict) else cursor_state_version
            next_sequence = data.get("last_sequence", cursor_sequence) if isinstance(data, dict) else cursor_sequence
            changed = mode == "SNAPSHOT" or (isinstance(operations, list) and bool(operations)) or (
                isinstance(next_sequence, int) and next_sequence > cursor_sequence
            )
            if changed:
                yield f"id: {int(next_sequence)}\nevent: game_sync\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                cursor_state_version = int(next_state_version)
                cursor_sequence = int(next_sequence)
                last_heartbeat = asyncio.get_running_loop().time()
            elif asyncio.get_running_loop().time() - last_heartbeat >= 15:
                yield ": heartbeat\n\n"
                last_heartbeat = asyncio.get_running_loop().time()
            first_read = False
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream")


@feedback_router.post("/feedback", status_code=201)
async def create_feedback(
    request: Request,
    x_user_id: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
    """정본 feedback 요청을 처리한다."""

    payload = _validate_body(FeedbackRequest, await request.json())
    owner = user_id_header(x_user_id)
    key = idempotency_header(idempotency_key)
    data, replayed = await asyncio.to_thread(game_runtime(request).feedback, owner, payload, key)
    return api_success_response(request, data, status_code=201, replayed=replayed)


def _validate_body(model: type[BaseModel], body: object) -> BaseModel:
    """함수 내부 Pydantic 검증 오류도 공통 오류 envelope로 변환한다."""

    try:
        return model.model_validate(body)
    except ValidationError as error:
        details = [{"location": list(item["loc"]), "type": item["type"]} for item in error.errors()]
        code = "VALIDATION_ERROR" if model is CreateGameRequest and isinstance(body, dict) and ("mode" in body or "custom_role" in body) else "INVALID_REQUEST"
        raise ApiError(status_code=422, code=code, message="요청 형식이 올바르지 않습니다.", details=details) from error
