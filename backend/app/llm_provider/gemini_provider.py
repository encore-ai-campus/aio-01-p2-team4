"""Google GenAI 공식 비동기 API를 공통 Provider 계약으로 감싼다."""

import asyncio
import json
import time
from typing import Any

from backend.app.llm_provider.base import LLMProvider, LLMRequest, LLMResponse
from backend.app.llm_provider.errors import LLMDependencyError, LLMResponseError, LLMTimeoutError


class GeminiProvider(LLMProvider):
    """Gemini JSON response schema 기능을 사용하는 adapter다."""

    def __init__(self, api_key: str, model: str) -> None:
        try:
            from google import genai
        except ImportError as error:
            raise LLMDependencyError(
                "google-genai package is required for the gemini provider"
            ) from error
        self.client = genai.Client(api_key=api_key)
        self.model = model

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """메시지를 Gemini content로 변환하고 JSON 응답을 정규화한다."""

        try:
            from google.genai import types
        except ImportError as error:
            raise LLMDependencyError(
                "google-genai types are required for the gemini provider"
            ) from error
        started = time.perf_counter()
        # MCP developer 지침도 시스템 영역에 보존하고 게임 원문만 user로 전달한다.
        system_instruction = "\n\n".join(
            message["content"] for message in request.messages
            if message.get("role") in {"system", "developer"}
        ) or None
        contents = [
            {"role": "user", "parts": [{"text": message["content"]}]}
            for message in request.messages
            if message.get("role") not in {"system", "developer"}
        ]
        try:
            response = await asyncio.wait_for(
                self.client.aio.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0,
                        max_output_tokens=request.max_output_tokens,
                        response_mime_type="application/json",
                        response_schema=_gemini_response_schema(request.response_schema),
                    ),
                ),
                timeout=request.timeout_seconds,
            )
        except TimeoutError as error:
            raise LLMTimeoutError("Gemini request timed out") from error
        except Exception as error:
            raise LLMResponseError("Gemini request failed") from error
        try:
            parsed = json.loads(response.text)
        except (AttributeError, TypeError, json.JSONDecodeError) as error:
            raise LLMResponseError("Gemini returned an invalid structured response") from error
        if not isinstance(parsed, dict):
            raise LLMResponseError("Gemini response must be a JSON object")
        usage = getattr(response, "usage_metadata", None)
        return LLMResponse(
            provider="gemini",
            model=self.model,
            output=parsed,
            input_tokens=_usage_value(usage, "prompt_token_count"),
            output_tokens=_usage_value(usage, "candidates_token_count"),
            finish_reason=_finish_reason(response),
            latency_ms=int((time.perf_counter() - started) * 1_000),
        )


def _usage_value(usage: Any, key: str) -> int | None:
    """Gemini usage metadata에서 음수가 아닌 token 수만 반환한다."""

    value = getattr(usage, key, None)
    return value if isinstance(value, int) and value >= 0 else None


def _gemini_response_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """공통 JSON Schema의 nullable union을 Gemini Schema 형식으로 변환한다."""

    properties: dict[str, dict[str, Any]] = {}
    for name, definition in schema.get("properties", {}).items():
        raw_type = definition.get("type")
        nullable = isinstance(raw_type, list) and "null" in raw_type
        value_type = next((item for item in raw_type if item != "null"), "string") if nullable else raw_type
        properties[name] = {
            "type": str(value_type).upper(),
            "nullable": nullable,
        }
    return {
        "type": "OBJECT",
        "properties": properties,
        "required": schema.get("required", []),
    }


def _finish_reason(response: Any) -> str | None:
    """candidate가 없거나 enum 객체인 경우에도 안전하게 종료 사유를 반환한다."""

    try:
        value = response.candidates[0].finish_reason
    except (AttributeError, IndexError, TypeError):
        return None
    return getattr(value, "name", str(value)) if value is not None else None
