"""FastMCP 등록부가 Backend synthetic endpoint를 호출하는 최소 adapter다."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from datetime import UTC, datetime
from time import monotonic
from typing import Any, Protocol
from urllib.parse import quote, urlencode, urlsplit
from uuid import UUID, uuid4

import httpx
from mcp.server.lowlevel.server import request_ctx

from mafia_game.schemas.common import (
    RESOURCE_SCOPE_ORDER,
    WireContractError,
    canonical_uuid,
    integer,
    require_keys,
    string,
)

_DIAGNOSTIC_SCOPE_KEY = "mafia_mcp_diagnostic_correlation"
_DIAGNOSTIC_LOGGER = logging.getLogger("mafia_game.diagnostic")
_OPERATIONS = {
    "runtime.startup", "runtime.library", "mcp.http", "mcp.initialize", "mcp.initialized",
    "mcp.resources.list", "mcp.resources.templates", "mcp.resources.read", "mcp.tools.list",
    "mcp.tools.call", "mcp.prompts.list", "mcp.prompts.get", "mcp.ping", "backend.context",
    "backend.prompt", "backend.action", "backend.special_roles",
} | {f"backend.context.{scope}" for scope in RESOURCE_SCOPE_ORDER}
_ERROR_CLASSES = {
    "MCP_INTERNAL_ERROR", "MCP_CANCELLED", "MCP_RPC_ERROR", "MCP_TOOL_ERROR",
    "MCP_BACKEND_ERROR", "MCP_BACKEND_TIMEOUT", "MCP_BACKEND_CONNECTION_ERROR",
    "MCP_BACKEND_CONNECT_TIMEOUT", "MCP_BACKEND_READ_TIMEOUT", "MCP_BACKEND_WRITE_TIMEOUT",
    "MCP_BACKEND_POOL_TIMEOUT", "MCP_BACKEND_CONNECT_ERROR", "MCP_BACKEND_READ_ERROR",
    "MCP_BACKEND_WRITE_ERROR", "MCP_BACKEND_REMOTE_PROTOCOL_ERROR",
    "MCP_BACKEND_INVALID_JSON", "MCP_BACKEND_INVALID_RESPONSE", "LIBRARY_WARNING",
    "LIBRARY_ERROR", "LIBRARY_INFO",
}


def _safe_error_class(value: Any) -> str | None:
    """고정 오류와 HTTP 상태만 허용해 외부 exception 문자열이 로그에 섞이지 않게 한다."""

    if value is None:
        return None
    if isinstance(value, str) and (
        value in _ERROR_CLASSES or re.fullmatch(r"MCP_(?:BACKEND_)?HTTP_[1-5][0-9]{2}", value)
    ):
        return value
    return "MCP_INTERNAL_ERROR"


def _request_correlation() -> str:
    """SDK가 현재 메시지에 붙인 HTTP scope만 읽고 세션의 이전 추적 문맥은 사용하지 않는다."""

    try:
        value = request_ctx.get().request.scope.get(_DIAGNOSTIC_SCOPE_KEY)
        if isinstance(value, str) and str(UUID(value)) == value:
            return value
    except (LookupError, AttributeError, TypeError, ValueError):
        pass
    return str(uuid4())


class DiagnosticSpan:
    """요청 내용과 식별자를 보관하지 않고 독립 UUID·기간·폐쇄형 결과만 기록한다."""

    def __init__(self, operation: str, *, correlation_id: str | None = None) -> None:
        self.operation = operation if operation in _OPERATIONS else "mcp.http"
        self.request_id = str(uuid4())
        self.correlation_id = correlation_id or _request_correlation()
        self.started_at = monotonic()
        self.error_class: str | None = None

    def emit(self, status: str, *, error_class: str | None = None) -> None:
        """진단 sink 실패는 원래 요청의 반환값·예외·취소 전파를 바꾸지 않는다."""

        record = {
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "operation": self.operation if self.operation in _OPERATIONS else "mcp.http",
            "status": status if status in {"started", "ok", "error", "cancelled"} else "error",
            "duration_ms": round(max(0.0, monotonic() - self.started_at) * 1000, 3),
            "error_class": _safe_error_class(error_class),
        }
        try:
            _DIAGNOSTIC_LOGGER.info(record)
        except Exception:
            pass

    def __enter__(self) -> DiagnosticSpan:
        self.emit("started")
        return self

    def __exit__(self, error_type: Any, error: Any, traceback: Any) -> None:
        if error_type is None:
            self.emit("ok", error_class=self.error_class)
        elif isinstance(error, asyncio.CancelledError):
            self.emit("cancelled", error_class="MCP_CANCELLED")
        else:
            code = self.error_class or (
                error.code if isinstance(error, BackendContextError) else "MCP_INTERNAL_ERROR"
            )
            self.emit("error", error_class=code)


class DiagnosticFormatter(logging.Formatter):
    """프로세스 메타데이터와 여섯 허용 필드만 직렬화하고 SDK 원문·stack은 폐기한다."""

    def format(self, record: logging.LogRecord) -> str:
        data = record.msg if record.name == _DIAGNOSTIC_LOGGER.name else None
        if not isinstance(data, dict) or set(data) != {
            "request_id", "correlation_id", "operation", "status", "duration_ms", "error_class",
        }:
            data = {
                "request_id": str(uuid4()), "correlation_id": _request_correlation(),
                "operation": "runtime.library", "status": "error",
                "duration_ms": 0.0,
                "error_class": "LIBRARY_ERROR" if record.levelno >= logging.ERROR else (
                    "LIBRARY_WARNING" if record.levelno >= logging.WARNING else "LIBRARY_INFO"
                ),
            }
        else:
            # 전용 logger를 직접 호출한 외부 코드도 신뢰하지 않고 필드별로 다시 제한한다.
            data = dict(data)
            for key in ("request_id", "correlation_id"):
                try:
                    if not isinstance(data[key], str) or str(UUID(data[key])) != data[key]:
                        raise ValueError
                except (TypeError, ValueError, AttributeError):
                    data[key] = str(uuid4())
            if not isinstance(data["operation"], str) or data["operation"] not in _OPERATIONS:
                data["operation"] = "runtime.library"
            if data["status"] not in ("started", "ok", "error", "cancelled"):
                data["status"] = "error"
            duration = data["duration_ms"]
            if type(duration) not in (float, int) or not math.isfinite(duration) or duration < 0:
                data["duration_ms"] = 0.0
            data["error_class"] = _safe_error_class(data["error_class"])
        return json.dumps({
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "process": record.process,
            **data,
        }, ensure_ascii=False, separators=(",", ":"))


class DiagnosticHandler(logging.StreamHandler):
    """출력 장치 장애 때 logging의 원문·stack 출력 fallback도 사용하지 않는다."""

    def handleError(self, record: logging.LogRecord) -> None:
        pass


def configure_diagnostic_logging() -> None:
    """독립 MCP 프로세스의 stderr를 안전한 formatter 하나로 모아 원문 우회를 막는다."""

    handler = DiagnosticHandler()
    handler.setFormatter(DiagnosticFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    _DIAGNOSTIC_LOGGER.setLevel(logging.INFO)
    _DIAGNOSTIC_LOGGER.handlers.clear()
    _DIAGNOSTIC_LOGGER.propagate = True
    for name in ("mcp", "httpx", "httpcore", "uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
        logger.setLevel(logging.WARNING)


class BackendContextError(RuntimeError):
    """Backend 실패를 외부 문구 없는 고정 코드로만 전달한다."""

    def __init__(self, code: str = "MCP_BACKEND_ERROR") -> None:
        """응답·URL·예외 원문이 실수로 들어와도 허용된 진단 코드만 남긴다."""

        allowed = {
            "MCP_BACKEND_ERROR", "MCP_BACKEND_TIMEOUT", "MCP_BACKEND_CONNECTION_ERROR",
            "MCP_BACKEND_INVALID_JSON", "MCP_BACKEND_INVALID_RESPONSE",
        }
        self.code = code if isinstance(code, str) and (
            code in allowed or re.fullmatch(r"MCP_BACKEND_HTTP_[1-5][0-9]{2}", code)
        ) else "MCP_BACKEND_ERROR"
        super().__init__(self.code)


class BackendContextClient(Protocol):
    """MCP 등록부가 의존하는 최소 Backend 호출 계약이다."""

    async def read_resource(self, uri: str) -> dict[str, Any]:
        """Backend context를 읽는다."""

    async def get_prompt(self, name: str, arguments: dict[str, str]) -> str:
        """Backend prompt 본문을 읽는다."""

    async def submit_action(self, **payload: str | None) -> dict[str, Any]:
        """행동 payload를 Backend에 전달한다."""

    async def inspect_special_roles(self, *, user_id: str, game_id: str) -> dict[str, Any]:
        """Backend가 소유자에게 허용한 특수 직업만 요청별로 조회한다."""


class MinimalBackendContextClient:
    """인증·세션·게임 판정 없이 Backend HTTP endpoint만 호출한다."""

    def __init__(
        self,
        backend_api_url: str,
        *,
        client: httpx.AsyncClient | None = None,
        allow_insecure_http: bool = False,
    ) -> None:
        parsed = urlsplit(backend_api_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("BACKEND_API_URL must be an absolute HTTP(S) URL")
        if parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError("BACKEND_API_URL must not include query, fragment, or userinfo")
        # Docker 내부망은 Compose가 명시적으로 허용한 경우에만 서비스명 HTTP를
        # 사용한다. 기본값은 기존처럼 loopback·HTTPS만 허용해 임의 endpoint
        # 호출을 막는다.
        private_network_http = parsed.scheme == "http" and allow_insecure_http
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"} and not private_network_http:
            raise ValueError("plain HTTP is allowed only for loopback development")
        self._base_url = backend_api_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=10.0, trust_env=False)
        self._owns_client = client is None

    async def _request(
        self, method: str, path: str, *, body: bytes = b"", operation: str = "backend.context"
    ) -> dict[str, Any]:
        """Backend JSON object 응답만 허용하고 내부 오류 원문은 숨긴다."""

        with DiagnosticSpan(operation) as diagnostic:
            return await self._request_json(method, path, body=body, diagnostic=diagnostic)

    async def _request_json(
        self, method: str, path: str, *, body: bytes, diagnostic: DiagnosticSpan,
    ) -> dict[str, Any]:
        """콜백 단계의 상세 분류는 로그에만 남기고 기존 외부 오류 코드는 유지한다."""

        try:
            response = await self._client.request(
                method,
                f"{self._base_url}{path}",
                content=body,
                headers={"Content-Type": "application/json"},
            )
        except httpx.TimeoutException as error:
            diagnostic.error_class = {
                httpx.ConnectTimeout: "MCP_BACKEND_CONNECT_TIMEOUT",
                httpx.ReadTimeout: "MCP_BACKEND_READ_TIMEOUT",
                httpx.WriteTimeout: "MCP_BACKEND_WRITE_TIMEOUT",
                httpx.PoolTimeout: "MCP_BACKEND_POOL_TIMEOUT",
            }.get(type(error), "MCP_BACKEND_TIMEOUT")
            raise BackendContextError("MCP_BACKEND_TIMEOUT") from None
        except httpx.TransportError as error:
            diagnostic.error_class = {
                httpx.ConnectError: "MCP_BACKEND_CONNECT_ERROR",
                httpx.ReadError: "MCP_BACKEND_READ_ERROR",
                httpx.WriteError: "MCP_BACKEND_WRITE_ERROR",
                httpx.RemoteProtocolError: "MCP_BACKEND_REMOTE_PROTOCOL_ERROR",
            }.get(type(error), "MCP_BACKEND_CONNECTION_ERROR")
            raise BackendContextError("MCP_BACKEND_CONNECTION_ERROR") from None
        except (httpx.HTTPError, ValueError):
            raise BackendContextError from None
        # 상태를 먼저 확인해야 HTML 오류 페이지를 JSON 오류로 잘못 분류하지 않는다.
        # 외부 예외 체인은 숨겨 FastMCP traceback에도 요청 URL과 본문이 남지 않게 한다.
        if response.status_code < 200 or response.status_code >= 300:
            raise BackendContextError(f"MCP_BACKEND_HTTP_{response.status_code}") from None
        try:
            payload = response.json()
        except ValueError:
            raise BackendContextError("MCP_BACKEND_INVALID_JSON") from None
        if not isinstance(payload, dict):
            raise BackendContextError("MCP_BACKEND_INVALID_RESPONSE") from None
        return payload

    async def read_resource(self, uri: str) -> dict[str, Any]:
        """URI 형식·UUID·scope를 검증한 뒤 Backend에 전달하며 projection은 재구성하지 않는다."""

        parts = uri.split("/")
        current = len(parts) == 6 and parts[:4] == ["mafia:", "", "context", "current"]
        scoped = len(parts) == 8 and parts[:4] == ["mafia:", "", "context", "scoped"]
        if not (current or scoped):
            raise BackendContextError
        try:
            parameters = {
                "game_id": canonical_uuid(parts[4]),
                "user_id": canonical_uuid(parts[5]),
            }
            if scoped:
                parameters["player_id"] = canonical_uuid(parts[6])
                if parts[7] not in RESOURCE_SCOPE_ORDER:
                    raise WireContractError
            parameters["scope"] = parts[7] if scoped else "public"
        except WireContractError:
            raise BackendContextError from None
        return await self._request(
            "GET", f"/internal/mcp/context?{urlencode(parameters)}",
            operation=f"backend.context.{parameters['scope']}",
        )

    async def get_prompt(self, name: str, arguments: dict[str, str]) -> str:
        """Prompt 이름을 Backend에 전달하고 문자열 본문만 반환한다."""

        if name != "agent_instruction":
            raise BackendContextError
        # FastMCP의 생략된 선택 인자는 빈 문자열이므로 UUID query에 보내지 않는다.
        # 값이 있는 인자는 그대로 전달해 Backend의 형식 검증을 우회하지 않는다.
        arguments = {
            key: value for key, value in arguments.items()
            if key not in {"game_id", "user_id"} or value != ""
        }
        query = ""
        if arguments:
            query = "?" + "&".join(
                f"{quote(key, safe='-._~')}={quote(value, safe='-._~')}"
                for key, value in arguments.items()
            )
        payload = await self._request(
            "GET", f"/internal/mcp/prompts/{quote(name, safe='-._~')}{query}",
            operation="backend.prompt",
        )
        prompt = payload.get("prompt")
        if not isinstance(prompt, str):
            raise BackendContextError
        return prompt

    async def submit_action(self, **payload: str | None) -> dict[str, Any]:
        """Backend가 명시적으로 승인한 응답만 반환해 HTTP 200과 행동 성공을 구분한다."""

        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        result = await self._request(
            "POST", "/internal/mcp/actions", body=body, operation="backend.action",
        )
        if result.get("accepted") is not True or result.get("error") is not None:
            raise BackendContextError
        return result

    async def inspect_special_roles(self, *, user_id: str, game_id: str) -> dict[str, Any]:
        """소유자 조회를 위임하고 추가 비공개 필드·다른 게임 응답을 폐쇄형 검증으로 막는다."""

        try:
            parameters = {
                "user_id": canonical_uuid(user_id),
                "game_id": canonical_uuid(game_id),
            }
        except WireContractError:
            raise BackendContextError from None
        result = await self._request(
            "GET", f"/internal/mcp/special-roles?{urlencode(parameters)}",
            operation="backend.special_roles",
        )
        try:
            require_keys(result, {"game_id", "player_id", "ability_id", "state_version", "roles"})
            if canonical_uuid(result["game_id"]) != game_id:
                raise WireContractError
            actor_id = canonical_uuid(result["player_id"])
            if result["ability_id"] != "intel.special_roles.v1":
                raise WireContractError
            integer(result["state_version"], minimum=1)
            if not isinstance(result["roles"], list):
                raise WireContractError
            # actor는 Backend가 소유 HUMAN으로 확정한다. MCP는 응답의 본인 제외와
            # 중복만 확인하고 직업 소유권·생존·첫 밤 해금 판정을 새로 만들지 않는다.
            seen = {actor_id}
            for item in result["roles"]:
                require_keys(item, {"player_id", "display_name", "role", "alive"})
                player_id = canonical_uuid(item["player_id"])
                if player_id in seen:
                    raise WireContractError
                seen.add(player_id)
                string(item["display_name"])
                if string(item["role"]) not in {"DETECTIVE", "DOCTOR"}:
                    raise WireContractError
                if not isinstance(item["alive"], bool):
                    raise WireContractError
        except WireContractError:
            raise BackendContextError("MCP_BACKEND_INVALID_RESPONSE") from None
        return result

    async def aclose(self) -> None:
        """adapter가 생성한 HTTP client만 닫는다."""

        if self._owns_client:
            await self._client.aclose()
