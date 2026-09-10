"""공개 human discussion command의 얇은 진입점."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from backend.app.schemas.command_schema import GameCommandRequest
from backend.app.services.game.discussion_transaction import submit_discussion_transaction


def submit_discussion(
    service: Any,
    owner_user_id: UUID,
    game_id: UUID,
    payload: GameCommandRequest,
    idempotency_key: UUID,
    *,
    now: datetime | None = None,
) -> tuple[dict[str, Any], bool]:
    """human 요청을 공통 human·AI discussion transaction으로 전달한다."""

    return submit_discussion_transaction(
        service, owner_user_id, game_id, payload, idempotency_key, now=now
    )
