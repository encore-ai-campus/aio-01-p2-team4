"""인간·AI discussion command의 공통 PostgreSQL transaction."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from dataclasses import replace
from collections import Counter
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row

from backend.app.core.errors import ApiError
from backend.app.game_engine.engine import GameEngine
from backend.app.game_engine.errors import RuleViolation
from backend.app.game_engine.rules.discussion_rules import is_first_day_discussion
from backend.app.infrastructure.transaction import lock_idempotency
from backend.app.models.enums import GamePhase
from backend.app.repositories.action_repository import ActionSubmissionInsert
from backend.app.schemas.command_schema import GameCommandRequest
from backend.app.services.game.actor_context import ActorContext, validate_discussion_actor
from backend.app.services.game.helpers import request_hash
from backend.app.services.game.postgres_helpers import restore_locked_game
from backend.app.services.game.service_errors import rule_error
from backend.app.services.game.window_service import next_window


def submit_discussion_transaction(service: Any, owner_user_id: UUID, game_id: UUID, payload: GameCommandRequest, idempotency_key: UUID, *, actor: ActorContext | None = None, now: datetime | None = None) -> tuple[dict[str, Any], bool]:
    """actor 종류만 달리하고 모든 discussion 저장 절차는 공유한다."""

    if payload.type not in {"SPEAK", "PASS"}:
        raise ValueError("discussion command only accepts SPEAK or PASS")
    if actor is not None and actor.owner_user_id != owner_user_id:
        raise ValueError("actor owner does not match command owner")
    route_scope = f"POST /api/v1/games/{game_id}/agent-commands" if actor else f"POST /api/v1/games/{game_id}/commands"
    principal_type = actor.principal_type if actor else "USER"
    principal_id = actor.principal_id if actor else owner_user_id
    body_hash = request_hash(payload.receipt_body())
    current_time = now or datetime.now(UTC)
    try:
        with service._transactions.transaction() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                lock_idempotency(cursor, principal_type, principal_id, idempotency_key)
                game_row = service._games.lock_game(cursor, game_id)
                if game_row is None or UUID(str(game_row["owner_user_id"])) != owner_user_id:
                    raise ApiError(status_code=404, code="GAME_NOT_FOUND", message="게임을 찾을 수 없습니다.")
                previous = service._receipts.find(cursor, principal_type=principal_type, principal_id=principal_id, idempotency_key=idempotency_key)
                if previous is not None:
                    if previous["request_hash"] != body_hash or previous["route_scope"] != route_scope:
                        raise ApiError(status_code=409, code="IDEMPOTENCY_KEY_REUSED", message="같은 Idempotency-Key가 다른 요청에 사용되었습니다.")
                    return deepcopy(previous["result_body"]), True
                state, human_player_id = restore_locked_game(service, cursor, game_row)
                current_actor = actor or ActorContext.human(owner_user_id=owner_user_id, player_id=human_player_id)
                if actor is not None and service._players.get_kind(cursor, game_id=game_id, player_id=actor.player_id) != "AI":
                    raise ApiError(status_code=403, code="ACTOR_NOT_ALLOWED", message="Agent actor가 아닙니다.")
                if payload.expected_state_version != state.state_version:
                    raise ApiError(status_code=409, code="STALE_STATE_VERSION", message="게임 상태가 변경되었습니다.", details={"current_state_version": state.state_version})
                window = service._actions.current_window(cursor, game_id=game_id)
                validate_discussion_actor(state=state, window=window, actor=current_actor, window_id=payload.window_id)
                service.hydrate_discussion_state(cursor, state=state, window=window)
                # 자유 토론은 순수 엔진의 차례 순환을 우회하므로 저장 전에 같은 금지를
                # 적용한다. 이전 receipt 재응답은 위에서 끝나며 새 거부는 원장을 쓰지 않는다.
                if payload.type == "PASS" and is_first_day_discussion(state.phase, state.day_number):
                    raise ApiError(status_code=409, code="ACTION_NOT_ALLOWED",
                                   message="첫날에는 발언을 PASS할 수 없습니다.")
                accepted_version = state.state_version
                discussion_phase = state.phase
                timed = window.get("deadline_at") is not None
                if timed:
                    current_time = now or datetime.now(UTC)
                    if window["deadline_at"] <= current_time:
                        raise ApiError(status_code=409, code="WINDOW_CLOSED", message="토론 시간이 마감되었습니다.")
                    recent = service._actions.recent_discussion_actions(cursor, game_id=game_id, since=current_time - timedelta(seconds=60))
                    count = sum(row["actor_player_id"] == current_actor.player_id and row["action_type"] == "SPEAK" for row in recent)
                    if payload.type == "SPEAK" and count >= 7:
                        raise ApiError(status_code=429, code="SPEECH_RATE_LIMITED", message="플레이어별 1분에 최대 7회 발언할 수 있습니다.")
                try:
                    if payload.type == "SPEAK":
                        if payload.message is None:
                            raise ApiError(status_code=422, code="INVALID_REQUEST", message="SPEAK에는 message가 필요합니다.")
                        if timed:
                            from backend.app.game_engine.rules.player_rules import require_alive_player
                            from backend.app.game_engine.phases.transition import touch
                            require_alive_player(state, current_actor.player_id)
                            message = GameEngine.normalize_speech(payload.message)
                            touch(state)
                            GameEngine()._record(state, "SPEAK", current_actor.player_id, text=message)
                        else:
                            GameEngine().speak(state, current_actor.player_id, payload.message)
                    else:
                        if payload.message is not None:
                            raise ApiError(status_code=422, code="INVALID_REQUEST", message="PASS에는 message를 보낼 수 없습니다.")
                        if timed:
                            from backend.app.game_engine.rules.player_rules import require_alive_player
                            from backend.app.game_engine.phases.transition import touch
                            require_alive_player(state, current_actor.player_id)
                            touch(state)
                            GameEngine()._record(state, "PASS", current_actor.player_id)
                        else:
                            GameEngine().pass_turn(state, current_actor.player_id)
                except RuleViolation as exc:
                    raise rule_error(exc) from exc
                waiting_for_analysis = (
                    not timed and getattr(service, "wait_for_speech_analysis", False) is True
                    and state.phase in {GamePhase.DAY_VOTE, GamePhase.FINAL_ACCUSATION}
                )
                if waiting_for_analysis:
                    # 구형 순차 토론도 마지막 행동은 확정하되 투표를 아직 열지 않는다.
                    # 즉시 마감된 토론 창을 남기면 재시작 후에도 동일 준비 경로로 복구된다.
                    state.phase = discussion_phase
                operation = state.operations[-1]
                service._actions.insert_submission(cursor, ActionSubmissionInsert(game_id=game_id, window_id=UUID(str(window["id"])), actor_player_id=current_actor.player_id, action_type=payload.type, target_player_id=None, message=operation.text if payload.type == "SPEAK" else None, source=current_actor.source, observed_state_version=accepted_version))
                service._games.update_game_state(
                    cursor,
                    state=state,
                    expected_state_version=accepted_version,
                    user_action=actor is None,
                )
                service._actions.cancel_current_window(cursor, game_id=game_id)
                following = next_window(state, current_time)
                if waiting_for_analysis and following is not None:
                    following = replace(following, deadline_at=current_time)
                if timed and following is not None:
                    counts = Counter(row["actor_player_id"] for row in recent)
                    counts[current_actor.player_id] += 1
                    speech_counts = Counter(row["actor_player_id"] for row in recent if row["action_type"] == "SPEAK")
                    if payload.type == "SPEAK":
                        speech_counts[current_actor.player_id] += 1
                    candidates = [player for player in state.alive_players if player.kind.value == "AI" and speech_counts[player.player_id] < 7]
                    # 전원이 분당 상한에 도달해도 AI 예약을 남겨 제한이 풀리면 worker가 재개한다.
                    if not candidates:
                        candidates = [player for player in state.alive_players if player.kind.value == "AI"]
                    chosen = min(candidates, key=lambda player: (counts[player.player_id], player.seat)) if candidates else state.player_by_id[human_player_id]
                    following = replace(following, deadline_at=window["deadline_at"], turn_player_id=chosen.player_id)
                if following is not None:
                    service._actions.open_window(cursor, following)
                front_sequence = service._games.next_front_sequence(cursor, game_id)
                service.append_discussion_events(cursor, game_id=game_id, state=state, actor_player_id=current_actor.player_id, command_type=payload.type, message=operation.text, next_window=following, front_sequence=front_sequence, now=current_time)
                result = {"command_id": str(idempotency_key), "command_type": payload.type, "accepted_state_version": accepted_version, "result_state_version": state.state_version, "sync_url": f"/api/v1/games/{game_id}/sync"}
                service._receipts.insert(cursor, principal_type=current_actor.principal_type, principal_id=current_actor.principal_id, idempotency_key=idempotency_key, route_scope=route_scope, game_id=game_id, request_hash=body_hash, result_state_version=state.state_version, http_status=200, result_body=result)
                return result, False
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(status_code=503, code="DEPENDENCY_UNAVAILABLE", message="게임 저장소를 사용할 수 없습니다.", retryable=True) from exc


def expire_discussion(service: Any, owner_user_id: UUID, game_id: UUID, *, now: datetime | None = None,
                      expected_window_id: UUID | None = None) -> dict[str, Any] | None:
    """게임 잠금 아래 마감을 한 번 확정하고 발언을 만들지 않은 상태 전이만 저장한다."""
    from backend.app.models.enums import GamePhase, GameStatus
    from backend.app.game_engine.phases.transition import touch

    current_time = now or datetime.now(UTC)
    with service._transactions.transaction() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            row = service._games.lock_game(cursor, game_id)
            if row is None or UUID(str(row["owner_user_id"])) != owner_user_id:
                return
            window = service._actions.current_window(cursor, game_id=game_id)
            # 잠금 대기 시간을 새 투표 제한 시간에서 차감하지 않도록 잠금을 얻은 뒤
            # 실제 전환 시각을 정한다. 합성 검증에서 지정한 시각은 그대로 보존한다.
            current_time = now or datetime.now(UTC)
            # 준비 조회 이후 저장·재개 또는 다른 명령으로 창이 바뀌었으면 다음 주기에
            # 새 창을 다시 검증한다. 이전 분석 판정으로 새 투표를 조기에 열지 않는다.
            if expected_window_id is not None and (
                not window or UUID(str(window["id"])) != expected_window_id
            ):
                return
            if not window or window["window_kind"] != "SPEECH" or window.get("deadline_at") is None or window["deadline_at"] > current_time:
                return
            state, human = restore_locked_game(service, cursor, row)
            if state.status is not GameStatus.IN_PROGRESS or state.phase not in {GamePhase.DAY_DISCUSSION, GamePhase.FINAL_DISCUSSION}:
                return
            version = state.state_version
            if state.phase is GamePhase.FINAL_DISCUSSION:
                state.phase = GamePhase.FINAL_ACCUSATION
            elif state.day_number == 1:
                state.phase, state.round = GamePhase.NIGHT_ACTION, 1
            else:
                state.phase = GamePhase.DAY_VOTE
            state.speech_actors.clear()
            touch(state)
            service._games.update_game_state(cursor, state=state, expected_state_version=version)
            service._actions.cancel_current_window(cursor, game_id=game_id)
            following = next_window(state, current_time)
            service._actions.open_window(cursor, following)
            sequence = service._games.next_front_sequence(cursor, game_id)
            service.append_discussion_events(cursor, game_id=game_id, state=state, actor_player_id=human, command_type="END_DISCUSSION", message=None, next_window=following, front_sequence=sequence, now=current_time)
            return {"result_state_version": state.state_version}
