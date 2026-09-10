"""FastMCP가 실제 게임 runtime을 호출하는 Backend 내부 adapter."""

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from backend.app.core.errors import ApiError
from backend.app.schemas.command_schema import GameCommandRequest
from backend.app.services.game.actor_context import read_actor_context
from backend.app.services.game.game_read_service import read_special_roles

router = APIRouter(prefix="/internal/mcp", tags=["mcp"])


class McpActionRequest(BaseModel):
    """MCP Tool 입력을 공개 GameCommand 입력으로 변환하기 위한 폐쇄형 schema."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    action: Literal["PASS", "SPEAK", "NIGHT_ACTION", "VOTE"]
    user_id: UUID
    game_id: UUID
    player_id: UUID | None = None
    expected_state_version: int = Field(ge=1)
    window_id: UUID
    target_player_id: UUID | None = None
    message: str | None = Field(default=None, max_length=200)
    idempotency_key: UUID
    ability_id: Literal["vote.triple.v1"] | None = None

    @model_validator(mode="after")
    def validate_custom_vote(self) -> "McpActionRequest":
        """새 능력은 소유 HUMAN의 투표에만 전달하고 기존 AI 경로와 분리한다."""

        if self.ability_id is not None and (
            self.action != "VOTE" or self.player_id is not None or self.message is not None
        ):
            raise ValueError("투표 능력은 사용자 본인의 투표에만 사용할 수 있습니다.")
        return self


@router.get("/special-roles")
def inspect_special_roles(
    request: Request,
    response: Response,
    game_id: UUID = Query(...),
    user_id: UUID = Query(...),
) -> dict[str, Any]:
    """사용자 소유 게임의 해금된 특수 직업 정보만 캐시 없이 반환한다."""

    if set(request.query_params) - {"game_id", "user_id"}:
        raise ApiError(status_code=422, code="INVALID_REQUEST", message="조회 형식이 올바르지 않습니다.")
    response.headers["Cache-Control"] = "no-store"
    return read_special_roles(
        request.app.state.game_runtime._read, owner_user_id=user_id, game_id=game_id,
    )


@router.get("/context")
def read_context(
    request: Request,
    game_id: UUID = Query(...),
    user_id: UUID = Query(...),
    player_id: UUID | None = Query(default=None),
    scope: str = Query(default="public"),
) -> dict[str, Any]:
    """같은 게임의 AI actor와 scope를 고정해 인간 개인 정보 없이 8.2 envelope를 반환한다."""

    runtime = request.app.state.game_runtime
    return read_actor_context(
        runtime._read, owner_user_id=user_id, game_id=game_id,
        player_id=player_id, scope=scope, agents=runtime._agent_repository,
    )


@router.get("/prompts/{name}")
def read_prompt(
    name: str,
    game_id: UUID | None = Query(default=None),
    user_id: UUID | None = Query(default=None),
) -> dict[str, str]:
    """Agent가 실제 게임 command를 만들 때 지켜야 할 고정 지침을 반환한다."""

    if name != "agent_instruction":
        raise ApiError(
            status_code=404,
            code="PROMPT_NOT_FOUND",
            message="요청한 Prompt를 찾을 수 없습니다.",
        )
    del game_id, user_id
    return {
        "prompt": (
            "Backend가 제공한 게임 context만 사용하고, 하나의 허용된 proposal만 반환하세요. "
            "게임 상태 변경은 Backend command 검증을 통해서만 수행됩니다."
        )
    }


@router.post("/actions")
def submit_action(request: Request, payload: McpActionRequest) -> dict[str, Any]:
    """MCP action을 기존 PostgreSQL GameCommand service에 위임한다."""

    if payload.player_id is not None and payload.action == "PASS":
        result, replayed = request.app.state.game_runtime.agent_pass(
            payload.user_id,
            payload.game_id,
            payload.player_id,
            expected_state_version=payload.expected_state_version,
            window_id=payload.window_id,
        )
        return {
            "status": "accepted",
            "source": "backend",
            "accepted": True,
            "replayed": replayed,
            "result": result,
        }
    if payload.player_id is not None and payload.action == "SPEAK" and payload.message is not None:
        result, replayed = request.app.state.game_runtime.agent_speak(
            payload.user_id, payload.game_id, payload.player_id, payload.message,
            expected_state_version=payload.expected_state_version, window_id=payload.window_id,
        )
        return {"status": "accepted", "source": "backend", "accepted": True, "replayed": replayed, "result": result}
    if payload.player_id is not None and payload.action in {"NIGHT_ACTION", "VOTE"}:
        command_type = "SUBMIT_NIGHT_ACTION" if payload.action == "NIGHT_ACTION" else "SUBMIT_VOTE"
        command = GameCommandRequest(
            type=command_type,
            expected_state_version=payload.expected_state_version,
            window_id=payload.window_id,
            target_player_id=payload.target_player_id,
        )
        result, replayed = request.app.state.game_runtime.agent_action(
            payload.user_id, payload.game_id, payload.player_id, command, payload.idempotency_key
        )
        return {"status": "accepted", "source": "backend", "accepted": True, "replayed": replayed, "result": result}

    command_type = {
        "PASS": "PASS",
        "SPEAK": "SPEAK",
        "NIGHT_ACTION": "SUBMIT_NIGHT_ACTION",
        "VOTE": "SUBMIT_VOTE",
    }[payload.action]
    try:
        command = GameCommandRequest(
            type=command_type,
            expected_state_version=payload.expected_state_version,
            window_id=payload.window_id,
            target_player_id=payload.target_player_id,
            message=payload.message,
            ability_id=payload.ability_id,
        )
    except ValidationError as error:
        raise ApiError(
            status_code=422,
            code="INVALID_REQUEST",
            message="MCP action 형식이 올바르지 않습니다.",
        ) from error

    result, replayed = request.app.state.game_runtime.command(
        payload.user_id,
        payload.game_id,
        command,
        payload.idempotency_key,
    )
    return {
        "status": "accepted",
        "source": "backend",
        "accepted": True,
        "replayed": replayed,
        "result": result,
    }
