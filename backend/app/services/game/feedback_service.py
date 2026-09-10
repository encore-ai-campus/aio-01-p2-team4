"""PostgreSQL feedback 요청의 검증·멱등성·저장을 조정한다."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row

from backend.app.core.errors import ApiError
from backend.app.infrastructure.transaction import TransactionManager, lock_idempotency
from backend.app.repositories.feedback_repository import PostgresFeedbackRepository
from backend.app.repositories.game_repository import PostgresGameRepository
from backend.app.repositories.receipt_repository import PostgresReceiptRepository
from backend.app.repositories.user_repository import PostgresUserRepository
from backend.app.schemas.feedback_schema import FeedbackRequest
from backend.app.services.game.helpers import request_hash


class PostgresFeedbackService:
    """feedback API를 DB transaction 하나로 처리하는 업무 서비스."""

    ROUTE_SCOPE = "POST /api/v1/feedback"
    PRINCIPAL_TYPE = "USER"

    def __init__(
        self,
        *,
        transactions: TransactionManager,
        users: PostgresUserRepository,
        games: PostgresGameRepository,
        feedback: PostgresFeedbackRepository | None = None,
        receipts: PostgresReceiptRepository | None = None,
    ) -> None:
        """피드백과 멱등성 원장이 같은 transaction을 사용하게 한다."""

        self._transactions = transactions
        self._users = users
        self._games = games
        self._feedback = feedback or PostgresFeedbackRepository()
        self._receipts = receipts or PostgresReceiptRepository()

    def submit(
        self,
        user_id: UUID,
        payload: FeedbackRequest,
        idempotency_key: UUID,
    ) -> tuple[dict[str, Any], bool]:
        """사용자 준비부터 feedback·receipt 저장까지 원자적으로 수행한다."""

        payload_hash = request_hash(payload.model_dump(mode="json"))
        with self._transactions.transaction() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                lock_idempotency(cursor, self.PRINCIPAL_TYPE, user_id, idempotency_key)
                previous = self._receipts.find(
                    cursor,
                    principal_type=self.PRINCIPAL_TYPE,
                    principal_id=user_id,
                    idempotency_key=idempotency_key,
                )
                if previous is not None:
                    if (
                        previous["request_hash"] != payload_hash
                        or previous["route_scope"] != self.ROUTE_SCOPE
                    ):
                        raise ApiError(
                            status_code=409,
                            code="IDEMPOTENCY_KEY_REUSED",
                            message="같은 Idempotency-Key가 다른 요청에 사용되었습니다.",
                        )
                    return dict(previous["result_body"]), True

                self._users.ensure_user_in_transaction(cursor, user_id)
                game_id = payload.game_id
                if payload.feedback_type == "GAME":
                    assert game_id is not None
                    game = self._games.lock_game(cursor, game_id)
                    if game is None or game["owner_user_id"] != user_id:
                        raise ApiError(
                            status_code=404,
                            code="GAME_NOT_FOUND",
                            message="게임을 찾을 수 없습니다.",
                        )
                    if game["status"] != "COMPLETED":
                        raise ApiError(
                            status_code=409,
                            code="FEEDBACK_GAME_NOT_COMPLETED",
                            message="종료된 게임에만 게임별 의견을 남길 수 있습니다.",
                        )
                    existing = self._feedback.find_game_feedback(
                        cursor,
                        user_id=user_id,
                        game_id=game_id,
                    )
                    if existing is not None:
                        raise ApiError(
                            status_code=409,
                            code="FEEDBACK_ALREADY_SUBMITTED",
                            message="이 게임에는 이미 게임별 의견을 남겼습니다.",
                        )

                row = self._feedback.insert(
                    cursor,
                    user_id=user_id,
                    feedback_type=payload.feedback_type,
                    game_id=game_id,
                    rating=payload.rating,
                    comment=payload.comment,
                    tags=payload.tags,
                )
                created_at = row["created_at"]
                if isinstance(created_at, datetime):
                    created_at = created_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
                result = {
                    "feedback_id": str(row["id"]),
                    "feedback_type": row["feedback_type"],
                    "created_at": created_at,
                }
                self._receipts.insert(
                    cursor,
                    principal_type=self.PRINCIPAL_TYPE,
                    principal_id=user_id,
                    idempotency_key=idempotency_key,
                    route_scope=self.ROUTE_SCOPE,
                    game_id=game_id,
                    request_hash=payload_hash,
                    result_state_version=None,
                    http_status=201,
                    result_body=result,
                )
                return result, False
