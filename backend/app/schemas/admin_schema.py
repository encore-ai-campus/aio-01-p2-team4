"""read-only 관리자 API의 query 입력을 검증한다.

관리자 API는 화면이 보내는 값을 그대로 SQL이나 서비스에 전달하지 않는다.
목록의 상태·phase와 metrics의 기간을 이 경계에서 먼저 제한해 잘못된 조회가
일어나거나 지나치게 큰 범위를 한 번에 읽는 일을 막는다.
"""

import re
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AdminStatus = Literal["IN_PROGRESS", "SAVED", "COMPLETED", "FAILED"]
AdminPhase = Literal[
    "ROLE_REVEAL",
    "DAY_DISCUSSION",
    "NIGHT_ACTION",
    "DAY_VOTE",
    "REVOTE",
    "FINAL_DISCUSSION",
    "FINAL_ACCUSATION",
    "ENDED",
]


class AdminGameListQuery(BaseModel):
    """관리자 게임 목록의 허용된 필터와 페이지 크기다."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    status: AdminStatus | None = None
    phase: AdminPhase | None = None
    cursor: str | None = Field(default=None, max_length=200)
    limit: int = Field(default=20, ge=1, le=100)


class AdminMetricsQuery(BaseModel):
    """관리자 통계 조회 기간이다. 최대 31일만 허용한다."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)

    from_: datetime | None = Field(default=None, alias="from")
    to: datetime | None = None

    @model_validator(mode="after")
    def validate_range(self) -> "AdminMetricsQuery":
        """시작·종료 순서와 최대 조회 기간을 검사한다."""

        if self.from_ is not None and self.from_.tzinfo is None:
            self.from_ = self.from_.replace(tzinfo=UTC)
        if self.to is not None and self.to.tzinfo is None:
            self.to = self.to.replace(tzinfo=UTC)
        if self.from_ is not None and self.to is not None:
            if self.from_ > self.to:
                raise ValueError("from must not be later than to")
            if (self.to - self.from_).total_seconds() > 31 * 24 * 60 * 60:
                raise ValueError("metrics range must not exceed 31 days")
        return self


class AdminSpeechAnalyticsQuery(BaseModel):
    """관리자 공개 발언 분석의 범위와 표시할 주제 수를 검증한다."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)

    from_: datetime | None = Field(default=None, alias="from")
    to: datetime | None = None
    game_id: UUID | None = None
    persona_id: str | None = Field(default=None, min_length=1, max_length=64)
    round: int | None = Field(default=None, ge=0, le=5)
    analysis_version: str | None = Field(default=None, min_length=1, max_length=128)
    limit: int = Field(default=12, ge=1, le=20)

    @field_validator("persona_id", "analysis_version")
    @classmethod
    def validate_identifier(cls, value: str | None) -> str | None:
        """SQL 식별자 필터에 공백과 제어 문자를 허용하지 않는다."""

        if value is None:
            return None
        if not value.isprintable() or not value.strip() or any(char in value for char in "\r\n\t"):
            raise ValueError("identifier must be printable")
        return value.strip()

    @model_validator(mode="after")
    def validate_range(self) -> "AdminSpeechAnalyticsQuery":
        """발언 event 시각 범위의 timezone과 최대 31일 간격을 검사한다."""

        if self.from_ is not None and self.from_.tzinfo is None:
            self.from_ = self.from_.replace(tzinfo=UTC)
        if self.to is not None and self.to.tzinfo is None:
            self.to = self.to.replace(tzinfo=UTC)
        if self.from_ is not None and self.to is not None:
            if self.from_ > self.to:
                raise ValueError("from must not be later than to")
            if (self.to - self.from_).total_seconds() > 31 * 24 * 60 * 60:
                raise ValueError("speech analytics range must not exceed 31 days")
        return self


AdminAuditType = Literal[
    "ADMIN_LIST_GAMES", "ADMIN_GET_GAME", "ADMIN_GET_METRICS",
    "ADMIN_GET_ROLE_WIN_RATES", "ADMIN_GET_PERSONA_WIN_RATES",
    "ADMIN_LIST_FEEDBACK", "ADMIN_LIST_AUDIT_LOGS", "ADMIN_QUERY_INSIGHTS",
    "ADMIN_GET_SPEECH_ANALYTICS", "ADMIN_LIST_AGENT_JOBS",
]


class AdminFeedbackQuery(BaseModel):
    """피드백 페이지의 필터와 UUID 커서를 SQL 호출 전에 검증한다."""

    model_config = ConfigDict(extra="forbid")
    feedback_type: Literal["GENERAL", "GAME"] | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    cursor: UUID | None = None
    limit: int = Field(default=20, ge=1, le=100)


class AdminAuditQuery(BaseModel):
    """감사 PK의 bigint 범위를 제한하고 이벤트 분류만 필터로 허용한다."""

    model_config = ConfigDict(extra="forbid")
    event_type: AdminAuditType | None = None
    cursor: int | None = Field(default=None, ge=1, le=9223372036854775807)
    limit: int = Field(default=20, ge=1, le=100)


class AdminAgentJobQuery(BaseModel):
    """Agent 작업의 저장된 분류와 UUID만 허용해 조회 조건을 제한한다."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    game_id: UUID | None = None
    job_kind: Literal["SPEECH", "NIGHT_ACTION", "VOTE", "GM_NARRATION"] | None = None
    status: Literal["RESERVED", "SUCCEEDED", "FALLBACK", "STALE", "FAILED"] | None = None
    cursor: UUID | None = None
    limit: int = Field(default=20, ge=1, le=100)


