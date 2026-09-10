"""PostgreSQL ``feedback`` 테이블 저장소."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb


class PostgresFeedbackRepository:
    """검증이 끝난 피드백을 저장하고 게임별 중복 여부를 조회한다."""

    def find_game_feedback(
        self,
        cursor: Any,
        *,
        user_id: UUID,
        game_id: UUID,
    ) -> Mapping[str, Any] | None:
        """같은 사용자의 같은 게임 피드백을 조회한다."""

        cursor.execute(
            """
            SELECT id
            FROM public.feedback
            WHERE user_id = %s
              AND game_id = %s
              AND feedback_type = 'GAME'
            LIMIT 1
            """,
            (user_id, game_id),
        )
        return cursor.fetchone()

    def insert(
        self,
        cursor: Any,
        *,
        user_id: UUID,
        feedback_type: str,
        game_id: UUID | None,
        rating: int,
        comment: str | None,
        tags: list[str],
    ) -> Mapping[str, Any]:
        """피드백을 저장하고 공개 응답에 필요한 식별자와 시각을 반환한다."""

        cursor.execute(
            """
            INSERT INTO public.feedback (
                user_id, feedback_type, game_id, rating, comment, tags
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, feedback_type, created_at
            """,
            (user_id, feedback_type, game_id, rating, comment, Jsonb(tags)),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("feedback 저장 결과가 반환되지 않았습니다.")
        return row
