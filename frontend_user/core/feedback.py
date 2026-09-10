"""일반·게임별 feedback 입력 검증."""

from __future__ import annotations

import unicodedata
from typing import Any
from uuid import UUID

ALLOWED_TAGS = ("UX", "BALANCE", "DIALOGUE")


def build_feedback(
    *, feedback_type: str, rating: int, comment: str, tags: list[str], game_id: str | None = None
) -> dict[str, Any]:
    """정본의 rating·comment·tag 경계를 검증한 뒤 API body를 구성한다."""

    # 팀 전달 사항: Backend는 이 검증을 다시 수행하고 등록된 tag allowlist만
    # 허용해야 한다. Front의 local storage에는 제출 완료 flag를 저장하지 않는다.
    if feedback_type not in {"GENERAL", "GAME"}:
        raise ValueError("피드백 종류가 올바르지 않습니다.")
    if not isinstance(rating, int) or isinstance(rating, bool) or not 1 <= rating <= 5:
        raise ValueError("별점은 1점부터 5점까지 선택해 주세요.")
    normalized = " ".join(unicodedata.normalize("NFC", comment).split())
    if normalized and (
        len(normalized) > 1000
        or any(unicodedata.category(char).startswith("C") for char in normalized)
    ):
        raise ValueError("의견은 제어 문자 없이 1000자까지 입력해 주세요.")
    if len(tags) > 5 or len(set(tags)) != len(tags) or any(tag not in ALLOWED_TAGS for tag in tags):
        raise ValueError("선택 가능한 태그를 확인해 주세요.")
    body: dict[str, Any] = {
        "feedback_type": feedback_type,
        "rating": rating,
        "comment": normalized or None,
        "tags": tags,
    }
    if feedback_type == "GAME":
        try:
            body["game_id"] = str(UUID(str(game_id)))
        except (TypeError, ValueError):
            raise ValueError("게임 식별자를 확인할 수 없습니다.") from None
    return body