AdminKnowledgeSourceType = Literal["FEEDBACK", "GAME_SUMMARY", "OPERATIONS_DOC"]


class AdminInsightFilters(BaseModel):
    """운영 자료 검색에 적용할 안전한 구조화 필터다."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)

    source_types: list[AdminKnowledgeSourceType] = Field(
        default_factory=lambda: ["FEEDBACK", "GAME_SUMMARY", "OPERATIONS_DOC"],
        min_length=1,
        max_length=3,
    )
    rating_lte: int | None = Field(default=None, ge=1, le=5)
    from_: datetime | None = Field(default=None, alias="from")
    to: datetime | None = None

    @field_validator("source_types")
    @classmethod
    def validate_source_types(cls, values: list[str]) -> list[str]:
        """중복 source type을 제거해 검색 조건을 예측 가능하게 만든다."""

        unique = list(dict.fromkeys(values))
        if not unique:
            raise ValueError("source_types must not be empty")
        return unique

    @model_validator(mode="after")
    def validate_range(self) -> "AdminInsightFilters":
        """검색 기간의 timezone과 최대 31일 범위를 검증한다."""

        if self.from_ is not None and self.from_.tzinfo is None:
            self.from_ = self.from_.replace(tzinfo=UTC)
        if self.to is not None and self.to.tzinfo is None:
            self.to = self.to.replace(tzinfo=UTC)
        if self.from_ is not None and self.to is not None:
            if self.from_ > self.to:
                raise ValueError("from must not be later than to")
            if (self.to - self.from_).total_seconds() > 31 * 24 * 60 * 60:
                raise ValueError("insight range must not exceed 31 days")
        return self


class AdminInsightQuery(BaseModel):
    """관리자 운영 자료 질문과 검색 범위를 검증하는 요청 모델이다."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=3, max_length=500)
    filters: AdminInsightFilters = Field(default_factory=AdminInsightFilters)
    top_k: int = Field(default=5, ge=1, le=10)

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        """질문 공백을 정규화하고 비밀값 조회 의도를 차단한다."""

        normalized = " ".join(value.split())
        if re.search(
            r"(?i)(?:\bapi[_ -]?key\b|\bpassword\b|\bpasswd\b|\bsecret\b|\btoken\b|\bdatabase[_ -]?url\b|비밀번호|암호|비밀키|접속정보)",
            normalized,
        ):
            raise ValueError("credential questions are not allowed")
        return normalized
