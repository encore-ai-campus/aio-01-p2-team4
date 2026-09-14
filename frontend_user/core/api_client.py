"""UUID 기반 공개 Backend API client."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

HttpTransport = Callable[[Request, float], tuple[int, bytes]]


class ApiClientConfigurationError(RuntimeError):
    """Backend 주소가 안전하지 않거나 설정되지 않은 경우의 오류."""


class ApiResponseError(RuntimeError):
    """Backend의 고정 오류 code와 HTTP status만 전달하는 오류."""

    def __init__(self, *, status_code: int, code: str, request_id: str | None = None) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.request_id = request_id


class ApiUnavailableError(ApiResponseError):
    """Backend 연결 실패 또는 잘못된 응답 오류."""


@dataclass(frozen=True, slots=True)
class BackendApiConfig:
    """Front 서버가 사용할 Backend 주소와 요청 timeout."""

    api_url: str
    timeout_seconds: float = 5.0
    allow_insecure_http: bool = False

    def __post_init__(self) -> None:
        """운영 HTTPS와 loopback 개발 HTTP만 허용해 임의 endpoint 호출을 막는다."""

        candidate = self.api_url.strip().rstrip("/")
        try:
            parsed = urlsplit(candidate)
            port = parsed.port
        except ValueError as exc:
            raise ApiClientConfigurationError("Backend API URL이 올바르지 않습니다.") from exc
        local_http = parsed.scheme == "http" and parsed.hostname in {
            "localhost", "127.0.0.1", "::1",
        }
        # Docker 내부망은 Front 컨테이너와 Backend 컨테이너 사이에서만 사용한다.
        # 기본값은 계속 loopback·HTTPS만 허용하며, Compose가 명시적으로 주입한
        # allowlist 플래그가 있을 때만 서비스명 기반 HTTP를 허용한다.
        private_network_http = parsed.scheme == "http" and self.allow_insecure_http
        if (
            not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in {"", "/"}
                or (parsed.scheme != "https" and not (local_http or private_network_http))
                or (port is not None and not 1 <= port <= 65_535)):
            raise ApiClientConfigurationError("Backend API URL이 안전하지 않습니다.")
        if not 0 < self.timeout_seconds <= 30:
            raise ApiClientConfigurationError("Backend API timeout이 올바르지 않습니다.")
        object.__setattr__(self, "api_url", candidate)


class ApiClient:
    """공개 사용자 API를 호출하는 UUID-only client."""

    # Backend는 일반 사용자 요청에서 UUID 식별자와 요청 추적 ID만 읽는다.
    # UUID는 인증 자격증명이 아니므로 Backend가 최초 쓰기 요청에서 사용자 행을
    # 멱등 생성하고 게임 소유권은 owner_user_id와 비교한다.

    def __init__(self, *, user_id: UUID | str, api_url: str | None = None,
                 transport: HttpTransport | None = None,
                 request_id_factory: Callable[[], UUID] = uuid4) -> None:
        self.user_id = UUID(str(user_id))
        if self.user_id.version != 4:
            raise ValueError("사용자 ID는 UUID v4여야 합니다.")
        self.config = BackendApiConfig(
            api_url=api_url or os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000"),
            allow_insecure_http=(
                os.getenv("BACKEND_API_ALLOW_INSECURE_HTTP", "false").lower() == "true"
            ),
        )
        self._transport = transport or _send
        self._request_id_factory = request_id_factory

    def get_health(self) -> dict[str, Any]:
        """Backend 프로세스의 HTTP 처리 가능 여부를 조회한다."""

        return self._request("GET", "/health")

    def get_ready(self) -> dict[str, Any]:
        """Backend가 필수 저장소와 함께 요청을 받을 준비가 되었는지 조회한다."""

        return self._request("GET", "/ready")

    def get_games(self, *, status: str | None = None, cursor: str | None = None,
                  limit: int = 20) -> dict[str, Any]:
        """명세서의 status·opaque cursor·limit 조건으로 현재 사용자의 게임을 조회한다."""

        if not 1 <= limit <= 100:
            raise ValueError("게임 목록 limit은 1부터 100까지여야 합니다.")
        allowed_statuses = {"IN_PROGRESS", "SAVED", "COMPLETED", "FAILED"}
        if status is not None and status not in allowed_statuses:
            raise ValueError("게임 목록 status가 명세서의 허용 값이 아닙니다.")
        query = [f"limit={limit}"]
        if status is not None:
            query.append(f"status={status}")
        if cursor is not None:
            normalized_cursor = cursor.strip()
            if not normalized_cursor:
                raise ValueError("게임 목록 cursor는 비어 있을 수 없습니다.")
            query.append(f"cursor={quote(normalized_cursor, safe='')}")
        return self._request("GET", "/api/v1/games?" + "&".join(query))

    def get_custom_role_abilities(self) -> dict[str, Any]:
        """Backend의 공개 능력 catalog만 조회하며 MCP 실행 정보를 요청하지 않는다."""

        return self._request("GET", "/api/v1/game-config/custom-role-abilities")

    def create_game(self, *, player_count: int, idempotency_key: UUID | str,
                    mode: str = "STANDARD", custom_role: dict[str, Any] | None = None) -> dict[str, Any]:
        """고정된 idempotency key로 새 게임 생성을 한 번 요청한다."""

        # 팀 전달 사항: 이 body의 version 값은 mystery-v1/scenario-v1로 고정한다.
        # 성공 응답은 data.snapshot이 아니라 data.snapshot_url을 반환해야 하며,
        # Front는 그 URL을 GET해 authoritative snapshot을 조회한다.

        if player_count not in {6, 7, 8, 9}:
            raise ValueError("게임 인원은 6명부터 9명까지 선택할 수 있습니다.")
        if mode not in {"STANDARD", "CUSTOM_ROLE"} or (mode == "STANDARD" and custom_role is not None) or (mode == "CUSTOM_ROLE" and custom_role is None):
            raise ValueError("직업 설정을 확인해 주세요.")
        key = UUID(str(idempotency_key))
        return self._request(
            "POST",
            "/api/v1/games",
            {
                "player_count": player_count,
                "ruleset_version": "mystery-v1",
                "scenario_version": "scenario-v1",
                **({"mode": mode, "custom_role": custom_role} if mode == "CUSTOM_ROLE" else {}),
            },
            extra_headers={"Idempotency-Key": str(key)},
        )

    def get_game(self, game_id: UUID | str) -> dict[str, Any]:
        """생성 성공 뒤 snapshot URL을 통해 authoritative 상태를 조회한다."""

        return self._request("GET", f"/api/v1/games/{UUID(str(game_id))}")

    def get_special_roles(self, game_id: UUID | str) -> dict[str, Any]:
        """본인 전용 조회를 사용자 헤더와 함께 보내며 공유 캐시를 사용하지 않는다."""

        return self._request("GET", f"/api/v1/games/{UUID(str(game_id))}/special-roles")

    def delete_game(self, *, game_id: UUID | str, expected_state_version: int) -> dict[str, Any]:
        """삭제 재확인도 최초 대상·버전을 유지하고 사용자 UUID는 header로만 전달한다."""

        if type(expected_state_version) is not int or expected_state_version < 1:
            raise ValueError("게임 상태 버전이 올바르지 않습니다.")
        return self._request(
            "DELETE", f"/api/v1/games/{UUID(str(game_id))}"
            f"?expected_state_version={expected_state_version}",
        )

    def get_vote_insights(self, *, game_id: UUID | str, window_id: UUID | str,
                          scope: str = "current_discussion") -> dict[str, Any]:
        """보조 조회 지연이 투표 입력을 오래 막지 않도록 짧은 timeout을 적용한다."""

        if scope not in {"current_discussion", "game"}:
            raise ValueError("발언 분석 범위가 올바르지 않습니다.")
        return self._request(
            "GET", f"/api/v1/games/{UUID(str(game_id))}/vote-insights"
            f"?window_id={UUID(str(window_id))}&scope={scope}",
            timeout_seconds=min(self.config.timeout_seconds, 0.75),
        )

    def submit_command(self, *, game_id: UUID | str, command: dict[str, Any],
                       idempotency_key: UUID | str) -> dict[str, Any]:
        """고정된 command body와 idempotency key로 게임 변경을 요청한다."""

        key = UUID(str(idempotency_key))
        return self._request(
            "POST",
            f"/api/v1/games/{UUID(str(game_id))}/commands",
            command,
            extra_headers={"Idempotency-Key": str(key)},
        )

    def get_sync(self, *, game_id: UUID | str, after_state_version: int,
                 after_sequence: int) -> dict[str, Any]:
        """SSE 재연결과 동일한 cursor로 polling sync를 조회한다."""

        # 팀 전달 사항: /sync와 /events는 같은 Front sequence를 사용해야 한다.
        # delta 보존 범위를 벗어나면 operations 일부가 아니라 mode=SNAPSHOT의
        # 완전한 snapshot을 반환해야 Front가 안전하게 복구할 수 있다.

        if after_state_version < 0 or after_sequence < 0:
            raise ValueError("sync cursor는 0 이상이어야 합니다.")
        return self._request(
            "GET",
            f"/api/v1/games/{UUID(str(game_id))}/sync?after_state_version={after_state_version}&after_sequence={after_sequence}",
        )

    def submit_feedback(self, *, body: dict[str, Any], idempotency_key: UUID | str) -> dict[str, Any]:
        """고정된 feedback body와 UUID v4 key로 feedback을 제출한다."""

        # 팀 전달 사항: Backend는 X-User-Id와 Idempotency-Key를 필수로 확인하고,
        # 동일 game의 중복 GAME feedback에는 409를 반환해야 한다. feedback 성공은
        # 201과 data.feedback_id를 사용하며 게임 상태를 변경하지 않는다.

        key = UUID(str(idempotency_key))
        return self._request("POST", "/api/v1/feedback", body, extra_headers={"Idempotency-Key": str(key)})

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None,
                 *, extra_headers: dict[str, str] | None = None,
                 timeout_seconds: float | None = None) -> dict[str, Any]:
        """UUID를 header에만 넣고 JSON object 응답을 검증한다."""

        request_id = str(self._request_id_factory())
        raw = None if body is None else json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        headers = {"Accept": "application/json", "X-User-Id": str(self.user_id), "X-Request-Id": request_id}
        if raw is not None:
            headers["Content-Type"] = "application/json"
        if extra_headers:
            headers.update(extra_headers)
        request = Request(f"{self.config.api_url}{path}", data=raw, method=method, headers=headers)
        try:
            status_code, response_body = self._transport(
                request, self.config.timeout_seconds if timeout_seconds is None else timeout_seconds
            )
        except (OSError, URLError, TimeoutError) as exc:
            raise ApiUnavailableError(status_code=503, code="DEPENDENCY_UNAVAILABLE", request_id=request_id) from exc
        try:
            payload = json.loads(response_body.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ApiUnavailableError(status_code=503, code="INVALID_RESPONSE", request_id=request_id) from exc
        if not isinstance(payload, dict):
            raise ApiUnavailableError(status_code=503, code="INVALID_RESPONSE", request_id=request_id)
        if status_code >= 400:
            error = payload.get("error")
            code = error.get("code") if isinstance(error, dict) else payload.get("code")
            raise ApiResponseError(status_code=status_code, code=code if isinstance(code, str) else "BACKEND_ERROR", request_id=request_id)
        return payload


def _send(request: Request, timeout: float) -> tuple[int, bytes]:
    """검증된 Backend에만 네트워크 요청을 보내고 HTTP 오류 body를 반환한다."""

    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - endpoint를 먼저 검증한다.
            return int(response.status), response.read(256 * 1024)
    except HTTPError as exc:
        return exc.code, exc.read(256 * 1024)
