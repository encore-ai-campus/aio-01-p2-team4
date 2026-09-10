"""Streamlit과 브라우저 local storage 사이의 최소 UUID bridge."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import streamlit as st

from frontend_user.core.identity import STORAGE_KEY, new_user_id, parse_uuid_v4

ASSET_DIR = Path(__file__).with_name("browser_components") / "identity"
IDENTITY_HTML = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
IDENTITY_JS = (ASSET_DIR / "index.js").read_text(encoding="utf-8")
IDENTITY_COMPONENT = st.components.v2.component(
    name="ai_mafia_identity", html=IDENTITY_HTML, js=IDENTITY_JS
)
IDENTITY_COMPONENT_CHANGED_SESSION_KEY = "identity.bridge_changed"

# 팀 전달 사항: 이 component는 UUID 문자열과 LOCAL/SESSION_ONLY 상태만 반환한다.
# snapshot, 게임 목록, role, private event, API secret을 browser storage나 component
# state에 저장하지 않는다. 저장소가 차단되어도 화면을 중단하지 않고 session-only로
# 동작하되, 게임 복구가 보장되지 않는다는 경고를 사용자에게 표시한다.


def _mark_identity_changed() -> None:
    """브라우저 bridge가 실제 상태를 반환했음을 다음 Streamlit rerun에 전달한다."""

    st.session_state[IDENTITY_COMPONENT_CHANGED_SESSION_KEY] = True


def load_identity(
    *,
    scope_version: str = "1",
    current_user_id: UUID | None = None,
    current_persistence: str | None = None,
    replacement: UUID | None = None,
    reset_stored: bool = False,
) -> tuple[UUID | None, str | None, str | None]:
    """현재 요청의 브라우저 응답만 채택하고 명시적 저장소 실패에만 임시 UUID를 쓴다."""

    try:
        result = IDENTITY_COMPONENT(
            data={
                "schema_version": 1,
                "component_instance_id": "identity-main",
                "storage_key": STORAGE_KEY,
                "scope_version": scope_version,
                "current_user_id": str(current_user_id) if current_user_id else None,
                "session_only": current_persistence == "SESSION_ONLY",
                "replacement": str(replacement) if replacement else None,
                "reset_stored": reset_stored,
            },
            default={"identity": None},
            on_identity_change=_mark_identity_changed,
            key="identity-bridge",
        )
        identity = getattr(result, "identity", None)
    except Exception:
        return None, None, "BRIDGE_UNAVAILABLE"
    # 첫 mount의 None은 비동기 응답 대기이며 저장소 실패나 새 사용자 생성의 근거가 아니다.
    if identity is None:
        return None, None, None
    if not isinstance(identity, dict):
        return None, None, "INVALID_BRIDGE_RESPONSE"
    if (
        type(identity.get("schema_version")) is not int
        or identity.get("schema_version") != 1
        or identity.get("component_instance_id") != "identity-main"
    ):
        return None, None, "INVALID_BRIDGE_RESPONSE"
    if identity.get("scope_version") != scope_version:
        return None, None, None
    user_id = parse_uuid_v4(identity.get("user_id"))
    persistence = identity.get("persistence")
    error_code = identity.get("error_code")
    if error_code is not None and not isinstance(error_code, str):
        return None, None, "INVALID_BRIDGE_RESPONSE"
    if error_code == "STORAGE_BLOCKED" and persistence == "SESSION_ONLY":
        # 복구 쓰기가 실패해도 사용자가 입력한 UUID를 보존하고, 재실행 때 다시 만들지 않는다.
        return replacement or current_user_id or user_id or new_user_id(), persistence, error_code
    if error_code in {"INVALID_STORED_UUID", "CRYPTO_UNAVAILABLE"}:
        return None, None, error_code
    if user_id is None or persistence != "LOCAL" or error_code is not None:
        return None, None, "INVALID_BRIDGE_RESPONSE"
    if replacement is not None and user_id != replacement:
        return None, None, "INVALID_BRIDGE_RESPONSE"
    return user_id, "LOCAL", None
