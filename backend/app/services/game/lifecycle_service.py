"""게임 시작·저장·재개 command와 수동 삭제 service의 공개 조합 경계.

트랜잭션의 순서와 상태 변경은 이 모듈에 두고, 저장소와 공통 복원·이벤트
도우미는 service 객체가 제공하도록 한다. 이렇게 하면 command별 orchestration이
게임 서비스의 거대한 구현 파일에 다시 섞이지 않는다.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row

from backend.app.core.errors import ApiError
from backend.app.game_engine.engine import GameEngine
from backend.app.game_engine.errors import RuleViolation
from backend.app.infrastructure.transaction import lock_idempotency
from backend.app.repositories.action_repository import ActionWindowInsert
from backend.app.schemas.command_schema import GameCommandRequest
from backend.app.services.game.helpers import request_hash as _request_hash, window_id as uuid5_for_window
from backend.app.services.game.service_errors import rule_error
from backend.app.services.game.postgres_helpers import find_replay, restore_locked_game


def delete_game(
    service: Any, owner_user_id: UUID, game_id: UUID, *, expected_state_version: int,
) -> dict[str, Any]:
    """사용자가 확인한 게임만 잠금 안에서 삭제하고 실패 시 종속 원장도 되돌린다.

    command와 동일한 게임 행 잠금으로 AI 진행·저장과 직렬화한다. 존재하지 않는
    게임과 타인 소유 게임은 같은 오류로 반환해 삭제 여부를 외부에 구분하지 않는다.
    """

    if type(expected_state_version) is not int or expected_state_version < 1:
        raise ApiError(status_code=422, code="INVALID_REQUEST", message="게임 상태 버전이 올바르지 않습니다.")
    try:
        with service._transactions.transaction() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                game = service._games.lock_game(cursor, game_id)
                if game is None or UUID(str(game["owner_user_id"])) != owner_user_id:
                    raise ApiError(status_code=404, code="GAME_NOT_FOUND", message="게임을 찾을 수 없습니다.")
                if game["state_version"] != expected_state_version:
                    raise ApiError(status_code=409, code="STALE_STATE_VERSION", message="게임 상태가 변경되었습니다. 최신 상태를 다시 확인하세요.")
                if game["status"] not in {"IN_PROGRESS", "SAVED"}:
                    raise ApiError(status_code=409, code="INVALID_GAME_STATUS", message="진행 중이거나 저장된 게임만 삭제할 수 있습니다.")
                service._games.delete_owned_game(
                    cursor, game_id=game_id, owner_user_id=owner_user_id,
                    expected_state_version=expected_state_version,
                )
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(status_code=503, code="DEPENDENCY_UNAVAILABLE", message="게임을 삭제하지 못했습니다. 다시 확인해 주세요.", retryable=True) from exc
    return {"game_id": str(game_id), "deleted": True}


def _route_scope(game_id: UUID) -> str:
    """게임 command의 idempotency 범위를 한 곳에서 만든다."""

    return f"POST /api/v1/games/{game_id}/commands"


def _remaining_ms(window: Mapping[str, Any] | None, now: datetime) -> int | None:
    """시간 제한 window의 저장 시점 잔여 시간을 계산한다."""

    if window is None or (window["window_kind"] == "SPEECH" and window.get("deadline_at") is None):
        return None
    deadline = window["deadline_at"]
    if not isinstance(deadline, datetime):
        raise RuntimeError("Timed action window deadline is invalid")
    return max(int((deadline - now).total_seconds() * 1000), 0)


def _saved_remaining_ms(window: Mapping[str, Any] | None) -> int | None:
    """PAUSED window의 종류에 맞는 저장 잔여 시간을 검증한다."""

    if window is None:
        return None
    if window["status"] != "PAUSED":
        raise RuntimeError("Saved game action window is not paused")
    window_kind = str(window["window_kind"])
    remaining_ms = window.get("remaining_ms_on_save")
    if window_kind == "SPEECH" and remaining_ms is None:
        return None
    if window_kind not in {"SPEECH", "NIGHT", "VOTE", "REVOTE", "FINAL_VOTE"}:
        raise RuntimeError("Saved action window kind is invalid")
    if isinstance(remaining_ms, bool) or not isinstance(remaining_ms, int) or remaining_ms < 0:
        raise RuntimeError("Saved timed window remaining time is invalid")
    return remaining_ms


def begin_game(service: Any, owner_user_id: UUID, game_id: UUID, payload: GameCommandRequest, idempotency_key: UUID) -> tuple[dict[str, Any], bool]:
    """BEGIN_GAME의 원장·window·event·receipt를 하나의 transaction으로 확정한다."""

    if payload.type != "BEGIN_GAME":
        raise ValueError("PostgresBeginGameService only accepts BEGIN_GAME")
    request_hash = _request_hash(payload.receipt_body())
    route_scope = _route_scope(game_id)
    try:
        with service._transactions.transaction() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                lock_idempotency(cursor, "USER", owner_user_id, idempotency_key)
                game_row = service._games.lock_game(cursor, game_id)
                if game_row is None or UUID(str(game_row["owner_user_id"])) != owner_user_id:
                    raise ApiError(status_code=404, code="GAME_NOT_FOUND", message="게임을 찾을 수 없습니다.")
                replay = find_replay(service, cursor, owner_user_id=owner_user_id, idempotency_key=idempotency_key, request_hash=request_hash, route_scope=route_scope)
                if replay is not None:
                    return replay, True
                state, human_player_id = restore_locked_game(service, cursor, game_row)
                accepted_version = state.state_version
                if payload.expected_state_version != accepted_version:
                    raise ApiError(status_code=409, code="STALE_STATE_VERSION", message="게임 상태가 변경되었습니다. 최신 상태를 다시 확인하세요.", details={"current_state_version": accepted_version})
                if service._actions.current_window(cursor, game_id=game_id) is not None:
                    raise ApiError(status_code=409, code="WINDOW_NOT_READY", message="현재 행동 window가 아직 정리되지 않았습니다.")
                try:
                    GameEngine().begin_game(state)
                except RuleViolation as exc:
                    raise rule_error(exc) from exc
                service._games.update_game_state(
                    cursor, state=state, expected_state_version=accepted_version, user_action=True,
                )
                front_sequence = service._games.next_front_sequence(cursor, game_id)
                from backend.app.services.game.window_service import next_window
                service._actions.open_window(cursor, next_window(state, datetime.now(UTC)))
                service.append_front_events(cursor, game_id=game_id, state=state, front_sequence=front_sequence)
                result = {"command_id": str(idempotency_key), "command_type": "BEGIN_GAME", "accepted_state_version": accepted_version, "result_state_version": state.state_version, "sync_url": f"/api/v1/games/{game_id}/sync"}
                service._receipts.insert(cursor, principal_type="USER", principal_id=owner_user_id, idempotency_key=idempotency_key, route_scope=route_scope, game_id=game_id, request_hash=request_hash, result_state_version=state.state_version, http_status=200, result_body=result)
                return result, False
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(status_code=503, code="DEPENDENCY_UNAVAILABLE", message="게임 저장소를 사용할 수 없습니다.", retryable=True) from exc


def save_game(service: Any, owner_user_id: UUID, game_id: UUID, payload: GameCommandRequest, idempotency_key: UUID, *, now: datetime | None = None) -> tuple[dict[str, Any], bool]:
    """화면 버전과 무관하게 마지막 확정 상태·window·event·receipt를 한 번에 저장한다.

    화면이 갱신되는 동안 AI가 진행해도 저장 의도는 유효하다. 요청 버전은 멱등
    hash에만 유지하고, 잠금 뒤 복원한 실제 버전으로 UPDATE해 확정된 기록을 보존한다.
    아직 확정되지 않은 외부 응답은 기다리지 않으며 저장 뒤 기존 상태 검증에 맡긴다.
    """

    if payload.type != "SAVE_AND_EXIT":
        raise ValueError("PostgresGameSaveService only accepts SAVE_AND_EXIT")
    request_hash = _request_hash(payload.receipt_body())
    route_scope = _route_scope(game_id)
    try:
        with service._transactions.transaction() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                lock_idempotency(cursor, "USER", owner_user_id, idempotency_key)
                game_row = service._games.lock_game(cursor, game_id)
                if game_row is None or UUID(str(game_row["owner_user_id"])) != owner_user_id:
                    raise ApiError(status_code=404, code="GAME_NOT_FOUND", message="게임을 찾을 수 없습니다.")
                replay = find_replay(service, cursor, owner_user_id=owner_user_id, idempotency_key=idempotency_key, request_hash=request_hash, route_scope=route_scope)
                if replay is not None:
                    return replay, True
                state, _ = restore_locked_game(service, cursor, game_row)
                accepted_version = state.state_version
                window = service._actions.current_window(cursor, game_id=game_id)
                if window is not None and window["status"] == "RESOLVING":
                    raise ApiError(status_code=409, code="WINDOW_NOT_READY", message="현재 행동 window가 아직 정리되지 않았습니다.")
                # 잠금을 기다리는 동안 흐른 시간까지 남은 시간으로 되돌리지 않는다.
                current_time = now or datetime.now(UTC)
                remaining_ms = _remaining_ms(window, current_time)
                try:
                    GameEngine().save(state, remaining_ms)
                except RuleViolation as exc:
                    raise rule_error(exc) from exc
                service._games.update_game_state(
                    cursor, state=state, expected_state_version=accepted_version, user_action=True,
                )
                if window is not None:
                    service._actions.pause_window(cursor, window_id=UUID(str(window["id"])), remaining_ms=remaining_ms)
                front_sequence = service._games.next_front_sequence(cursor, game_id)
                service.append_save_events(cursor, game_id=game_id, state=state, front_sequence=front_sequence)
                result = {"command_id": str(idempotency_key), "command_type": "SAVE_AND_EXIT", "accepted_state_version": accepted_version, "result_state_version": state.state_version, "sync_url": f"/api/v1/games/{game_id}/sync"}
                service._receipts.insert(cursor, principal_type="USER", principal_id=owner_user_id, idempotency_key=idempotency_key, route_scope=route_scope, game_id=game_id, request_hash=request_hash, result_state_version=state.state_version, http_status=200, result_body=result)
                return result, False
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(status_code=503, code="DEPENDENCY_UNAVAILABLE", message="게임 저장소를 사용할 수 없습니다.", retryable=True) from exc


def resume_game(service: Any, owner_user_id: UUID, game_id: UUID, payload: GameCommandRequest, idempotency_key: UUID, *, now: datetime | None = None) -> tuple[dict[str, Any], bool]:
    """RESUME의 저장 상태·window·event·receipt를 하나의 transaction으로 재개한다."""

    if payload.type != "RESUME":
        raise ValueError("PostgresGameResumeService only accepts RESUME")
    request_hash = _request_hash(payload.receipt_body())
    route_scope = _route_scope(game_id)
    current_time = now or datetime.now(UTC)
    try:
        with service._transactions.transaction() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                lock_idempotency(cursor, "USER", owner_user_id, idempotency_key)
                game_row = service._games.lock_game(cursor, game_id)
                if game_row is None or UUID(str(game_row["owner_user_id"])) != owner_user_id:
                    raise ApiError(status_code=404, code="GAME_NOT_FOUND", message="게임을 찾을 수 없습니다.")
                replay = find_replay(service, cursor, owner_user_id=owner_user_id, idempotency_key=idempotency_key, request_hash=request_hash, route_scope=route_scope)
                if replay is not None:
                    return replay, True
                state, _ = restore_locked_game(service, cursor, game_row)
                accepted_version = state.state_version
                if payload.expected_state_version != accepted_version:
                    raise ApiError(status_code=409, code="STALE_STATE_VERSION", message="게임 상태가 변경되었습니다. 최신 상태를 다시 확인하세요.", details={"current_state_version": accepted_version})
                window = service._actions.current_window(cursor, game_id=game_id)
                state.remaining_ms_on_save = _saved_remaining_ms(window)
                try:
                    GameEngine().resume(state, current_time)
                except RuleViolation as exc:
                    raise rule_error(exc) from exc
                service._games.update_game_state(
                    cursor, state=state, expected_state_version=accepted_version, user_action=True,
                )
                if window is not None:
                    service._actions.resume_window(cursor, window_id=UUID(str(window["id"])), deadline_at=state.deadline_at)
                front_sequence = service._games.next_front_sequence(cursor, game_id)
                service.append_resume_events(cursor, game_id=game_id, state=state, front_sequence=front_sequence)
                result = {"command_id": str(idempotency_key), "command_type": "RESUME", "accepted_state_version": accepted_version, "result_state_version": state.state_version, "sync_url": f"/api/v1/games/{game_id}/sync"}
                service._receipts.insert(cursor, principal_type="USER", principal_id=owner_user_id, idempotency_key=idempotency_key, route_scope=route_scope, game_id=game_id, request_hash=request_hash, result_state_version=state.state_version, http_status=200, result_body=result)
                return result, False
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(status_code=503, code="DEPENDENCY_UNAVAILABLE", message="게임 저장소를 사용할 수 없습니다.", retryable=True) from exc

from backend.app.services.game_service import (
    PostgresBeginGameService,
    PostgresGameResumeService,
    PostgresGameSaveService,
)

__all__ = [
    "begin_game",
    "resume_game",
    "save_game",
    "PostgresBeginGameService",
    "PostgresGameResumeService",
    "PostgresGameSaveService",
]
