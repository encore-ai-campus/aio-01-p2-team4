"""밤 행동·투표의 제출, 마감, 확정 원장을 같은 PostgreSQL transaction으로 처리한다."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row

from backend.app.core.errors import ApiError
from backend.app.game_engine.engine import GameEngine
from backend.app.game_engine.errors import RuleViolation
from backend.app.game_engine.fallback import auto_night_target, auto_vote_target
from backend.app.game_engine.rng import DeterministicRng
from backend.app.game_engine.rules.night_rules import ABILITY_ACTIONS, ability_action, required_actors, role_action
from backend.app.game_engine.rules.vote_rules import vote_weight
from backend.app.infrastructure.transaction import lock_idempotency
from backend.app.models.enums import GamePhase, GameStatus, NightActionType, PlayerKind, PlayerRole
from backend.app.models.game_state import GameState
from backend.app.repositories.action_repository import ActionSubmissionInsert
from backend.app.repositories.agent_repository import AgentReservation
from backend.app.schemas.command_schema import GameCommandRequest
from backend.app.services.game_service import PostgresBeginGameService
from backend.app.services.game.actor_context import ActorContext
from backend.app.services.game.helpers import request_hash
from backend.app.services.game.postgres_helpers import find_replay, restore_action_submissions, restore_locked_game
from backend.app.services.game.service_errors import rule_error
from backend.app.services.game.window_service import is_expired_window, next_window, validate_action_window


class PostgresActionCommandService(PostgresBeginGameService):
    """개별 제출과 AI batch가 같은 검증·해소·저장 경계를 사용한다."""

    def submit(self, owner_user_id: UUID, game_id: UUID, payload: GameCommandRequest,
               idempotency_key: UUID, *, actor: ActorContext | None = None,
               now: datetime | None = None) -> tuple[dict[str, Any], bool]:
        """인간 또는 단일 AI의 첫 유효 제출을 저장한다."""

        if payload.type not in {"SUBMIT_NIGHT_ACTION", "SUBMIT_VOTE"}:
            raise ValueError("행동 command 종류가 올바르지 않습니다.")
        if actor is not None and actor.owner_user_id != owner_user_id:
            raise ApiError(status_code=403, code="ACTOR_NOT_ALLOWED", message="Agent 소유자가 일치하지 않습니다.")
        return self._submit_actions(owner_user_id, game_id, payload.type,
                                    [{"player_id": actor.player_id if actor else None, "target_player_id": payload.target_player_id,
                                      "ability_id": payload.ability_id}],
                                    expected_state_version=payload.expected_state_version,
                                    window_id=payload.window_id, idempotency_key=idempotency_key,
                                    body_hash=request_hash(payload.receipt_body()),
                                    agent=actor is not None, now=now)

    def submit_agent_night_actions(self, owner_user_id: UUID, game_id: UUID,
                                   actions: list[dict[str, UUID]], *, expected_state_version: int,
                                   window_id: UUID, idempotency_key: UUID,
                                   now: datetime | None = None) -> tuple[dict[str, Any], bool]:
        """인간·기존 AI 제출을 유지하면서 아직 미제출인 AI 밤 역할을 반영한다."""

        return self._submit_agent_batch(owner_user_id, game_id, "SUBMIT_NIGHT_ACTION", actions,
                                        expected_state_version, window_id, idempotency_key, now)

    def submit_agent_votes(self, owner_user_id: UUID, game_id: UUID,
                           actions: list[dict[str, UUID]], *, expected_state_version: int,
                           window_id: UUID, idempotency_key: UUID,
                           now: datetime | None = None,
                           reservation: AgentReservation | None = None) -> tuple[dict[str, Any], bool]:
        """일반·재투표·최종 지목의 모든 AI 표를 동일하게 누적한다."""

        return self._submit_agent_batch(owner_user_id, game_id, "SUBMIT_VOTE", actions,
                                        expected_state_version, window_id, idempotency_key, now,
                                        reservation=reservation)

    def _submit_agent_batch(self, owner_user_id: UUID, game_id: UUID, command: str,
                            actions: list[dict[str, UUID]], version: int, window: UUID,
                            key: UUID, now: datetime | None,
                            *, reservation: AgentReservation | None = None) -> tuple[dict[str, Any], bool]:
        """batch 입력을 닫힌 형식으로 검증하고 command 종류까지 멱등 hash에 묶는다."""

        if not actions or any(set(item) != {"player_id", "target_player_id"} or not all(isinstance(value, UUID) for value in item.values()) for item in actions):
            raise ApiError(status_code=422, code="INVALID_REQUEST", message="AI 행동 형식이 올바르지 않습니다.")
        if len({item["player_id"] for item in actions}) != len(actions):
            raise ApiError(status_code=409, code="ACTION_ALREADY_SUBMITTED", message="같은 AI 행동이 중복됐습니다.")
        body_hash = request_hash({"type": command, "actions": [{key: str(value) for key, value in item.items()} for item in actions], "expected_state_version": version, "window_id": str(window)})
        return self._submit_actions(owner_user_id, game_id, command, actions,
                                    expected_state_version=version, window_id=window,
                                    idempotency_key=key, body_hash=body_hash, agent=True, now=now,
                                    reservation=reservation)

    def _submit_actions(self, owner_user_id: UUID, game_id: UUID, command: str,
                        actions: list[dict[str, Any]], *, expected_state_version: int,
                        window_id: UUID, idempotency_key: UUID, body_hash: str,
                        agent: bool, now: datetime | None,
                        reservation: AgentReservation | None = None) -> tuple[dict[str, Any], bool]:
        """행 잠금 뒤 소유권·멱등성·deadline·actor를 확인하고 한 버전으로 저장한다."""

        principal_type = "AGENT" if agent else "USER"
        principal_id = actions[0]["player_id"] if agent else owner_user_id
        route_scope = f"POST /api/v1/games/{game_id}/{'agent-commands' if agent else 'commands'}"
        try:
            with self._transactions.transaction() as connection:
                with connection.cursor(row_factory=dict_row) as cursor:
                    lock_idempotency(cursor, principal_type, principal_id, idempotency_key)
                    game_row = self._owned_game(cursor, owner_user_id, game_id)
                    previous = self._receipts.find(cursor, principal_type=principal_type, principal_id=principal_id, idempotency_key=idempotency_key)
                    if previous is not None:
                        if previous["request_hash"] != body_hash or previous["route_scope"] != route_scope:
                            raise ApiError(status_code=409, code="IDEMPOTENCY_KEY_REUSED", message="같은 Idempotency-Key가 다른 요청에 사용되었습니다.")
                        return dict(previous["result_body"]), True
                    state, human_id = restore_locked_game(self, cursor, game_row)
                    current_version = state.state_version
                    valid_version = (
                        self._actions.vote_version_is_current(
                            cursor, game_id=game_id, window_id=window_id,
                            expected=expected_state_version, current=current_version,
                        ) if agent and command == "SUBMIT_VOTE"
                        else current_version == expected_state_version
                    )
                    if not valid_version:
                        raise ApiError(status_code=409, code="STALE_STATE_VERSION", message="게임 상태가 변경되었습니다.", details={"current_state_version": state.state_version})
                    window = self._actions.current_window(cursor, game_id=game_id)
                    # worker 조회와 DB 잠금 대기 사이에 마감될 수 있으므로 여기서 시각을 읽는다.
                    current_time = now or datetime.now(UTC)
                    if reservation is not None:
                        # 완료된 모델 결과라도 commit 전에 token이 교체되거나 lease가
                        # 끝났으면 반영하지 않는다. 게임 잠금은 예약 갱신과 같은 순서다.
                        cursor.execute(
                            """
                            SELECT 1 FROM public.agent_jobs
                            WHERE id = %s AND lease_token = %s AND game_id = %s
                              AND window_id = %s AND player_id = %s AND job_kind = 'VOTE'
                              AND reserved_state_version = %s AND status IN ('SUCCEEDED', 'FALLBACK')
                              AND lease_expires_at > %s
                            """, (reservation.job_id, reservation.lease_token, game_id, window_id,
                                  principal_id, expected_state_version, current_time),
                        )
                        if cursor.fetchone() is None:
                            raise ApiError(status_code=409, code="STALE_STATE_VERSION", message="AI 투표 예약이 만료되거나 변경되었습니다.")
                    payload = GameCommandRequest(type=command, expected_state_version=expected_state_version,
                                                 window_id=window_id, target_player_id=actions[0]["target_player_id"])
                    validate_action_window(state, window, payload, now=current_time)
                    if (command == "SUBMIT_NIGHT_ACTION") != (state.phase is GamePhase.NIGHT_ACTION):
                        raise ApiError(status_code=409, code="INVALID_PHASE", message="현재 단계에 맞지 않는 행동입니다.")
                    submissions = self._actions.list_window_action_submissions(cursor, window_id=window_id)
                    restore_action_submissions(state, submissions)
                    phase, round_number = state.phase.value, state.round
                    for item in actions:
                        player_id = item["player_id"] if agent else human_id
                        if agent and (player_id not in state.player_by_id or state.player_by_id[player_id].kind is not PlayerKind.AI):
                            raise ApiError(status_code=403, code="ACTOR_NOT_ALLOWED", message="Agent actor가 아닙니다.")
                        action_type = self._submit_one(
                            state, player_id, item["target_player_id"],
                            ability_id=item.get("ability_id"),
                        )
                        submission = {"actor_player_id": player_id, "target_player_id": item["target_player_id"], "action_type": action_type, "source": "AGENT" if agent else "HUMAN", "ability_id": item.get("ability_id")}
                        self._store_submission(cursor, state, window_id, submission, expected_state_version)
                        submissions.append(submission)
                    required = required_actors(state) if phase == "NIGHT_ACTION" else state.alive_players
                    recorded = state.night_actions if phase == "NIGHT_ACTION" else state.votes
                    ready = all(player.player_id in recorded for player in required)
                    resolution = self._resolve(state, phase, round_number, submissions, force=False) if ready else None
                    # 개별 AI 표는 제출 원장에만 누적한다. 공개 version을 올리면
                    # 병렬 판단과 아직 제출하지 않은 인간 화면까지 stale로 바뀐다.
                    private_vote = agent and command == "SUBMIT_VOTE" and resolution is None
                    if private_vote:
                        state.state_version = current_version
                    else:
                        self._persist_action(cursor, state, window, submissions, resolution,
                                             current_version, current_time, game_row.get("fast_forward_enabled") is True,
                                             phase, round_number, user_action=not agent)
                    result = self._result(game_id, command, expected_state_version, idempotency_key,
                                          result_version=state.state_version)
                    self._receipts.insert(cursor, principal_type=principal_type, principal_id=principal_id,
                                          idempotency_key=idempotency_key, route_scope=route_scope,
                                          game_id=game_id, request_hash=body_hash,
                                          result_state_version=state.state_version, http_status=200, result_body=result)
                    return result, False
        except ApiError:
            raise
        except RuleViolation as exc:
            raise rule_error(exc) from exc
        except Exception as exc:
            raise ApiError(status_code=503, code="DEPENDENCY_UNAVAILABLE", message="게임 행동을 저장할 수 없습니다.", retryable=True) from exc

    @staticmethod
    def _submit_one(state: GameState, actor_id: UUID, target_id: UUID,
                    *, ability_id: str | None = None) -> str:
        """역할이나 phase를 입력으로 신뢰하지 않고 현재 규칙에서 행동 종류를 정한다."""

        engine = GameEngine()
        if state.phase is GamePhase.NIGHT_ACTION:
            action = ability_action(state, actor_id, ability_id)
            engine.submit_night_action(state, actor_id, action, target_id)
            return action.value
        if state.phase is GamePhase.FINAL_ACCUSATION:
            vote_weight(state, actor_id, ability_id)
            engine.submit_final_accusation(state, actor_id, target_id)
        else:
            engine.submit_vote(state, actor_id, target_id, ability_id=ability_id)
        return "VOTE"

    def _owned_game(self, cursor: Any, owner_user_id: UUID, game_id: UUID) -> Mapping[str, Any]:
        """receipt를 재사용하기 전에도 잠근 게임의 현재 소유권을 확인한다."""

        game = self._games.lock_game(cursor, game_id)
        if game is None or UUID(str(game["owner_user_id"])) != owner_user_id:
            raise ApiError(status_code=404, code="GAME_NOT_FOUND", message="게임을 찾을 수 없습니다.")
        return game

    @staticmethod
    def _result(game_id: UUID, command: str, version: int, key: UUID | None = None,
                *, result_version: int | None = None) -> dict[str, Any]:
        """재사용 가능한 불변 terminal 응답에 snapshot이나 deadline을 섞지 않는다."""

        result = {"command_type": command, "accepted_state_version": version,
                  "result_state_version": version + 1 if result_version is None else result_version,
                  "sync_url": f"/api/v1/games/{game_id}/sync"}
        if key is not None:
            result["command_id"] = str(key)
        return result

    def _store_submission(self, cursor: Any, state: GameState, window_id: UUID,
                          row: Mapping[str, Any], version: int) -> None:
        """수동·자동 선택을 동일한 immutable 제출 원장에 기록한다."""

        self._actions.insert_submission(cursor, ActionSubmissionInsert(
            game_id=state.game_id, window_id=window_id, actor_player_id=UUID(str(row["actor_player_id"])),
            action_type=str(row["action_type"]), target_player_id=UUID(str(row["target_player_id"])),
            message=None, source=str(row["source"]), observed_state_version=version, ability_id=row.get("ability_id")))

    def auto_resolve_citizen_night(self, owner_user_id: UUID, game_id: UUID, *, now: datetime | None = None) -> dict[str, Any] | None:
        """기존 runtime 호출을 역할과 무관한 밤 만료 처리로 연결한다."""

        return self.auto_resolve_expired_night(owner_user_id, game_id, now=now)

    def auto_resolve_expired_night(self, owner_user_id: UUID, game_id: UUID, *, now: datetime | None = None) -> dict[str, Any] | None:
        """기존 제출을 복원하고 실제 마감된 밤만 원자적으로 해소한다."""

        return self._auto_resolve_expired(owner_user_id, game_id, night=True, now=now)

    def auto_resolve_expired_vote(self, owner_user_id: UUID, game_id: UUID, *, now: datetime | None = None) -> dict[str, Any] | None:
        """인간 무응답을 포함한 투표·재투표·최종 지목의 마감을 처리한다."""

        return self._auto_resolve_expired(owner_user_id, game_id, night=False, now=now)

    def _auto_resolve_expired(self, owner_user_id: UUID, game_id: UUID, *, night: bool,
                              now: datetime | None) -> dict[str, Any] | None:
        """worker의 오래된 조회가 새 window를 조기 해소하지 못하게 잠금 뒤 재검사한다."""

        try:
            with self._transactions.transaction() as connection:
                with connection.cursor(row_factory=dict_row) as cursor:
                    game = self._games.lock_game(cursor, game_id)
                    if game is None or UUID(str(game["owner_user_id"])) != owner_user_id:
                        return None
                    state, _ = restore_locked_game(self, cursor, game)
                    phases = {GamePhase.NIGHT_ACTION} if night else {GamePhase.DAY_VOTE, GamePhase.REVOTE, GamePhase.FINAL_ACCUSATION}
                    if state.phase not in phases:
                        return None
                    window = self._actions.current_window(cursor, game_id=game_id)
                    current_time = now or datetime.now(UTC)
                    if not is_expired_window(state, window, current_time):
                        return None
                    accepted_version = state.state_version
                    phase, round_number = state.phase.value, state.round
                    submissions = self._actions.list_window_action_submissions(cursor, window_id=UUID(str(window["id"])))
                    restore_action_submissions(state, submissions)
                    resolution = self._resolve(state, phase, round_number, submissions, force=True)
                    self._persist_action(cursor, state, window, submissions, resolution, accepted_version,
                                         current_time, game.get("fast_forward_enabled") is True,
                                         phase, round_number,
                                         user_action=False)
                    return self._result(game_id, "AUTO_RESOLVE_NIGHT" if night else "AUTO_RESOLVE_VOTE", accepted_version)
        except ApiError:
            raise
        except Exception as exc:
            raise ApiError(status_code=503, code="DEPENDENCY_UNAVAILABLE", message="만료된 행동을 처리할 수 없습니다.", retryable=True) from exc

    def _resolve(self, state: GameState, phase: str, round_number: int,
                 submissions: list[dict[str, Any]], *, force: bool) -> dict[str, Any]:
        """엔진이 임시 선택을 비우기 전에 자동 입력과 확정 결과를 보존한다.

        선택 알고리즘은 규칙 엔진의 fallback/RNG를 사용한다. 진영 자동 공격은
        가상 actor 행을 만들지 않으며 같은 입력으로 엔진 해소 결과를 검증한다.
        """

        alive = state.alive_players
        existing = {UUID(str(row["actor_player_id"])) for row in submissions}
        auto_rows = []
        payload: dict[str, Any] = {"schema_version": 1, "round": round_number, "phase": phase}
        source = "SUBMISSIONS"
        engine = GameEngine()
        if phase == "NIGHT_ACTION":
            if force:
                for actor in required_actors(state):
                    action = role_action(state, actor.player_id)
                    if actor.player_id in existing or (action is NightActionType.ATTACK and not actor.custom_ability_ids):
                        continue
                    target = auto_night_target(state, actor, action)
                    engine.submit_night_action(state, actor.player_id, action, target.player_id)
                    auto_rows.append({"actor_player_id": actor.player_id, "target_player_id": target.player_id, "action_type": action.value, "source": "AUTO", "ability_id": next((item for item in actor.custom_ability_ids if item in ABILITY_ACTIONS), None)})
            choices = [*submissions, *auto_rows]
            attacks = [row for row in choices if row["action_type"] == "ATTACK"]
            targets = sorted({UUID(str(row["target_player_id"])) for row in attacks})
            if targets:
                target = DeterministicRng(state.seed).choice(targets, f"night-attack:{round_number}")
                if len(targets) > 1:
                    source = "TIE_RNG"
            else:
                mafia = next((player for player in alive if player.role is PlayerRole.MAFIA and not player.custom_ability_ids
                              and player.player_id not in state.night_actions), None)
                target = auto_night_target(state, mafia, NightActionType.ATTACK).player_id if mafia else None
                source = "FACTION_AUTO" if mafia else "SUBMISSIONS"
            protected = sorted({
                UUID(str(row["target_player_id"]))
                for row in choices if row["action_type"] == "PROTECT"
            })
            protection = protected[0] if len(protected) == 1 else None
            payload.update({"attack_choices": [self._choice(row) for row in attacks],
                            "resolved_attack_target_player_id": str(target) if target else None,
                            "protect_player_id": str(protection) if protection else None,
                            "protect_player_ids": [str(item) for item in protected],
                            "investigations": [dict(self._choice(row), is_mafia=state.player_by_id[UUID(str(row["target_player_id"]))].faction.value == "MAFIA") for row in choices if row["action_type"] == "INVESTIGATE"],
                            "killed_player_id": str(target) if target and target not in protected else None})
            engine.resolve_night(state, force=force)
            killed = [player.player_id for player in alive if not player.alive]
            if killed != ([target] if target and target not in protected else []):
                raise RuntimeError("밤 엔진 결과와 확정 원장이 다릅니다.")
        else:
            candidates = [player for player in alive if phase != "REVOTE" or player.player_id in state.revote_candidates]
            if force:
                for actor in alive:
                    if actor.player_id in state.votes:
                        continue
                    target = auto_vote_target(state, actor)
                    self._submit_one(state, actor.player_id, target.player_id)
                    auto_rows.append({"actor_player_id": actor.player_id, "target_player_id": target.player_id, "action_type": "VOTE", "source": "AUTO"})
            ballots = [self._vote_choice(state, row, phase=GamePhase(phase)) for row in [*submissions, *auto_rows]]
            counts = Counter()
            for ballot in ballots:
                counts[ballot["target_player_id"]] += vote_weight(
                    state, UUID(ballot["actor_player_id"]), ballot.get("ability_id"), phase=GamePhase(phase),
                )
            highest = max(counts.values())
            leaders = [player.player_id for player in candidates if counts[str(player.player_id)] == highest]
            tied = len(leaders) > 1
            needs_revote = phase == "DAY_VOTE" and tied
            if phase == "FINAL_ACCUSATION":
                if state.status is not GameStatus.COMPLETED:
                    engine.resolve_final_accusation(state, force=False)
                target = state.final_accusation_target
                if tied:
                    source = "TIE_RNG"
            else:
                engine.resolve_vote(state, force=False)
                target = leaders[0] if not tied else None
            payload.update({"ballots": ballots,
                            "counts": [{"target_player_id": str(player.player_id), "vote_count": counts[str(player.player_id)]} for player in candidates],
                            "eliminated_player_id": str(target) if target and phase != "FINAL_ACCUSATION" else None,
                            "tied": tied, "needs_revote": needs_revote,
                            "tied_candidates": [str(value) for value in leaders] if tied else [],
                            "final_target_player_id": str(target) if phase == "FINAL_ACCUSATION" and target else None})
        uses_rng = force or source in {"FACTION_AUTO", "TIE_RNG"}
        proof = DeterministicRng(state.seed).proof_hash(f"resolution:{round_number}:{phase}", request_hash(payload)) if uses_rng else None
        return {"payload": payload, "auto_rows": auto_rows, "source": source, "target": target, "proof": proof}

    @staticmethod
    def _choice(row: Mapping[str, Any]) -> dict[str, Any]:
        """종료 복기에 허용된 actor·대상·자동 선택만 새 object로 복사한다."""

        return {"actor_player_id": str(row["actor_player_id"]), "target_player_id": str(row["target_player_id"]), "is_auto": row["source"] == "AUTO"}

    @staticmethod
    def _vote_choice(state: GameState, row: Mapping[str, Any], *, phase: GamePhase) -> dict[str, Any]:
        """능력 사용은 인간의 검증된 표에만 기록하고 기존 ballot 형식은 유지한다."""

        ability_id = row.get("ability_id")
        vote_weight(state, UUID(str(row["actor_player_id"])), ability_id, phase=phase)
        if ability_id is not None and row["source"] != "HUMAN":
            raise RuleViolation("ABILITY_ID_INVALID")
        ballot = PostgresActionCommandService._choice(row)
        if ability_id is not None:
            ballot["ability_id"] = ability_id
        return ballot

    def _persist_action(self, cursor: Any, state: GameState, window: Mapping[str, Any],
                        submissions: list[dict[str, Any]], resolution: dict[str, Any] | None,
                        version: int, now: datetime, fast_forward_enabled: bool,
                        phase: str, round_number: int, *, user_action: bool) -> None:
        """원장·탈락 원인·상태·다음 window·공개 결과를 같은 transaction에 저장한다."""

        state.state_version = version + 1
        state.updated_at = now
        following: Any = window
        if resolution is not None:
            for row in resolution["auto_rows"]:
                self._store_submission(cursor, state, UUID(str(window["id"])), row, version)
            self._actions.insert_resolution(cursor, game_id=state.game_id, window_id=UUID(str(window["id"])),
                                            resolution_type=str(window["window_kind"]), resolution_source=resolution["source"],
                                            target_player_id=resolution["target"], payload=resolution["payload"],
                                            rng_proof_hash=resolution["proof"], state_version=state.state_version)
            self._players.update_eliminated_players(cursor, game_id=state.game_id, players=state.players, phase=phase, round=round_number)
            following = next_window(state, now)
            if following is not None:
                self._actions.open_window(cursor, following)
        self._games.update_game_state(
            cursor, state=state, expected_state_version=version, user_action=user_action,
        )
        front_sequence = self._games.next_front_sequence(cursor, state.game_id)
        self._append_events(cursor, state=state, next_window=following, front_sequence=front_sequence,
                            now=now, fast_forward_enabled=fast_forward_enabled,
                            resolution=resolution["payload"] if resolution else None)

    def fast_forward(self, owner_user_id: UUID, game_id: UUID, payload: GameCommandRequest,
                     idempotency_key: UUID) -> tuple[dict[str, Any], bool]:
        """인간 사망 뒤 빠른 진행 선택만 저장하고 실제 진행은 worker에 맡긴다."""

        if payload.type != "FAST_FORWARD":
            raise ValueError("빠른 진행 command가 아닙니다.")
        body_hash = request_hash(payload.receipt_body())
        route_scope = f"POST /api/v1/games/{game_id}/commands"
        try:
            with self._transactions.transaction() as connection:
                with connection.cursor(row_factory=dict_row) as cursor:
                    lock_idempotency(cursor, "USER", owner_user_id, idempotency_key)
                    game = self._owned_game(cursor, owner_user_id, game_id)
                    replay = find_replay(self, cursor, owner_user_id=owner_user_id, idempotency_key=idempotency_key, request_hash=body_hash, route_scope=route_scope)
                    if replay is not None:
                        return replay, True
                    state, _ = restore_locked_game(self, cursor, game)
                    version = state.state_version
                    if payload.expected_state_version != version:
                        raise ApiError(status_code=409, code="STALE_STATE_VERSION", message="게임 상태가 변경되었습니다.")
                    if state.status is not GameStatus.IN_PROGRESS or state.human_alive:
                        raise ApiError(status_code=409, code="ACTION_NOT_ALLOWED", message="진행 중 관전에서만 빠른 진행을 사용할 수 있습니다.")
                    now = datetime.now(UTC)
                    state.state_version = version + 1
                    state.updated_at = now
                    state.fast_forward_enabled = True
                    self._games.update_game_state(
                        cursor, state=state, expected_state_version=version, user_action=True,
                    )
                    front_sequence = self._games.next_front_sequence(cursor, game_id)
                    window = self._actions.current_window(cursor, game_id=game_id)
                    self._append_events(cursor, state=state, next_window=window, front_sequence=front_sequence,
                                        now=now, fast_forward_enabled=True, fast_forward_selected=True)
                    result = self._result(game_id, "FAST_FORWARD", version, idempotency_key)
                    self._receipts.insert(cursor, principal_type="USER", principal_id=owner_user_id,
                                          idempotency_key=idempotency_key, route_scope=route_scope, game_id=game_id,
                                          request_hash=body_hash, result_state_version=state.state_version, http_status=200, result_body=result)
                    return result, False
        except ApiError:
            raise
        except Exception as exc:
            raise ApiError(status_code=503, code="DEPENDENCY_UNAVAILABLE", message="빠른 진행 선택을 저장할 수 없습니다.", retryable=True) from exc

    def _append_events(self, cursor: Any, *, state: GameState, next_window: Any,
                       front_sequence: int, now: datetime, fast_forward_enabled: bool,
                       resolution: dict[str, Any] | None = None,
                       fast_forward_selected: bool = False) -> None:
        """확정 결과만 공개하고 인간 조사 결과는 수신자가 지정된 private event로 저장한다."""

        events = []

        def append(event_type: str, operation_type: str, payload: dict[str, Any], *, player_id: UUID | None = None) -> None:
            """한 transaction의 visible operation index를 빠짐없이 부여한다."""

            events.append(self._events.append(cursor, game_id=state.game_id, state_version=state.state_version,
                                              event_type=event_type, audience="PLAYER" if player_id else "PUBLIC",
                                              audience_player_id=player_id, front_sequence=front_sequence,
                                              operation_index=len(events), operation_type=operation_type, payload=payload))

        append("PHASE_CHANGED", "SET_GAME_STATE", {"status": state.status.value, "phase": state.phase.value,
               "round": state.round, "day_number": state.day_number, "state_version": state.state_version,
               "fast_forward_enabled": fast_forward_enabled})
        if fast_forward_selected:
            append("FAST_FORWARD_ENABLED", "APPEND_PUBLIC_EVENT", {"enabled": True})
        if resolution is not None:
            if resolution["phase"] == "NIGHT_ACTION":
                append("NIGHT_RESOLVED", "APPEND_PUBLIC_EVENT", {"round": resolution["round"], "killed_player_id": resolution["killed_player_id"]})
                for investigation in resolution["investigations"]:
                    actor_id = UUID(investigation["actor_player_id"])
                    data = {"round": resolution["round"], "target_player_id": investigation["target_player_id"], "is_mafia": investigation["is_mafia"]}
                    if state.player_by_id[actor_id].kind is PlayerKind.HUMAN:
                        append("INVESTIGATION_RESULT", "APPEND_PRIVATE_EVENT", data, player_id=actor_id)
                    else:
                        # AI 조사 이력은 본인 MCP context에만 사용한다. Front batch에
                        # 넣으면 공개 index 간격으로 비공개 actor가 드러날 수 있다.
                        self._events.append(cursor, game_id=state.game_id, state_version=state.state_version,
                                            event_type="INVESTIGATION_RESULT", audience="PLAYER",
                                            audience_player_id=actor_id, payload=data)
            else:
                append("VOTE_RESOLVED", "APPEND_PUBLIC_EVENT", {key: resolution[key] for key in ("round", "phase", "counts", "tied", "needs_revote")})
                target = resolution["eliminated_player_id"] or resolution["final_target_player_id"]
                if target is not None:
                    append("PLAYER_EXECUTED", "APPEND_PUBLIC_EVENT", {"player_id": target, "revealed_role": state.player_by_id[UUID(target)].role.value})
            if state.status is GameStatus.COMPLETED:
                append("GAME_ENDED", "APPEND_PUBLIC_EVENT", {"winner": state.winner.value, "win_reason": state.win_reason.value})
        if next_window is None:
            append("TURN_OPENED", "CLEAR_ACTION_WINDOW", {"window_id": None})
        else:
            if isinstance(next_window, Mapping):
                identifier, kind, cycle, paused, version, deadline, turn = (next_window["id"], next_window["window_kind"], next_window["cycle"], next_window["status"] == "PAUSED", next_window["opened_state_version"], next_window["deadline_at"], next_window["turn_player_id"])
            else:
                identifier, kind, cycle, paused, version, deadline, turn = (next_window.window_id, next_window.window_kind, next_window.cycle, False, next_window.opened_state_version, next_window.deadline_at, next_window.turn_player_id)
            append("TURN_OPENED", "SET_ACTION_WINDOW", {"window_id": str(identifier), "kind": kind, "cycle": cycle,
                   "paused": paused, "opened_state_version": version, "server_time": now.isoformat().replace("+00:00", "Z"),
                   "deadline_at": deadline.isoformat().replace("+00:00", "Z") if deadline else None,
                   "remaining_ms": max(int((deadline - now).total_seconds() * 1000), 0) if deadline else None,
                   "turn_player_id": str(turn) if turn else None, "has_submitted": False, "legal_actions": [], "valid_targets": []})
        for event in events:
            self._outbox.enqueue(cursor, UUID(str(event["id"])))
