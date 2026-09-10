"""브라우저 UUID identity의 순수 검증·생성 규칙."""

from __future__ import annotations

from uuid import UUID, uuid4

STORAGE_KEY = "ai_mafia_user_id_v1"

# 팀 전달 사항: 일반 사용자 origin의 local storage key는 이 값으로 고정한다.
# 관리자 앱은 다른 origin과 ai_mafia_admin_user_id_v1 key를 사용하므로 두 앱의
# UUID 저장값을 공유한다고 가정하면 안 된다.


def parse_uuid_v4(value: object) -> UUID | None:
    """외부 문자열이 UUID v4인지 검증하고 아니면 None을 반환한다."""

    try:
        parsed = UUID(str(value))
    except (AttributeError, TypeError, ValueError):
        return None
    return parsed if parsed.version == 4 else None


def new_user_id() -> UUID:
    """브라우저 crypto.randomUUID의 session-only 대체값을 생성한다."""

    return uuid4()
