"""애플리케이션 설정에서 선택된 LLM Provider를 조립한다."""

from backend.app.core.config import Settings, get_settings
from backend.app.llm_provider.dummy import DummyProvider
from backend.app.llm_provider.errors import LLMConfigurationError
from backend.app.llm_provider.gemini_provider import GeminiProvider
from backend.app.llm_provider.local import LocalProvider
from backend.app.llm_provider.openai_provider import OpenAIProvider


def get_llm_provider(settings: Settings | None = None):
    """Provider 선택값에 필요한 설정만 확인해 구현체를 반환한다."""

    selected = settings or get_settings()
    if selected.llm_provider == "dummy":
        return DummyProvider()
    if selected.llm_provider == "local":
        return LocalProvider(selected.local_llm_base_url, selected.local_llm_model)
    if selected.llm_provider == "openai":
        if not selected.openai_api_key or not selected.openai_model:
            raise LLMConfigurationError("OPENAI_API_KEY and OPENAI_MODEL are required")
        return OpenAIProvider(selected.openai_api_key, selected.openai_model)
    if selected.llm_provider == "gemini":
        if not selected.gemini_api_key or not selected.gemini_model:
            raise LLMConfigurationError("GEMINI_API_KEY and GEMINI_MODEL are required")
        return GeminiProvider(selected.gemini_api_key, selected.gemini_model)
    raise LLMConfigurationError("LLM_PROVIDER is not supported")
