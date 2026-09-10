"""WU-M2/M3 Mafia Game MCP session·Resource runtime의 composition root다."""

from __future__ import annotations

import asyncio
import json
import os
from uuid import uuid4

from mcp.server.fastmcp import FastMCP

from mafia_game.api.prompts.registry import register_prompts
from mafia_game.api.resources.registry import register_resources
from mafia_game.api.tools.registry import register_tools
from mafia_game.integrations.engine_http import (
    _DIAGNOSTIC_SCOPE_KEY,
    BackendContextClient,
    DiagnosticSpan,
    MinimalBackendContextClient,
    configure_diagnostic_logging,
)


class McpDiagnosticMiddleware:
    """HTTP 200 안의 RPC 실패도 구분하며 payload를 출력하지 않는 ASGI 계측 경계다."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        diagnostic = DiagnosticSpan("mcp.http", correlation_id=str(uuid4()))
        scope[_DIAGNOSTIC_SCOPE_KEY] = diagnostic.correlation_id
        request_body = bytearray()
        response_body = bytearray()
        request_truncated = response_truncated = False
        response_status = 500

        async def measured_receive():
            nonlocal request_truncated
            message = await receive()
            if message["type"] == "http.request" and not request_truncated:
                chunk = message.get("body", b"")
                if len(request_body) + len(chunk) <= 16_384:
                    request_body.extend(chunk)
                else:
                    request_body.clear()
                    request_truncated = True
            return message

        async def measured_send(message):
            nonlocal response_status, response_truncated
            if message["type"] == "http.response.start":
                response_status = message["status"]
            if message["type"] == "http.response.body" and not response_truncated:
                chunk = message.get("body", b"")
                if len(response_body) + len(chunk) <= 65_536:
                    response_body.extend(chunk)
                else:
                    response_body.clear()
                    response_truncated = True
            await send(message)

        diagnostic.emit("started")
        error_class = None
        status = "ok"
        try:
            await self.app(scope, measured_receive, measured_send)
            if not 200 <= response_status < 300:
                status, error_class = "error", f"MCP_HTTP_{response_status}"
            elif not response_truncated:
                body = _diagnostic_json(response_body)
                if "error" in body:
                    status, error_class = "error", "MCP_RPC_ERROR"
                elif isinstance(body.get("result"), dict) and body["result"].get("isError") is True:
                    status, error_class = "error", "MCP_TOOL_ERROR"
        except asyncio.CancelledError:
            status, error_class = "cancelled", "MCP_CANCELLED"
            raise
        except Exception:
            status, error_class = "error", "MCP_INTERNAL_ERROR"
            raise
        finally:
            # ASGI 메시지를 교체하거나 선소비하지 않으며 분류용 복사본도 요청 안에서만 쓴다.
            method = _diagnostic_json(request_body).get("method") if not request_truncated else None
            operations = {
                "initialize": "mcp.initialize", "notifications/initialized": "mcp.initialized",
                "resources/list": "mcp.resources.list",
                "resources/templates/list": "mcp.resources.templates",
                "resources/read": "mcp.resources.read", "tools/list": "mcp.tools.list",
                "tools/call": "mcp.tools.call", "prompts/list": "mcp.prompts.list",
                "prompts/get": "mcp.prompts.get", "ping": "mcp.ping",
            }
            diagnostic.operation = operations.get(method, "mcp.http") if isinstance(method, str) else "mcp.http"
            request_body.clear()
            response_body.clear()
            diagnostic.emit(status, error_class=error_class)


def _diagnostic_json(body: bytearray) -> dict:
    """불완전·대형·잘못된 JSON은 분류를 생략하며 실제 MCP 처리 결과는 건드리지 않는다."""

    try:
        value = json.loads(body)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return {}
    return value if isinstance(value, dict) else {}


def create_fastmcp_server(backend: BackendContextClient | None = None) -> FastMCP:
    """FastMCP 운영 객체를 만들고 주입된 Backend adapter의 등록부를 조립한다.

    FastMCP가 protocol session을 관리하도록 위임하고, 프로젝트 내부에는 별도의
    bootstrap·session 상태 머신을 두지 않는다. 게임 규칙과 상태 변경은 Backend에
    남겨 MCP 등록부가 자체 판단을 수행하지 않도록 한다.
    """

    server = FastMCP(
        "ai-mafia-mcp",
        json_response=True,
        stateless_http=False,
        streamable_http_path="/mcp",
    )
    if backend is not None:
        register_fastmcp_components(server, backend)
    return server


def register_fastmcp_components(server: FastMCP, backend: BackendContextClient) -> None:
    """컨텍스트 Resource·Prompt 등록을 한 composition root에서 조립한다."""

    register_resources(server, backend)
    register_tools(server, backend)
    register_prompts(server, backend)


def create_minimal_fastmcp_app(backend: BackendContextClient):
    """기존 인증 runtime 없이 FastMCP 등록부만 노출하는 최소 ASGI 앱을 만든다."""

    app = create_fastmcp_server(backend).streamable_http_app()
    app.add_middleware(McpDiagnosticMiddleware)
    return app


def run() -> None:
    """최소 FastMCP 등록부를 loopback 개발 서버로 실행한다."""

    import uvicorn

    configure_diagnostic_logging()
    backend_url = os.environ.get("BACKEND_API_URL", "http://127.0.0.1:8000")
    host = os.environ.get("MCP_LISTEN_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_LISTEN_PORT", "8100"))
    backend = MinimalBackendContextClient(backend_url)
    DiagnosticSpan("runtime.startup").emit("ok")
    # Uvicorn이 formatter를 다시 덮어쓰거나 요청 URL을 별도 access logger로 내보내지 않는다.
    uvicorn.run(
        create_minimal_fastmcp_app(backend), host=host, port=port,
        log_config=None, access_log=False,
    )


if __name__ == "__main__":
    run()
