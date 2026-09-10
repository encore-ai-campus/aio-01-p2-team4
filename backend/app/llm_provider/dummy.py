"""외부 네트워크 없이 Provider 계약을 검증하는 결정적 구현이다."""

from backend.app.llm_provider.base import LLMProvider, LLMRequest, LLMResponse


class DummyProvider(LLMProvider):
    """scaffold와 회귀 테스트에서 사용할 고정 PING 응답 Provider다."""

    def __init__(self, *, state_version: int = 1) -> None:
        self.state_version = state_version

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """B6에서는 PASS를 반환하고, 기존 scaffold 요청은 그대로 호환한다."""

        version = self.state_version
        is_legacy = False
        for message in request.messages:
            content = message.get("content", "")
            if content.startswith("source_state_version="):
                version = int(content.split("=", 1)[1])
                is_legacy = True
        output = (
            {"action": "PING", "target_player_id": None, "source_state_version": version}
            if is_legacy
            else {
                "type": "PASS",
                "target_player_id": None,
                "message": None,
                "public_rationale": None,
            }
        )
        return LLMResponse(
            provider="dummy",
            model="dummy",
            output=output,
            input_tokens=0,
            output_tokens=0,
            finish_reason="stop",
        )

