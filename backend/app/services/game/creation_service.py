"""게임 생성 transaction과 초기 게임 조합을 담당하는 모듈."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any
from uuid import UUID, uuid4

from psycopg.rows import dict_row

from backend.app.game_engine.rng import DeterministicRng
from backend.app.core.errors import ApiError
from backend.app.infrastructure.transaction import lock_idempotency
from backend.app.game_engine.engine import ROLE_COUNTS, GameEngine
from backend.app.models.enums import Faction, PlayerKind, PlayerRole
from backend.app.models.game_state import GameState
from backend.app.repositories.player_repository import PlayerInsert, ScenarioFactInsert
from backend.app.schemas.game_schema import CreateGameRequest
from backend.app.services.game.helpers import create_game_result, request_hash
from backend.app.services.game.postgres_helpers import find_replay


def create_game(
    service: Any,
    owner_user_id: UUID,
    payload: CreateGameRequest,
    idempotency_key: UUID,
) -> tuple[dict[str, Any], bool]:
    """게임 생성에 필요한 모든 row와 공개 원장을 하나의 transaction으로 확정한다."""

    hash_body = payload.model_dump(mode="json")
    if payload.mode == "STANDARD":
        # migration 전 생성 요청·receipt와 동일한 hash를 유지한다.
        hash_body.pop("mode", None)
        hash_body.pop("custom_role", None)
    request_hash_value = request_hash(hash_body)
    try:
        with service._transactions.transaction() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                lock_idempotency(cursor, "USER", owner_user_id, idempotency_key)
                lock_idempotency(cursor, "GAME_CREATE", owner_user_id)
                replay = find_replay(
                    service,
                    cursor,
                    owner_user_id=owner_user_id,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash_value,
                    route_scope=service.ROUTE_SCOPE,
                )
                if replay is not None:
                    return replay, True
                service._users.ensure_user_in_transaction(cursor, owner_user_id)
                state, scenario, player_rows, fact_rows = build_initial_game(
                    service, cursor, owner_user_id=owner_user_id, payload=payload
                )
                encrypted_seed = service._keyring.encrypt_seed(state.seed)
                service._games.insert_initial_game(
                    cursor,
                    state=state,
                    owner_user_id=owner_user_id,
                    scenario_version=payload.scenario_version,
                    scenario_id=str(scenario["id"]),
                    scenario_content_hash=str(scenario["content_hash"]),
                    encrypted_seed=encrypted_seed,
                    agent_config_version=service.AGENT_CONFIG_VERSION,
                )
                service._players.insert_players(cursor, game_id=state.game_id, players=player_rows)
                service._players.insert_facts(cursor, game_id=state.game_id, facts=fact_rows)
                event = service._events.append(
                    cursor,
                    game_id=state.game_id,
                    state_version=state.state_version,
                    event_type="GAME_CREATED",
                    audience="PUBLIC",
                    payload={
                        "game_id": str(state.game_id),
                        "status": state.status.value,
                        "phase": state.phase.value,
                        "state_version": state.state_version,
                    },
                )
                service._outbox.enqueue(cursor, UUID(str(event["id"])))
                result = create_game_result(state)
                service._receipts.insert(
                    cursor,
                    principal_type="USER",
                    principal_id=owner_user_id,
                    idempotency_key=idempotency_key,
                    route_scope=service.ROUTE_SCOPE,
                    game_id=state.game_id,
                    request_hash=request_hash_value,
                    result_state_version=state.state_version,
                    http_status=201,
                    result_body=result,
                )
                return result, False
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(
            status_code=503,
            code="DEPENDENCY_UNAVAILABLE",
            message="게임 저장소를 사용할 수 없습니다.",
            retryable=True,
        ) from exc


def build_initial_game(
    service: Any,
    cursor: Any,
    *,
    owner_user_id: UUID,
    payload: CreateGameRequest,
) -> tuple[GameState, Mapping[str, Any], list[PlayerInsert], list[ScenarioFactInsert]]:
    """seed로 시나리오·persona·개인 단서를 확정해 DB 입력으로 변환한다."""

    human_player_id = uuid4()
    state = GameEngine.new_game(
        [(human_player_id, PlayerKind.HUMAN)]
        + [(uuid4(), PlayerKind.AI) for _ in range(payload.player_count - 1)],
        game_id=uuid4(),
    )
    for player in state.players:
        player.display_name = f"플레이어 {player.seat}"
    state.mode = payload.mode
    if payload.custom_role is not None:
        human = state.player_by_id[human_player_id]
        desired_mafia = payload.custom_role.faction == "MAFIA"
        human.role = PlayerRole.MAFIA if desired_mafia else PlayerRole.CITIZEN
        mafia_count = ROLE_COUNTS[payload.player_count][0] - int(desired_mafia)
        ai_roles = (
            [PlayerRole.MAFIA] * mafia_count
            + [PlayerRole.DETECTIVE, PlayerRole.DOCTOR]
            + [PlayerRole.CITIZEN] * (payload.player_count - 3 - mafia_count)
        )
        ai_players = DeterministicRng(state.seed).shuffle(
            [player for player in state.players if player.kind is PlayerKind.AI],
            "custom-role-assignment",
        )
        for player, role in zip(ai_players, ai_roles, strict=True):
            player.role = role
        human.custom_role_name = payload.custom_role.name
        human.custom_role_catalog_version = payload.custom_role.catalog_version
        human.custom_ability_ids = tuple(payload.custom_role.ability_ids)
        human.custom_faction = Faction(payload.custom_role.faction)

    candidates = service._scenarios.list_active(cursor, scenario_version=payload.scenario_version)
    last_scenario_id = service._scenarios.last_created_scenario_id(
        cursor, owner_user_id=owner_user_id, scenario_version=payload.scenario_version
    )
    eligible = [item for item in candidates if item["id"] != last_scenario_id] or candidates
    if not eligible:
        raise RuntimeError("No active scenario is available")
    rng = DeterministicRng(state.seed)
    scenario = rng.choice(eligible, "scenario-selection")

    personas = service._agents.list_active_personas(cursor, version=service.AGENT_CONFIG_VERSION)
    if not personas:
        raise RuntimeError("No active persona is available")
    ordered_personas = rng.shuffle(personas, "persona-assignment")
    templates = service._scenarios.list_active_templates(cursor, scenario_id=str(scenario["id"]))
    alibis = [item for item in templates if item["template_kind"] == "ALIBI"]
    observations = [item for item in templates if item["template_kind"] == "OBSERVATION"]
    if len(alibis) < payload.player_count or len(observations) < payload.player_count:
        raise RuntimeError("Scenario templates are insufficient")
    selected_alibis = rng.shuffle(alibis, "alibi-template")[: payload.player_count]
    selected_observations = rng.shuffle(observations, "observation-template")[: payload.player_count]

    player_rows: list[PlayerInsert] = []
    fact_rows: list[ScenarioFactInsert] = []
    for index, player in enumerate(state.players):
        persona_id = None
        if player.kind is PlayerKind.AI:
            persona_id = str(ordered_personas[(player.seat - 2) % len(ordered_personas)]["id"])
        player_rows.append(
            PlayerInsert(
                player_id=player.player_id,
                user_id=owner_user_id if player.kind is PlayerKind.HUMAN else None,
                kind=player.kind.value,
                seat=player.seat,
                display_name=player.display_name,
                role=player.role.value,
                faction=player.faction.value,
                persona_id=persona_id,
                custom_role_name=player.custom_role_name,
                custom_role_catalog_version=player.custom_role_catalog_version,
                custom_ability_ids=player.custom_ability_ids,
            )
        )
        fact_rows.append(
            fact_from_template(
                player_id=player.player_id, fact_kind="ALIBI", template=selected_alibis[index],
                seat=player.seat, subject_player_id=None,
            )
        )
        observation_template = selected_observations[index]
        subject_player_id = None
        if observation_template["subject_mode"] == "SEAT":
            subject_player_id = rng.choice(
                [candidate.player_id for candidate in state.players if candidate.player_id != player.player_id],
                f"observation-subject:{player.player_id}",
            )
        fact_rows.append(
            fact_from_template(
                player_id=player.player_id, fact_kind="OBSERVATION", template=observation_template,
                seat=player.seat, subject_player_id=subject_player_id,
            )
        )
    return state, scenario, player_rows, fact_rows


def fact_from_template(
    *, player_id: UUID, fact_kind: str, template: Mapping[str, Any], seat: int,
    subject_player_id: UUID | None,
) -> ScenarioFactInsert:
    """템플릿을 개인 단서 row로 변환한다."""

    return ScenarioFactInsert(
        fact_id=uuid4(), player_id=player_id, fact_kind=fact_kind,
        template_id=UUID(str(template["id"])),
        rendered_text=str(template["text_template"]).replace("{{seat}}", str(seat)),
        subject_player_id=subject_player_id,
    )

from backend.app.services.game_service import PostgresGameCreationService

__all__ = ["PostgresGameCreationService"]
