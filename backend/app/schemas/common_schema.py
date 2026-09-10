"""여러 Backend endpoint가 공유하는 상태와 오류 응답 schema."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """프로세스 생존 여부만 노출하는 health 응답."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["ok"] = "ok"


class ReadinessDependencies(BaseModel):
    """Backend가 실제 요청을 처리할 때 필요한 두 저장소의 연결 상태.

    주소나 오류 원문은 절대 포함하지 않고 ``ok`` 또는 ``error``만 반환한다.
    따라서 운영 DB 비밀번호나 내부 서버 주소가 준비 상태 응답으로 새어 나가지 않는다.
    """

    model_config = ConfigDict(extra="forbid")
    postgresql: Literal["ok", "error"]
    redis: Literal["ok", "error"]


class ReadinessResponse(BaseModel):
    """DB와 Redis를 모두 사용할 수 있는지 알려 주는 준비 상태 응답."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["ready", "not_ready"]
    dependencies: ReadinessDependencies


class ErrorDetail(BaseModel):
    """클라이언트가 오류를 이해하고 재시도 여부를 판단하는 정보."""

    model_config = ConfigDict(extra="forbid")
    code: str
    message: str
    request_id: str
    retryable: bool
    details: Any = None


class ErrorResponse(BaseModel):
    """비밀값이나 내부 예외 문자열을 포함하지 않는 공통 오류 계약."""

    model_config = ConfigDict(extra="forbid")
    error: ErrorDetail
