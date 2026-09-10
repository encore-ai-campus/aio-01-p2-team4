"""게임 플레이어와 시나리오 개인 단서를 저장하는 PostgreSQL 저장소."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb


@dataclass(frozen=True, slots=True)
class PlayerInsert:
    """game_players의 생성 시점 값을 명시적으로 묶은 내부 입력."""

    player_id: UUID
    user_id: UUID | None
    kind: str
    seat: int
    display_name: str
    role: str
    faction: str
    persona_id: str | None
    custom_role_name: str | None = None
    custom_role_catalog_version: str | None = None
    custom_ability_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ScenarioFactInsert:
    """플레이어 한 명에게 확정된 ALIBI 또는 OBSERVATION 입력."""

    fact_id: UUID
    player_id: UUID
    fact_kind: str
    template_id: UUID
    rendered_text: str
    subject_player_id: UUID | None = None


class PostgresPlayerRepository:
    """계산이 끝난 플레이어와 단서를 같은 transaction cursor로 INSERT한다."""

    def insert_players(
        self,
        cursor: Any,
        *,
        game_id: UUID,
        players: list[PlayerInsert],
    ) -> None:
        """6~9명의 플레이어를 정본 컬럼에 저장한다."""

        _validate_players(players)
        for player in players:
            cursor.execute(
                """
                INSERT INTO public.game_players (
                    id, game_id, user_id, kind, seat, display_name,
                    role, faction, alive, persona_id, custom_role_name,
                    custom_role_catalog_version, custom_ability_ids
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s, %s, %s, %s)
                """,
                (
                    player.player_id,
                    game_id,
                    player.user_id,
                    player.kind,
                    player.seat,
                    player.display_name,
                    player.role,
                    player.faction,
                    player.persona_id,
                    player.custom_role_name,
                    player.custom_role_catalog_version,
                    Jsonb(list(player.custom_ability_ids)) if player.custom_ability_ids else None,
                ),
            )

    def insert_facts(
        self,
        cursor: Any,
        *,
        game_id: UUID,
        facts: list[ScenarioFactInsert],
    ) -> None:
        """렌더링이 끝난 개인 단서를 역할 정보 없이 저장한다."""

        _validate_facts(facts)
        for fact in facts:
            cursor.execute(
                """
                INSERT INTO public.player_scenario_facts (
                    id, game_id, player_id, fact_kind, template_id,
                    rendered_text, subject_player_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    fact.fact_id,
                    game_id,
                    fact.player_id,
                    fact.fact_kind,
                    fact.template_id,
                    fact.rendered_text,
                    fact.subject_player_id,
                ),
            )

    def list_players(self, cursor: Any, *, game_id: UUID) -> list[Mapping[str, Any]]:
        """snapshot 복원에 필요한 플레이어 상태를 좌석 순서로 읽는다."""

        cursor.execute(
            """
            SELECT id, game_id, user_id, kind, seat, display_name, role, faction,
                   alive, persona_id, eliminated_phase, eliminated_round,
                   custom_role_name, custom_role_catalog_version, custom_ability_ids,
                   created_at, updated_at
            FROM public.game_players
            WHERE game_id = %s
            ORDER BY seat
            """,
            (game_id,),
        )
        return list(cursor.fetchall())

    def get_kind(self, cursor: Any, *, game_id: UUID, player_id: UUID) -> str | None:
        """특정 게임 플레이어의 공개 실행 종류를 읽는다.

        AI 차례 여부처럼 실행 조합에 필요한 원장 조회도 서비스가 SQL을 직접
        작성하지 않도록 플레이어 저장소가 query와 row 변환을 함께 소유한다.
        존재하지 않는 플레이어는 ``None``으로 반환해 호출부가 안전하게 차례를
        무시할 수 있게 한다.
        """

        cursor.execute(
            """
            SELECT kind
            FROM public.game_players
            WHERE game_id = %s AND id = %s
            """,
            (game_id, player_id),
        )
        row = cursor.fetchone()
        return None if row is None else str(row["kind"])

    def update_eliminated_players(self, cursor: Any, *, game_id: UUID, players: list[Any], phase: str, round: int) -> None:
        """엔진에서 사망 확정된 플레이어를 DB 원장에 반영한다.

        GameState는 transaction 안에서 계산되는 임시 규칙 상태이므로, snapshot이
        다음 요청에서도 같은 생존자를 복원하려면 game_players에도 함께 기록해야
        한다. 생존 플레이어는 갱신하지 않아 불필요한 row 변경을 줄인다.
        """

        allowed_phases = {
            "DAY_DISCUSSION", "NIGHT_ACTION", "DAY_VOTE", "REVOTE",
            "FINAL_DISCUSSION", "FINAL_ACCUSATION",
        }
        # 엔진은 마지막 처리를 마친 뒤 phase를 ENDED로 바꾼다. DB의 기존
        # elimination CHECK는 ENDED를 저장하지 않으므로 최종 지목 단계로
        # 정규화하고, migration을 바꾸지 않은 채 종료 결과를 기록한다.
        persisted_phase = phase if phase in allowed_phases else "FINAL_ACCUSATION"
        persisted_round = min(max(round, 1), 5)
        for player in players:
            if player.alive:
                continue
            cursor.execute(
                """
                UPDATE public.game_players
                SET alive = FALSE, eliminated_phase = %s, eliminated_round = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE game_id = %s AND id = %s AND alive = TRUE
                """,
                (persisted_phase, persisted_round, game_id, player.player_id),
            )

    def list_player_facts(
        self,
        cursor: Any,
        *,
        game_id: UUID,
        player_id: UUID,
    ) -> list[Mapping[str, Any]]:
        """인간 플레이어에게만 보낼 개인 단서를 읽는다."""

        cursor.execute(
            """
            SELECT id, fact_kind, template_id, rendered_text, subject_player_id,
                   created_at
            FROM public.player_scenario_facts
            WHERE game_id = %s AND player_id = %s
            ORDER BY fact_kind
            """,
            (game_id, player_id),
        )
        return list(cursor.fetchall())


