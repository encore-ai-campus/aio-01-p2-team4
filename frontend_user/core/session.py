"""Streamlit session state의 UUID와 사용자 scope 초기화 규칙."""

from __future__ import annotations

from uuid import UUID, uuid4

from frontend_user.core.identity import parse_uuid_v4

USER_ID_SESSION_KEY = "identity.user_id"
IDENTITY_PERSISTENCE_SESSION_KEY = "identity.persistence"
IDENTITY_WARNING_SESSION_KEY = "identity.storage_warning"
IDENTITY_SCOPE_SESSION_KEY = "identity.scope_version"
IDENTITY_WRITE_SESSION_KEY = "identity.write_request"


def set_identity(*, user_id: UUID, persistence: str, session_state: dict[str, object]) -> None:
    """검증된 UUID를 저장하고 실제 교체 때만 이전 사용자 화면 상태를 제거한다."""

    if parse_uuid_v4(user_id) is None or persistence not in {"LOCAL", "SESSION_ONLY"}:
        raise ValueError("유효한 UUID v4와 저장 상태가 필요합니다.")
    if session_state.get(USER_ID_SESSION_KEY) != str(user_id):
        reset_identity_scope(session_state)
    session_state[USER_ID_SESSION_KEY] = str(user_id)
    session_state[IDENTITY_PERSISTENCE_SESSION_KEY] = persistence
    session_state[IDENTITY_WARNING_SESSION_KEY] = persistence == "SESSION_ONLY"


def get_identity(session_state: dict[str, object]) -> UUID | None:
    """session mirror가 손상되었으면 사용하지 않고 None을 반환한다."""

    return parse_uuid_v4(session_state.get(USER_ID_SESSION_KEY))


def request_identity_write(
    *, user_id: UUID | None, session_state: dict[str, object]
) -> None:
    """교체 의도만 기록하고 브라우저 저장 응답 전에는 현재 사용자 scope를 유지한다."""

    if user_id is not None and parse_uuid_v4(user_id) is None:
        raise ValueError("UUID v4 형식만 사용할 수 있습니다.")
    # 동일 UUID를 연속 복구해도 이전 요청의 늦은 응답과 구분할 수 있어야 한다.
    session_state.pop("game.special_roles", None)
    session_state[IDENTITY_SCOPE_SESSION_KEY] = str(uuid4())
    session_state[IDENTITY_WRITE_SESSION_KEY] = {
        "user_id": str(user_id) if user_id is not None else None,
    }


def reset_identity_scope(session_state: dict[str, object]) -> None:
    """UUID 교체 시 이전 게임·private·cursor·form 상태를 제거한다."""

    for key in list(session_state):
        if str(key).startswith(("game.", "navigation.", "form.", "feedback.", "home.")):
            session_state.pop(key, None)
    session_state.pop(USER_ID_SESSION_KEY, None)
    session_state.pop(IDENTITY_PERSISTENCE_SESSION_KEY, None)
    session_state.pop(IDENTITY_WARNING_SESSION_KEY, None)


def special_roles_scope(session_state, snapshot):
    """비공개 조회의 현재 소유자·게임·플레이어·상태를 묶고 권한 상실은 즉시 거부한다."""

    from frontend_user.core.commands import owns_custom_ability

    user_id = get_identity(session_state)
    if (user_id is None or session_state.get(IDENTITY_WRITE_SESSION_KEY) is not None
            or not isinstance(snapshot, dict)
            or not owns_custom_ability(snapshot, "intel.special_roles.v1")):
        return None
    game, me = snapshot["game"], snapshot["me"]
    if (session_state.get("game.game_id") != game.get("game_id")
            or type(game.get("day_number")) is not int or game["day_number"] < 2
            or type(game.get("state_version")) is not int):
        return None
    return (str(user_id), session_state.get(IDENTITY_SCOPE_SESSION_KEY), game.get("game_id"),
            me.get("player_id"), game["state_version"], game.get("phase"), game["day_number"])


def maintain_special_roles(session_state, snapshot=None):
    """일반 rerun과 sync 양쪽에서 범위를 검사해 이전 private 결과를 폐기한다."""

    scope = special_roles_scope(session_state, snapshot)
    stored = session_state.get("game.special_roles")
    if scope is None or not isinstance(stored, dict) or stored.get("scope") != scope:
        session_state.pop("game.special_roles", None)
    if session_state.get("game.special_roles_refresh") != scope or scope is None:
        session_state.pop("game.special_roles_refresh", None)
    return scope
