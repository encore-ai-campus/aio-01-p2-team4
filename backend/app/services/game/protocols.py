"""게임 업무 서비스가 의존하는 최소 외부 계약."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class UserWriteService(Protocol):
    """최초 쓰기에서 사용자 UUID를 준비하는 계약."""

    def ensure_user(self, user_id: UUID) -> object: ...
