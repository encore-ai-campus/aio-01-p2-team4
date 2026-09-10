"""일반·게임별 feedback 요청 schema."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ALLOWED_FEEDBACK_TAGS = frozenset({"UX", "BALANCE", "DIALOGUE", "BUG", "PERFORMANCE"})


class FeedbackRequest(BaseModel):
    """feedback의 두 종류를 하나의 폐쇄형 요청으로 검증한다."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    feedback_type: Literal["GENERAL", "GAME"]
    game_id: UUID | None = None
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)
    tags: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        """공백만 있는 의견과 제어문자를 저장하지 않는다."""

        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("comment must not be blank")
        return normalized

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, values: list[str]) -> list[str]:
        """등록된 tag만 중복 없이 허용한다."""

        normalized = [" ".join(value.split()).upper() for value in values]
        if len(set(normalized)) != len(normalized):
            raise ValueError("tags must not contain duplicates")
        if any(value not in ALLOWED_FEEDBACK_TAGS for value in normalized):
            raise ValueError("tag is not allowed")
        return normalized

    @model_validator(mode="after")
    def validate_game_scope(self) -> "FeedbackRequest":
        """GENERAL은 game_id를, GAME은 game_id를 반드시 갖게 한다."""

        if self.feedback_type == "GENERAL" and self.game_id is not None:
            raise ValueError("GENERAL feedback cannot include game_id")
        if self.feedback_type == "GAME" and self.game_id is None:
            raise ValueError("GAME feedback requires game_id")
        return self
