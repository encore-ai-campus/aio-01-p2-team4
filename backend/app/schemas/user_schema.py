"""내부 사용자 정보를 외부 identity 없이 반환하는 API 응답 schema."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from backend.app.models.identity import UserRecord


class UserResponse(BaseModel):
    """사용자 UUID와 서버가 관리하는 시각만 반환하는 최소 응답."""

    model_config = ConfigDict(extra="forbid")
    user_id: UUID
    created_at: datetime
    last_seen_at: datetime

    @classmethod
    def from_record(cls, record: UserRecord) -> "UserResponse":
        """저장소 모델을 API 응답으로 바꾼다. 외부 계정 정보는 포함하지 않는다."""

        return cls(
            user_id=record.id,
            created_at=record.created_at,
            last_seen_at=record.last_seen_at,
        )
