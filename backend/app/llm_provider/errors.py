"""Provider별 예외를 애플리케이션 공통 오류로 변환한다."""


class LLMProviderError(RuntimeError):
    """LLM 호출 실패의 안전한 상위 예외다."""

    code = "LLM_PROVIDER_ERROR"


class LLMConfigurationError(LLMProviderError):
    """선택된 Provider의 필수 설정이 없거나 잘못된 경우다."""

    code = "LLM_CONFIGURATION_ERROR"


class LLMDependencyError(LLMProviderError):
    """선택된 Provider의 공식 SDK가 설치되지 않은 경우다."""

    code = "LLM_DEPENDENCY_ERROR"


class LLMTimeoutError(LLMProviderError):
    """Provider가 제한 시간 안에 응답하지 않은 경우다."""

    code = "LLM_TIMEOUT"


class LLMAuthenticationError(LLMProviderError):
    """Provider 인증이 거부된 경우다."""

    code = "LLM_AUTHENTICATION_ERROR"


class LLMRateLimitError(LLMProviderError):
    """Provider의 요청 한도를 초과한 경우다."""

    code = "LLM_RATE_LIMIT"


class LLMResponseError(LLMProviderError):
    """Provider 응답이 비어 있거나 공통 계약과 맞지 않는 경우다."""

    code = "LLM_RESPONSE_ERROR"


class LLMIncompleteError(LLMResponseError):
    """추론·출력 한도 등으로 최종 구조화 응답이 완성되지 않은 경우다."""

    code = "LLM_INCOMPLETE"


class LLMModelUnavailableError(LLMProviderError):
    """설정한 모델이 존재하지 않거나 해당 프로젝트에서 접근할 수 없는 경우다."""

    code = "LLM_MODEL_UNAVAILABLE"
