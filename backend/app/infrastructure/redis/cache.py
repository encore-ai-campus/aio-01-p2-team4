"""Redis 공개 projection cache 기능."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any
from uuid import UUID

from redis import Redis
from redis.exceptions import RedisError


PUBLIC_KEY_PREFIX = "mafia:v1:public:"
CONVERSATION_KEY_PREFIX = "mafia:v1:conversation:"

# 서로 다른 읽기 transaction의 완료 순서가 바뀌어도 과거 이력이 최신 이력을
# 덮지 않는다. JSON 전체를 한 번에 저장하므로 부분 append나 중복 발언도 생기지 않는다.
_STORE_CONVERSATION = """
local existing = redis.call('GET', KEYS[1])
if existing then
    local ok, previous = pcall(cjson.decode, existing)
    if ok and type(previous) == 'table' and type(previous.state_version) == 'number'
       and previous.state_version > tonumber(ARGV[1]) then
        return 0
    end
end
redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
return 1
"""


class RedisConversationHistory:
    """게임별 전체 공개 이력을 보관하며 원본 DB의 현재 cursor와 같은 값만 돌려준다.

    호출부는 공개 event projection을 먼저 적용해야 한다. 역할 원장·개인 context·
    모델 응답 원문을 받지 않으며, 오류를 노출하거나 DB commit을 되돌리지 않는다.
    """

    def __init__(self, client: Redis, *, namespace: str, ttl_seconds: int = 604_800) -> None:
        """DB 대상별 namespace와 복구 가능한 공개 기록의 보관 기간을 고정한다."""

        if not namespace or not namespace.isalnum() or ttl_seconds <= 0:
            raise ValueError("대화 cache namespace 또는 TTL이 올바르지 않습니다.")
        self._client = client
        self._namespace = namespace
        self._ttl_seconds = ttl_seconds

    def key(self, game_id: str) -> str:
        """게임 ID를 정규화해 다른 자료의 Redis key를 지정할 수 없게 한다."""

        return f"{CONVERSATION_KEY_PREFIX}{self._namespace}:{UUID(game_id)}"

    @staticmethod
    def _checksum(events: list[dict[str, Any]]) -> str:
        """순서와 전체 본문을 함께 검사해 부분 저장·잘린 목록을 cache miss로 처리한다."""

        body = json.dumps(events, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return sha256(body.encode()).hexdigest()

    def get(self, game_id: str, *, state_version: int, through_sequence: int,
            front_sequence: int) -> list[dict[str, Any]] | None:
        """상한·게임·checksum이 모두 일치한 전체 이력만 반환하고 장애는 miss로 처리한다."""

        try:
            raw = self._client.get(self.key(game_id))
            if raw is None:
                return None
            value = json.loads(raw)
            expected = {"schema_version": 1, "state_version": state_version,
                        "through_sequence": through_sequence, "front_sequence": front_sequence}
            if not isinstance(value, dict) or value.get("game_id") != str(UUID(game_id)):
                return None
            if any(type(value.get(key)) is not int or value[key] != number
                   for key, number in expected.items()):
                return None
            events = value.get("events")
            if not isinstance(events, list) or any(not isinstance(event, dict) for event in events):
                return None
            if value.get("checksum") != self._checksum(events):
                return None
            return events
        except (RedisError, OSError, TypeError, ValueError):
            return None

    def set(self, game_id: str, *, state_version: int, through_sequence: int,
            front_sequence: int, events: list[dict[str, Any]]) -> bool:
        """검증된 공개 이력 전체를 원자적으로 교체하며 늦은 버전은 버린다."""

        try:
            if (type(state_version) is not int or state_version < 1
                or type(through_sequence) is not int or through_sequence < 0
                or type(front_sequence) is not int or front_sequence < 0):
                return False
            value = {"schema_version": 1, "game_id": str(UUID(game_id)),
                     "state_version": state_version, "through_sequence": through_sequence,
                     "front_sequence": front_sequence, "events": events,
                     "checksum": self._checksum(events)}
            body = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            return bool(self._client.eval(
                _STORE_CONVERSATION, 1, self.key(game_id), state_version, body, self._ttl_seconds,
            ))
        except (RedisError, OSError, TypeError, ValueError):
            return False

    def delete(self, game_id: str) -> bool:
        """DB에서 정리된 게임의 공개 대화 cache를 최선형으로 삭제한다."""

        try:
            return bool(self._client.delete(self.key(game_id)))
        except (RedisError, OSError, TypeError, ValueError):
            return False


class RedisPublicCache:
    """PostgreSQL에서 다시 만들 수 있는 공개 snapshot만 짧게 캐시한다.

    이 클래스는 private role, seed, prompt를 받지 않는 호출부와 함께 사용해야
    한다. Redis 데이터가 없어져도 원본 DB로 응답을 재구성할 수 있어야 한다.
    """

    def __init__(self, client: Redis, *, ttl_seconds: int = 60) -> None:
        if ttl_seconds <= 0:
            raise ValueError("공개 cache TTL은 0보다 커야 합니다.")
        self._client = client
        self._ttl_seconds = ttl_seconds

    @staticmethod
    def key(game_id: str, state_version: int) -> str:
        """게임과 state version별 공개 cache key를 만든다."""

        return f"{PUBLIC_KEY_PREFIX}{game_id}:{state_version}"

    def set(self, game_id: str, state_version: int, projection: dict[str, Any]) -> None:
        """공개 projection을 JSON으로 저장한다."""

        if state_version <= 0:
            raise ValueError("state_version은 1 이상이어야 합니다.")
        value = json.dumps(projection, ensure_ascii=False, separators=(",", ":"))
        self._client.setex(self.key(game_id, state_version), self._ttl_seconds, value)

    def get(self, game_id: str, state_version: int) -> dict[str, Any] | None:
        """cache miss면 None을 반환하고, JSON object가 아니면 폐기한다."""

        raw = self._client.get(self.key(game_id, state_version))
        if raw is None:
            return None
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            self._client.delete(self.key(game_id, state_version))
            return None
        return parsed if isinstance(parsed, dict) else None

    def delete(self, game_id: str, state_version: int) -> None:
        """검증된 공개 cache 한 건만 삭제한다."""

        self._client.delete(self.key(game_id, state_version))
