
"""관리자 origin의 UUID local storage bridge."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import streamlit as st

from frontend_admin.core.auth import ADMIN_STORAGE_KEY, parse_admin_uuid

ASSET_DIR = Path(__file__).with_name("browser_components") / "identity"
ADMIN_IDENTITY_COMPONENT = st.components.v2.component(
    name="ai_mafia_admin_identity",
    html=(ASSET_DIR / "index.html").read_text(encoding="utf-8"),
    js=(ASSET_DIR / "index.js").read_text(encoding="utf-8"),
)
ADMIN_IDENTITY_COMPONENT_CHANGED_SESSION_KEY = "admin.identity.bridge_changed"


def _mark_identity_changed() -> None:
    """브라우저 bridge의 실제 UUID가 준비되었음을 다음 관리자 앱 rerun에 전달한다."""

    st.session_state[ADMIN_IDENTITY_COMPONENT_CHANGED_SESSION_KEY] = True


def load_identity(
    *, scope_version: str = "1", replacement: UUID | None = None,
) -> tuple[UUID | None, str | None]:
    """현재 입력 요청의 저장 응답만 채택하고 지연된 옛 UUID 응답은 무시한다."""

    try:
        result = ADMIN_IDENTITY_COMPONENT(
            data={
                "storage_key": ADMIN_STORAGE_KEY,
                "scope_version": scope_version,
                "replacement": str(replacement) if replacement else None,
            },
            default={"identity": None},
            on_identity_change=_mark_identity_changed,
            key="admin-identity-bridge",
        )
        identity = getattr(result, "identity", None)
    except Exception:
        return None, "BRIDGE_UNAVAILABLE"
    if identity is None:
        return None, None
    if not isinstance(identity, dict):
        return None, "INVALID_BRIDGE_RESPONSE"
    if identity.get("scope_version") != scope_version:
        return None, None
    error = identity.get("error_code")
    if error in ("MISSING_UUID", "INVALID_STORED_UUID", "STORAGE_BLOCKED"):
        return None, error
    user_id = parse_admin_uuid(identity.get("user_id"))
    if error is not None or user_id is None or (replacement and user_id != replacement):
        return None, "INVALID_BRIDGE_RESPONSE"
    return user_id, None
