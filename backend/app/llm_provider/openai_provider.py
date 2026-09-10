"""OpenAI 공식 비동기 SDK를 공통 Provider 계약으로 감싼다."""

import time
from typing import Any, NoReturn

from backend.app.llm_provider.base import LLMProvider, LLMRequest, LLMResponse
from backend.app.llm_provider.errors import (
    LLMAuthenticationError,
    LLMDependencyError,
    LLMIncompleteError,
    LLMModelUnavailableError,
    LLMRateLimitError,
    LLMResponseError,
    LLMTimeoutError,
)


class OpenAIProvider(LLMProvider):
    """OpenAI Responses API의 구조화 JSON 응답 adapter다."""

    def __init__(self, api_key: str, model: str) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError as error:
            raise LLMDependencyError(
                "openai package is required for the openai provider"
            ) from error
        # SDK 내부 재시도가 고정 Agent lease 밖에서 계속 실행되지 않게 한다.
        self.client = AsyncOpenAI(api_key=api_key, max_retries=0)
        self.model = model

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """OpenAI 응답을 JSON object와 token usage로 정규화한다."""

        started = time.perf_counter()
        reasoning_model = self.model.startswith(("gpt-5", "gpt-6", "o1", "o3", "o4"))
        # 추론 모델의 한도에는 비공개 reasoning도 포함된다. 낮게 지정된 legacy
        # 요청에는 최소 여유를 주고, Agent가 지정한 더 큰 예산은 그대로 전달한다.
        options = {"reasoning": {"effort": "high"}} if reasoning_model else {}
        output_limit = max(request.max_output_tokens, 4096) if reasoning_model else request.max_output_tokens
        try:
            response = await self.client.responses.create(
                model=self.model,
                input=[dict(message) for message in request.messages],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "game_proposal",
                        "schema": request.response_schema,
                        "strict": True,
                    }
                },
                max_output_tokens=output_limit,
                timeout=request.timeout_seconds,
                store=False,
                **options,
            )
        except Exception as error:
            _raise_openai_error(error)
        if getattr(response, "status", None) == "incomplete":
            raise LLMIncompleteError("OpenAI response was incomplete")
        if getattr(response, "status", None) not in {None, "completed"}:
            raise LLMResponseError("OpenAI response did not complete")
        try:
            output = response.output_text
            import json
            parsed = json.loads(output)
        except (AttributeError, TypeError, ValueError) as error:
            raise LLMResponseError("OpenAI returned an invalid structured response") from error
        if not isinstance(parsed, dict):
            raise LLMResponseError("OpenAI response must be a JSON object")
        usage = getattr(response, "usage", None)
        return LLMResponse(
            provider="openai",
            model=self.model,
            output=parsed,
            input_tokens=_usage_value(usage, "input_tokens"),
            output_tokens=_usage_value(usage, "output_tokens"),
            finish_reason=None,
            request_id=getattr(response, "id", None),
            latency_ms=int((time.perf_counter() - started) * 1_000),
        )


def _usage_value(usage: Any, key: str) -> int | None:
    """SDK usage 객체에서 음수가 아닌 token 수만 반환한다."""

    value = getattr(usage, key, None)
    return value if isinstance(value, int) and value >= 0 else None


def _raise_openai_error(error: Exception) -> NoReturn:
    """OpenAI SDK 오류를 비밀값 없는 공통 오류로 변환한다."""

    name = type(error).__name__.lower()
    if name == "notfounderror" or getattr(error, "code", None) == "model_not_found":
        raise LLMModelUnavailableError("OpenAI model is unavailable") from error
    if "authentication" in name or "permission" in name:
        raise LLMAuthenticationError("OpenAI authentication failed") from error
    if "ratelimit" in name:
        raise LLMRateLimitError("OpenAI rate limit exceeded") from error
    if "timeout" in name:
        raise LLMTimeoutError("OpenAI request timed out") from error
    raise LLMResponseError("OpenAI request failed") from error
