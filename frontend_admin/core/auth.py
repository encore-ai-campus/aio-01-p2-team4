"""관리자 UUID 입력을 정규화하며 실제 권한 판정은 Backend에 맡긴다."""

from uuid import UUID

ADMIN_ACCESS_SESSION_KEY = "admin-access-granted"
ADMIN_USER_ID_SESSION_KEY = "admin.user_id"
ADMIN_STORAGE_KEY = "ai_mafia_admin_user_id_v1"


def parse_admin_uuid(value: object) -> UUID | None:
    """붙여 넣은 UUID v4만 정규화하고 URL·임의 문자열은 식별자로 사용하지 않는다."""

    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    try:
        parsed = UUID(normalized)
    except ValueError:
        return None
    return parsed if parsed.version == 4 and str(parsed) == normalized else None


def has_admin_access(value: object) -> bool:
    """명시적인 불리언 True만 관리자 접근 허용으로 해석한다."""

    return value is True
