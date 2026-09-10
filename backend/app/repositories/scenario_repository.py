"""승인된 시나리오와 개인 단서 template을 읽는 PostgreSQL 저장소."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID


class PostgresScenarioRepository:
    """게임 생성에 필요한 정적 콘텐츠만 조회한다.

    시나리오 선택 자체는 seed를 사용하는 서비스가 담당한다. 저장소는 활성화되고
    승인된 후보를 ID 순서로 돌려줘 같은 입력에서 선택 순서가 흔들리지 않게 한다.
    """

    def list_active(
        self,
        cursor: Any,
        *,
        scenario_version: str,
    ) -> list[Mapping[str, Any]]:
        """사용 가능한 승인 시나리오를 안정적인 순서로 반환한다."""

        cursor.execute(
            """
            SELECT id, version, title, background, victim, locations, content_hash
            FROM public.scenario_catalog
            WHERE version = %s
              AND active = TRUE
              AND approved_at IS NOT NULL
            ORDER BY id
            """,
            (scenario_version,),
        )
        return list(cursor.fetchall())

    def last_created_scenario_id(
        self,
        cursor: Any,
        *,
        owner_user_id: UUID,
        scenario_version: str,
    ) -> str | None:
        """직전 생성 게임의 시나리오를 찾아 연속 중복 선택을 피하게 한다."""

        cursor.execute(
            """
            SELECT scenario_id
            FROM public.games
            WHERE owner_user_id = %s
              AND scenario_version = %s
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (owner_user_id, scenario_version),
        )
        row = cursor.fetchone()
        return str(row["scenario_id"]) if row is not None else None

    def list_active_templates(
        self,
        cursor: Any,
        *,
        scenario_id: str,
    ) -> list[Mapping[str, Any]]:
        """ALIBI와 OBSERVATION template을 고정 key 순서로 반환한다."""

        cursor.execute(
            """
            SELECT id, scenario_id, template_kind, template_key,
                   text_template, subject_mode
            FROM public.scenario_templates
            WHERE scenario_id = %s
              AND active = TRUE
            ORDER BY template_kind, template_key, id
            """,
            (scenario_id,),
        )
        return list(cursor.fetchall())

