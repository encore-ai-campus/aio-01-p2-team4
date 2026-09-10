"""Redis game lock 보조 기능."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from redis import Redis


LOCK_KEY_PREFIX = "mafia:v1:lock:game:"
_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


@dataclass(frozen=True, slots=True)
class GameLockToken:
    """획득한 lock과 소유 token을 한 쌍으로 보관한다."""

    game_id: str
    token: str


class RedisGameLock:
    """Redis를 짧은 보조 잠금으로 사용한다.

    Redis lock이 사라져도 PostgreSQL의 game row ``FOR UPDATE``가 최종 정합성을
    보장한다. token을 비교하지 않고 release하면 다른 요청의 lock을 지울 수
    있으므로 반드시 소유 token을 확인한다.
    """

    def __init__(self, client: Redis, *, ttl_seconds: int = 15) -> None:
        if ttl_seconds <= 0:
            raise ValueError("Redis lock TTL은 0보다 커야 합니다.")
        self._client = client
        self._ttl_seconds = ttl_seconds

    @staticmethod
    def key(game_id: str) -> str:
        """정본에서 정한 game lock key를 만든다."""

        return f"{LOCK_KEY_PREFIX}{game_id}"

    def acquire(self, game_id: str) -> GameLockToken | None:
        """lock을 얻으면 token을 반환하고, 이미 사용 중이면 None을 반환한다."""

        token = str(uuid4())
        acquired = self._client.set(
            self.key(game_id), token, nx=True, ex=self._ttl_seconds
        )
        return GameLockToken(game_id, token) if acquired else None

    def release(self, lock: GameLockToken) -> bool:
        """token이 아직 유효하고 내 token일 때만 lock을 해제한다."""

        deleted = self._client.eval(
            _RELEASE_SCRIPT,
            1,
            self.key(lock.game_id),
            lock.token,
        )
        return bool(deleted)
