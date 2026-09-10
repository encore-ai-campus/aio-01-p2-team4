"""Redis event stream과 outbox wakeup 알림 기능."""

from __future__ import annotations

import json
from collections.abc import Sequence

from redis import Redis


EVENTS_KEY_PREFIX = "mafia:v1:events:"
OUTBOX_WAKEUP_CHANNEL = "mafia:v1:outbox:wakeup"


class RedisEventStream:
    """Front-visible event batch pointer만 Redis에 fan-out한다.

    event 본문과 private 정보는 Redis stream에 복사하지 않는다. 소비자가
    stream을 놓치면 PostgreSQL game_events를 기준으로 다시 조회한다.
    """

    def __init__(self, client: Redis, *, max_length: int = 1_000) -> None:
        if max_length <= 0:
            raise ValueError("Redis stream 최대 길이는 0보다 커야 합니다.")
        self._client = client
        self._max_length = max_length

    @staticmethod
    def key(game_id: str) -> str:
        """정본에서 정한 game event stream key를 만든다."""

        return f"{EVENTS_KEY_PREFIX}{game_id}"

    def publish_batch(
        self,
        game_id: str,
        front_sequence: int,
        event_ids: Sequence[str],
    ) -> str:
        """Front sequence와 event ID 목록을 stream에 추가한다."""

        if front_sequence <= 0:
            raise ValueError("front_sequence은 1 이상이어야 합니다.")
        if not event_ids:
            raise ValueError("event batch에는 event ID가 하나 이상 필요합니다.")
        return str(
            self._client.xadd(
                self.key(game_id),
                {
                    "front_sequence": str(front_sequence),
                    "event_ids": json.dumps(list(event_ids), separators=(",", ":")),
                },
                maxlen=self._max_length,
                approximate=True,
            )
        )

    def publish_outbox_wakeup(self, event_outbox_id: int) -> int:
        """새 outbox가 있다는 힌트를 발행한다. 유실돼도 DB polling이 복구한다."""

        return int(self._client.publish(OUTBOX_WAKEUP_CHANNEL, str(event_outbox_id)))
