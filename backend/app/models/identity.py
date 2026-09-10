"""UUID 기반 내부 사용자 식별 모델."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class UserRecord:
    """정본 ``users`` 테이블과 일치하는 최소 사용자 읽기 모델.

    사용자에게 필요한 것은 UUID와 생성·최근 확인 시각뿐이며, UUID 자체는
    인증 수단이 아니라 사용자 구분을 위한 식별자다.
    """

    id: UUID
    created_at: datetime
    last_seen_at: datetime
