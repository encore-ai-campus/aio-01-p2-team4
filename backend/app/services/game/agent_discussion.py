"""공통 discussion transaction을 호출하는 Agent 진입점."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from backend.app.schemas.command_schema import GameCommandRequest
from backend.app.services.game.actor_context import ActorContext
from backend.app.services.game.discussion_transaction import submit_discussion_transaction
from backend.app.services.game_service import PostgresDiscussionCommandService


class PostgresAgentDiscussionService(PostgresDiscussionCommandService):
    """AI SPEAK·PASS를 human과 동일한 transaction helper로 저장한다."""

    def submit_pass(
        self,
        owner_user_id: UUID,
        game_id: UUID,
        player_id: UUID,
        *,
        expected_state_version: int,
        window_id: UUID,
        idempotency_key: UUID | None = None,
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """AI PASS를 공통 discussion transaction으로 전달한다."""

        return submit_discussion_transaction(
            self,
            owner_user_id,
            game_id,
            GameCommandRequest(type="PASS", expected_state_version=expected_state_version, window_id=window_id),
            idempotency_key or uuid4(),
            actor=ActorContext.agent(owner_user_id=owner_user_id, player_id=player_id),
            now=now,
        )

    def submit_speak(
        self,
        owner_user_id: UUID,
        game_id: UUID,
        player_id: UUID,
        message: str,
        *,
        expected_state_version: int,
        window_id: UUID,
        idempotency_key: UUID | None = None,
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """AI SPEAK를 공통 discussion transaction으로 전달한다."""

        return submit_discussion_transaction(
            self,
            owner_user_id,
            game_id,
            GameCommandRequest(
                type="SPEAK",
                expected_state_version=expected_state_version,
                window_id=window_id,
                message=message,
            ),
            idempotency_key or uuid4(),
            actor=ActorContext.agent(owner_user_id=owner_user_id, player_id=player_id),
            now=now,
        )
