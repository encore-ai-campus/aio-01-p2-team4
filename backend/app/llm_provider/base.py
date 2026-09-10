"""Provider 구현이 공유하는 비동기 요청·응답 계약이다."""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class LLMRequest:
    """모델에 전달할 제한된 메시지와 구조화 출력 조건이다."""

    messages: tuple[dict[str, str], ...]
    response_schema: dict[str, Any]
    max_output_tokens: int
    timeout_seconds: float
    trace_id: str | None = None


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Provider SDK 응답에서 외부에 공개할 관측 정보와 결과다."""

    provider: str
    model: str
    output: dict[str, Any]
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None
    request_id: str | None = None
    latency_ms: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class LLMProvider(Protocol):
    """게임 Agent가 Provider 구현을 교체할 때 의존하는 최소 인터페이스다."""

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """구조화된 모델 응답을 생성한다."""

