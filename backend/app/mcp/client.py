"""Agent가 FastMCP를 통해 게임 context와 action을 호출하는 client."""

from __future__ import annotations

import json
import re
from typing import Any, Protocol
from uuid import UUID, uuid4
from datetime import datetime

import httpx


class McpContextError(RuntimeError):
    """외부 응답 원문 없이 MCP 장애 경계만 호출자에게 전달한다."""

    def __init__(self, code: str, *, http_status: int | None = None) -> None:
        """외부 자유 문자열이 진단 로그로 전파되지 않도록 분류도 재검증한다."""

        allowed = {
            "MCP_TIMEOUT", "MCP_CONNECTION_ERROR", "MCP_HTTP_ERROR", "MCP_INVALID_JSON",
            "MCP_RPC_ERROR", "MCP_CONTEXT_CONTRACT", "MCP_CONTEXT_STALE", "MCP_INSTRUCTION_MISSING",
            "MCP_BACKEND_ERROR", "MCP_BACKEND_TIMEOUT", "MCP_BACKEND_CONNECTION_ERROR",
            "MCP_BACKEND_INVALID_JSON", "MCP_BACKEND_INVALID_RESPONSE",
        }
        self.code = code if isinstance(code, str) and (
            code in allowed or re.fullmatch(r"MCP_BACKEND_HTTP_[1-5][0-9]{2}", code)
        ) else "MCP_UNKNOWN_ERROR"
        self.http_status = http_status if type(http_status) is int and 100 <= http_status <= 599 else None
        super().__init__(f"FastMCP context contract/request failed: {self.code}")


def _backend_error(message: Any) -> McpContextError:
    """FastMCP가 감싼 Backend 오류에서 허용된 마지막 고정 코드만 추출한다."""

    match = re.search(
        r"(?:^|: )(MCP_BACKEND_(?:HTTP_[1-5][0-9]{2}|TIMEOUT|CONNECTION_ERROR|INVALID_JSON|INVALID_RESPONSE|ERROR))\Z",
        message,
    ) if isinstance(message, str) else None
    code = match.group(1) if match else "MCP_RPC_ERROR"
    status = int(code.rsplit("_", 1)[1]) if code.startswith("MCP_BACKEND_HTTP_") else None
    return McpContextError(code, http_status=status)


class AgentContextClient(Protocol):
    """Agent 작업에 필요한 최소 Context 조회 계약이다."""

    async def get_context(self, *, capability: str, scope: str) -> dict[str, Any]:
        """현재 작업에 허용된 Context를 반환한다."""

    async def close(self) -> None:
        """작업 종료 시 provider 자원을 닫는다."""