def _validate_players(players: list[PlayerInsert]) -> None:
    """DB에 보내기 전에 인원·좌석·HUMAN/AI 식별 규칙을 검사한다."""

    if not 6 <= len(players) <= 9:
        raise ValueError("Game creation requires 6 to 9 players")
    if len({player.player_id for player in players}) != len(players):
        raise ValueError("Player IDs must be unique")
    if {player.seat for player in players} != set(range(1, len(players) + 1)):
        raise ValueError("Player seats must be consecutive from 1")

    human_count = 0
    for player in players:
        if not player.display_name.strip() or len(player.display_name) > 40:
            raise ValueError("Player display name is invalid")
        if player.kind == "HUMAN":
            human_count += 1
            if player.user_id is None or player.persona_id is not None:
                raise ValueError("Human player identity is invalid")
        elif player.kind == "AI":
            if player.user_id is not None or not player.persona_id:
                raise ValueError("AI player identity is invalid")
        else:
            raise ValueError("Player kind is invalid")
    if human_count != 1:
        raise ValueError("Game creation requires exactly one human player")


def _validate_facts(facts: list[ScenarioFactInsert]) -> None:
    """같은 플레이어에게 같은 종류의 단서가 중복되지 않게 검사한다."""

    unique_keys = {(fact.player_id, fact.fact_kind) for fact in facts}
    if len(unique_keys) != len(facts):
        raise ValueError("Player scenario facts must be unique by kind")
    for fact in facts:
        if fact.fact_kind not in {"ALIBI", "OBSERVATION"}:
            raise ValueError("Scenario fact kind is invalid")
        if not fact.rendered_text.strip() or len(fact.rendered_text) > 240:
            raise ValueError("Rendered scenario fact is invalid")
