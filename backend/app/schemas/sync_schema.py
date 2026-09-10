"""게임 polling·SSE가 공유하는 동기화 요청 타입."""

from pydantic import BaseModel, ConfigDict, Field


class SyncQuery(BaseModel):
    """마지막으로 적용한 client cursor다."""

    model_config = ConfigDict(extra="forbid")

    after_state_version: int = Field(ge=0)
    after_sequence: int = Field(ge=0)
