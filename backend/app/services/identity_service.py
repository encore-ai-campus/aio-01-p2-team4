"""공개 요청의 UUID 사용자 컨텍스트를 처리하는 서비스."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from backend.app.models.identity import UserRecord


class UserRepository(Protocol):
    """서비스가 사용자 생성·조회에 사용하는 최소 저장소 계약."""

    def ensure_user(self, user_id: UUID) -> UserRecord: ...

    def get_user(self, user_id: UUID) -> UserRecord | None: ...


class IdentityService:
    """인증을 대신하지 않고 UUID 사용자 행의 생명주기만 관리한다.

    X-User-Id는 UUID 형식의 식별자일 뿐이다. 토큰 검증이나 로그인 기능은
    이 서비스의 책임이 아니며, 게임 소유권도 게임 서비스가 별도로 확인한다.
    """

    def __init__(self, repository: UserRepository) -> None:
        self._repository = repository

    def ensure_user(self, user_id: UUID) -> UserRecord:
        """최초 쓰기 요청에서만 사용자를 멱등 생성한다."""

        return self._repository.ensure_user(user_id)

    def get_user(self, user_id: UUID) -> UserRecord | None:
        """조회 전용 경로에서 사용한다. 알 수 없는 UUID는 생성하지 않는다."""

        return self._repository.get_user(user_id)
