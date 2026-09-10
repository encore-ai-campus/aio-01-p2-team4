"""게임 service가 엔진 오류를 공개 API 오류로 변환하는 공통 adapter."""

from backend.app.core.errors import ApiError
from backend.app.game_engine.errors import RuleViolation


def rule_error(error: RuleViolation) -> ApiError:
    """엔진의 규칙 오류를 service 계층의 일관된 HTTP 오류로 변환한다."""

    code_map = {
        "INVALID_PHASE": "INVALID_PHASE",
        "GAME_NOT_SAVED": "GAME_NOT_SAVED",
        "PLAYER_DEAD": "PLAYER_DEAD",
        "TARGET_DEAD": "TARGET_INVALID",
        "SELF_TARGET_INVALID": "TARGET_INVALID",
        "TARGET_INVALID": "TARGET_INVALID",
        "DUPLICATE_ACTION": "ACTION_ALREADY_SUBMITTED",
        "ROLE_ACTION_NOT_ALLOWED": "ACTION_NOT_ALLOWED",
        "ROLE_ACTION_INVALID": "ACTION_NOT_ALLOWED",
        "SPEECH_LENGTH_INVALID": "INVALID_REQUEST",
        "WINDOW_NOT_READY": "WINDOW_NOT_READY",
    }
    code = code_map.get(str(error), "ACTION_NOT_ALLOWED")
    return ApiError(
        status_code=409 if code != "INVALID_REQUEST" else 422,
        code=code,
        message="현재 게임 상태에서 허용되지 않는 행동입니다.",
    )
