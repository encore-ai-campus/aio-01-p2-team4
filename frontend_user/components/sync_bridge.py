"""fetch 기반 SSE bridge와 Python polling fallback 연결부."""

from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import streamlit as st

from frontend_user.core.sync import SyncEnvelopeError, apply_envelope
from frontend_user.core.sync_policy import DEFAULT_SYNC_POLICY

ASSET_DIR = Path(__file__).with_name("browser_components") / "sync"
SYNC_COMPONENT = st.components.v2.component(
    name="ai_mafia_sync", html=(ASSET_DIR / "index.html").read_text(encoding="utf-8"),
    js=(ASSET_DIR / "index.js").read_text(encoding="utf-8"),
)


def mount_sse(*, backend_url: str, game_id: str, user_id: UUID, last_sequence: int,
              after_state_version: int = 0) -> dict[str, Any] | None:
    """동일 사용자·게임 scope의 envelope와 제한된 주기의 진행 상태 tick만 받는다."""

    # 팀 전달 사항: /events는 native EventSource가 아니라 fetch streaming으로 연결한다.
    # Backend CORS/proxy는 X-User-Id, X-Request-Id, Last-Event-ID를 허용해야 하며,
    # game_id·UUID를 query parameter에 넣어서는 안 된다.

    # Python에서 실행되는 Frontend는 Docker 내부 DNS 이름을 사용하지만, 이
    # component의 JavaScript는 사용자의 브라우저에서 실행된다. 브라우저가
    # 접근할 수 있는 공개 Backend 주소를 별도 설정으로 받아 두 주소를 섞지 않는다.
    browser_backend_url = os.getenv("BACKEND_BROWSER_URL", backend_url).strip().rstrip("/")
    scope = (browser_backend_url, game_id, str(user_id), st.session_state.get("identity.scope_version"))
    if st.session_state.get("game.sync_scope") != scope:
        st.session_state["game.sync_scope"] = scope
        st.session_state["game.sync_scope_version"] = str(uuid4())
        st.session_state["game.sync_seen_envelope"] = None
        st.session_state["game.sync_tick"] = 0
        st.session_state["game.sync_status"] = "CONNECTING"
        st.session_state["game.sync_hidden"] = False
    instance = f"sync-{game_id}-{user_id}"
    scope_version = st.session_state["game.sync_scope_version"]
    st.session_state["game.sync_component_failed"] = False
    try:
        result = SYNC_COMPONENT(
            data={"schema_version": 1, "component_instance_id": instance, "scope_version": scope_version,
                  "backend_url": browser_backend_url, "game_id": game_id, "user_id": str(user_id),
                  "last_sequence": last_sequence, "after_sequence": last_sequence,
                  "after_state_version": after_state_version, "policy": asdict(DEFAULT_SYNC_POLICY)},
            # component는 공개 기록 fragment 안에서만 실행한다. 2초 진행 tick도
            # 해당 fragment만 갱신하므로 전체 앱과 작성 중인 입력은 재실행하지 않는다.
            default={"envelope": None, "status_tick": None},
            on_envelope_change=lambda: None,
            on_status_tick_change=lambda: None,
            key=instance,
        )
        tick = getattr(result, "status_tick", None)
        if _same_scope(tick, instance=instance, scope_version=scope_version):
            timestamp = tick.get("tick")
            if (tick.get("type") == "SYNC_STATUS" and tick.get("status") in {"CONNECTING", "LIVE", "POLLING", "STALE"}
                    and type(timestamp) is int and timestamp > st.session_state["game.sync_tick"]
                    and type(tick.get("hidden")) is bool):
                st.session_state["game.sync_tick"] = timestamp
                st.session_state["game.sync_status"] = tick["status"]
                st.session_state["game.sync_hidden"] = tick["hidden"]
        message = getattr(result, "envelope", None)
        if not _same_scope(message, instance=instance, scope_version=scope_version):
            return None
        event_id = message.get("event_id")
        if (message.get("type") != "SYNC_ENVELOPE" or not isinstance(event_id, str) or not event_id
                or event_id == st.session_state.get("game.sync_seen_envelope")):
            return None
        st.session_state["game.sync_seen_envelope"] = event_id
        envelope = message.get("envelope")
        # 현재 scope의 잘못된 payload는 빈 dict로 reducer에 전달해 기존 GET 복구
        # 경로를 실행한다. 이전 사용자의 늦은 응답은 위 scope 검사에서 폐기한다.
        return envelope if isinstance(envelope, dict) else {}
    except Exception:
        st.session_state["game.sync_component_failed"] = True
        st.session_state["game.sync_status"] = "POLLING"
        return None


def _same_scope(message: Any, *, instance: str, scope_version: str) -> bool:
    """UUID 교체·게임 이동 뒤 도착한 이전 component 응답의 상태 오염을 막는다."""

    return (isinstance(message, dict) and type(message.get("schema_version")) is int
            and message["schema_version"] == 1 and message.get("component_instance_id") == instance
            and message.get("scope_version") == scope_version)


def apply_sync(*, snapshot: dict[str, Any], envelope: dict[str, Any] | None) -> dict[str, Any]:
    """잘못된 batch는 버리고 caller가 authoritative GET을 수행하도록 예외를 고정한다."""

    # 팀 전달 사항: envelope 검증 실패 시 Backend GET snapshot으로 복구한다. Front는
    # 실패한 batch를 추정해 이어 붙이거나 deadline·phase를 자체 계산하지 않는다.

    if envelope is None:
        return snapshot
    updated, _ = apply_envelope(snapshot=snapshot, envelope=envelope)
    if updated is None:
        raise SyncEnvelopeError("SYNC_EMPTY")
    return updated