class FakeAgentContextClient:
    """외부 MCP와 네트워크 없이 Agent 흐름을 검증하는 fake provider다."""

    def __init__(
        self,
        context: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.context = context or {}
        self.error = error
        self.calls: list[tuple[str, str]] = []
        self.closed = False

    async def get_context(self, *, capability: str, scope: str) -> dict[str, Any]:
        """capability 원문은 저장하지 않고 호출 사실과 scope만 기록한다."""

        self.calls.append(("<opaque>", scope))
        if self.error is not None:
            raise self.error
        return dict(self.context)

    async def close(self) -> None:
        """fake provider의 종료 상태만 기록한다."""

        self.closed = True


class FastMcpGameContextClient:
    """FastMCP Streamable HTTP를 호출하는 실제 게임 context adapter.

    MCP session은 한 Agent turn 동안만 유지한다. Backend는 MCP protocol을 우회해
    내부 endpoint를 직접 호출하지 않으며, action 검증과 상태 변경은 MCP 뒤의
    Backend GameEngine에 남긴다.
    """

    def __init__(
        self,
        base_url: str,
        *,
        user_id: UUID,
        game_id: UUID,
        player_id: UUID | None = None,
        phase: str | None = None,
        state_version: int | None = None,
        window_id: UUID | None = None,
        client: httpx.AsyncClient | None = None,
        allow_vote_submission_version: bool = False,
    ) -> None:
        """loopback FastMCP endpoint와 현재 게임·사용자를 고정한다."""

        self._base_url = base_url.rstrip("/")
        self._user_id = user_id
        self._game_id = game_id
        self._player_id = player_id
        self._phase = phase
        self._state_version = state_version
        self._vote_base_version = state_version if allow_vote_submission_version else None
        self._window_id = window_id
        self._client = client or httpx.AsyncClient(timeout=15.0, trust_env=False)
        self._owns_client = client is None
        self._session_id: str | None = None
        self._request_id = 0
        self._last_context: dict[str, Any] | None = None
        self._initialized = False

    async def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """FastMCP JSON-RPC 응답을 확인하고 result object만 반환한다."""

        self._request_id += 1
        headers = {"Accept": "application/json, text/event-stream"}
        if self._session_id is not None:
            headers["Mcp-Session-Id"] = self._session_id
        response = await self._post(
            headers=headers,
            body={"jsonrpc": "2.0", "id": self._request_id, "method": method, "params": params},
        )
        if method == "initialize":
            self._session_id = response.headers.get("mcp-session-id")
        try:
            body = _json_object(response.text)
        except ValueError:
            raise McpContextError("MCP_INVALID_JSON") from None
        if body.get("jsonrpc") != "2.0" or type(body.get("id")) is not int or body["id"] != self._request_id:
            raise McpContextError("MCP_RPC_ERROR")
        if "error" in body:
            error = body["error"]
            raise _backend_error(error.get("message") if isinstance(error, dict) else None)
        if not isinstance(body.get("result"), dict):
            raise McpContextError("MCP_RPC_ERROR")
        return body["result"]

    async def _post(self, *, headers: dict[str, str], body: dict[str, Any]) -> httpx.Response:
        """초기화 알림도 HTTP 성공을 확인하고 연결 예외의 URL·본문은 숨긴다."""

        try:
            response = await self._client.post(f"{self._base_url}/mcp", headers=headers, json=body)
            response.raise_for_status()
        except httpx.TimeoutException:
            raise McpContextError("MCP_TIMEOUT") from None
        except httpx.HTTPStatusError as error:
            raise McpContextError("MCP_HTTP_ERROR", http_status=error.response.status_code) from None
        except httpx.TransportError:
            raise McpContextError("MCP_CONNECTION_ERROR") from None
        return response

    async def _initialize(self) -> None:
        """MCP protocol session을 한 번만 초기화한다."""

        if self._initialized:
            return
        result = await self._rpc(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "ai-mafia-agent", "version": "1.0"},
            },
        )
        del result
        await self._post(
            headers={
                "Accept": "application/json, text/event-stream",
                "Mcp-Session-Id": self._session_id or "",
            },
            body={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        self._initialized = True

    async def get_context(self, *, capability: str, scope: str) -> dict[str, Any]:
        """실제 Resource를 읽어 scope별 context를 반환한다."""

        del capability
        allowed = {"public"} if self._player_id is None else {"public", "me", "turn", "persona"}
        if scope not in allowed:
            raise ValueError("MCP context scope is not allowed")
        await self._initialize()
        uri = (f"mafia://context/current/{self._game_id}/{self._user_id}" if self._player_id is None
               else f"mafia://context/scoped/{self._game_id}/{self._user_id}/{self._player_id}/{scope}")
        result = await self._rpc(
            "resources/read",
            {"uri": uri},
        )
        contents = result.get("contents", [])
        if not isinstance(contents, list) or len(contents) != 1 or not isinstance(contents[0], dict) or contents[0].get("uri") != uri or contents[0].get("mimeType") != "application/json" or not isinstance(contents[0].get("text"), str):
            raise McpContextError("MCP_CONTEXT_CONTRACT")
        try:
            payload = _json_object(contents[0]["text"])
        except ValueError:
            raise McpContextError("MCP_INVALID_JSON") from None
        self._validate_context(payload, scope)
        if scope == "turn":
            self._last_context = payload
        return payload

    def _validate_context(self, payload: dict[str, Any], scope: str) -> None:
        """게임·actor·phase·버전·window binding과 폐쇄형 envelope를 재검증한다.

        최초 응답의 binding은 이후 scope에도 고정한다. runtime이 제공한 기대값이
        있으면 최초 응답부터 비교하므로 다른 차례의 context를 조용히 재사용하지 않는다.
        병렬 투표 worker만 같은 window에서 인간 첫 표의 한 버전 증가를 허용한다.
        그 증가 원인은 job 완료·행동 저장 시 Backend가 제출 원장으로 다시 검증한다.
        """

        keys = {"context_version", "game_id", "subject_type", "subject_id", "phase", "state_version", "window_id", "scope", "data"}
        data_keys = {
            "public": {"game", "scenario", "players", "public_events"},
            "me": {"player_id", "role", "alive", "alibi", "observation", "private_events"},
            "turn": {"window_id", "window_kind", "cycle", "opened_state_version", "server_time", "deadline_at", "turn_player_id", "allowed_tools", "valid_targets"},
            "persona": {"persona_id", "version", "display_name", "speech_style", "backstory", "parameters"},
        }
        try:
            if set(payload) != keys or type(payload["context_version"]) is not int or payload["context_version"] != 1:
                raise ValueError
            if payload["game_id"] != str(self._game_id) or payload["subject_id"] != str(self._player_id or self._game_id) or payload["subject_type"] != ("AI_PLAYER" if self._player_id else "GM") or payload["scope"] != scope:
                raise ValueError
            phases = {"DAY_DISCUSSION": "SPEECH", "FINAL_DISCUSSION": "SPEECH", "NIGHT_ACTION": "NIGHT", "DAY_VOTE": "VOTE", "REVOTE": "REVOTE", "FINAL_ACCUSATION": "FINAL_VOTE"}
            if payload["phase"] not in phases:
                raise ValueError
            if self._phase is not None and payload["phase"] != self._phase:
                raise McpContextError("MCP_CONTEXT_STALE")
            version = payload["state_version"]
            window = UUID(payload["window_id"])
            vote_increment = (
                self._vote_base_version is not None
                and payload["phase"] in {"DAY_VOTE", "REVOTE", "FINAL_ACCUSATION"}
                and version == self._vote_base_version + 1
                and self._state_version == self._vote_base_version
            )
            if str(window) != payload["window_id"] or type(version) is not int or version < 1:
                raise ValueError
            if ((self._state_version is not None and version != self._state_version and not vote_increment)
                    or (self._window_id is not None and window != self._window_id)):
                raise McpContextError("MCP_CONTEXT_STALE")
            data = payload["data"]
            # 서사 필드의 유무는 호환하되 MCP 소유 지침은 아래에서 필수로 확인한다.
            allowed_shapes = [data_keys[scope]]
            if scope == "public":
                allowed_shapes.append(data_keys[scope] | {"rules"})
            elif scope == "me":
                allowed_shapes.append(data_keys[scope] - {"alibi", "observation"})
            if scope in {"me", "persona"}:
                # 역할 전략을 모르는 구형 MCP와 조합하면 조용히 무전략 행동을 만들지
                # 않고 기존 MCP 장애 경로로 종료한다. 새 MCP를 먼저 배포해야 한다.
                allowed_shapes = [shape | {"agent_instruction"} for shape in allowed_shapes]
                if isinstance(data, dict) and "agent_instruction" not in data:
                    raise McpContextError("MCP_INSTRUCTION_MISSING")
            if not isinstance(data, dict) or set(data) not in allowed_shapes:
                raise ValueError
            if scope in {"me", "persona"}:
                instruction = data["agent_instruction"]
                if (not isinstance(instruction, str) or len(instruction) > 2400
                        or (scope == "me" and not instruction.strip())):
                    raise ValueError
            if "rules" in data and (not isinstance(data["rules"], list) or not data["rules"]
                                    or any(not isinstance(rule, str) or not rule.strip() for rule in data["rules"])):
                raise ValueError
            if scope == "public":
                game = data["game"]
                if game["game_id"] != str(self._game_id) or game["phase"] != payload["phase"] or type(game["state_version"]) is not int or game["state_version"] != version or "agent_activity" in game:
                    raise ValueError
            if scope == "me" and data["player_id"] != str(self._player_id):
                raise ValueError
            if scope == "turn":
                kind = phases[payload["phase"]]
                tools = {"SPEECH": ["propose_speech", "propose_pass"], "NIGHT": ["propose_night_action"]}.get(kind, ["propose_vote"])
                if payload["phase"] == "DAY_DISCUSSION" and data["allowed_tools"] == ["propose_speech"]:
                    tools = ["propose_speech"]
                if data["window_id"] != str(window) or data["window_kind"] != kind or data["allowed_tools"] != tools or type(data["opened_state_version"]) is not int or not 1 <= data["opened_state_version"] <= version or type(data["cycle"]) is not int or data["cycle"] not in {1, 2}:
                    raise ValueError
                targets = data["valid_targets"]
                if not isinstance(targets, list) or len(targets) > 8:
                    raise ValueError
                ids = []
                for target in targets:
                    if not isinstance(target, dict) or set(target) != {"player_id", "display_name"} or str(UUID(target["player_id"])) != target["player_id"] or not isinstance(target["display_name"], str) or not 1 <= len(target["display_name"]) <= 40:
                        raise ValueError
                    ids.append(target["player_id"])
                if len(set(ids)) != len(ids):
                    raise ValueError
                server = _utc_time(data["server_time"])
                if kind == "SPEECH":
                    if targets or (data["deadline_at"] is not None and _utc_time(data["deadline_at"]) <= server) or data["turn_player_id"] != str(self._player_id):
                        raise ValueError
                elif not targets or data["turn_player_id"] is not None or _utc_time(data["deadline_at"]) <= server:
                    raise ValueError
            self._phase, self._state_version, self._window_id = payload["phase"], version, window
        except (KeyError, TypeError, ValueError, AttributeError):
            raise McpContextError("MCP_CONTEXT_CONTRACT") from None

    async def read_context(self, *, game_id: UUID, player_id: UUID) -> dict[str, Any]:
        """게임 Agent adapter가 사용하는 실제 Resource 조회 포트다."""

        if game_id != self._game_id:
            raise ValueError("game_id does not match the MCP client scope")
        if player_id == self._user_id:
            raise ValueError("MCP owner and AI player identifiers must be distinct")
        if self._player_id is not None and self._player_id != player_id:
            raise ValueError("MCP actor does not match the client scope")
        self._player_id = player_id
        return {scope: await self.get_context(capability="", scope=scope)
                for scope in ("public", "me", "turn", "persona")}

    async def submit_action(
        self,
        *,
        game_id: UUID,
        player_id: UUID,
        action: dict[str, Any],
    ) -> dict[str, Any]:
        """정규화된 Agent proposal을 FastMCP Tool로 전달한다."""

        if game_id != self._game_id or player_id != self._player_id or self._last_context is None:
            raise ValueError("MCP action requires a previously read game context")
        action_type = action.get("type")
        allowed = {"SPEAK": "propose_speech", "PASS": "propose_pass", "NIGHT_ACTION": "propose_night_action", "VOTE": "propose_vote"}
        if action_type not in allowed or allowed[action_type] not in self._last_context["data"]["allowed_tools"]:
            raise ValueError("MCP action is not allowed in this window")
        result = await self._rpc(
            "tools/call",
            {
                "name": "submit_action",
                "arguments": {
                    "action": action_type,
                    "user_id": str(self._user_id),
                    "game_id": str(self._game_id),
                    "player_id": str(player_id),
                    "expected_state_version": self._state_version,
                    "window_id": str(self._window_id),
                    "idempotency_key": str(uuid4()),
                    "target_player_id": action.get("target_player_id"),
                    "message": action.get("message"),
                },
            },
        )
        contents = result.get("content", [])
        if result.get("isError", False) is not False or not isinstance(contents, list) or len(contents) != 1 or not isinstance(contents[0], dict) or not isinstance(contents[0].get("text"), str):
            raise RuntimeError("FastMCP action response is invalid")
        payload = _json_object(contents[0]["text"])
        receipt = payload.get("result")
        if set(payload) != {"status", "source", "accepted", "replayed", "result"} or payload.get("status") != "accepted" or payload.get("source") != "backend" or payload.get("accepted") is not True or type(payload.get("replayed")) is not bool or not isinstance(receipt, dict):
            raise RuntimeError("FastMCP action was not accepted")
        expected_command = {"NIGHT_ACTION": "SUBMIT_NIGHT_ACTION", "VOTE": "SUBMIT_VOTE"}.get(action_type, action_type)
        result_version = receipt.get("result_state_version")
        valid_result_version = type(result_version) is int and (
            result_version > self._state_version
            or (action_type == "VOTE" and result_version == self._state_version)
        )
        if receipt.get("command_type") != expected_command or type(receipt.get("accepted_state_version")) is not int or receipt["accepted_state_version"] != self._state_version or not valid_result_version or receipt.get("sync_url") != f"/api/v1/games/{self._game_id}/sync":
            raise RuntimeError("FastMCP action receipt is invalid")
        return payload

    async def close(self) -> None:
        """Agent turn에 사용한 HTTP client를 닫는다."""

        if self._owns_client:
            await self._client.aclose()


def _json_object(raw: str) -> dict[str, Any]:
    """중복 JSON member와 비유한 숫자를 거부해 마지막 값 덮어쓰기를 막는다."""

    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("MCP JSON contains duplicate fields")
            value[key] = item
        return value

    def invalid_constant(value):
        raise ValueError("MCP JSON contains a non-finite number")

    result = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)
    if not isinstance(result, dict):
        raise ValueError("MCP JSON must be an object")
    return result


def _utc_time(value: str) -> datetime:
    """UTC의 Z·+00:00 표기만 허용하고 느슨한 ISO 형식이나 다른 offset은 거부한다.

    Backend projection의 isoformat() 출력도 받되 timezone 없는 시각이나
    중복 offset을 보정하지 않아 서버·deadline 비교의 UTC 경계를 유지한다.
    """

    if not isinstance(value, str) or re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|\+00:00)",
        value,
    ) is None:
        raise ValueError("MCP context time must be UTC")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
