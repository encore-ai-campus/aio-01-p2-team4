"""일반 사용자 앱의 UUID bootstrap과 화면 dispatcher."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from frontend_user.app_pages.creation_complete_page import (  # noqa: E402
    render as render_creation_complete,
)
from frontend_user.app_pages.feedback_page import render as render_feedback  # noqa: E402
from frontend_user.app_pages.game_create_page import render as render_create  # noqa: E402
from frontend_user.app_pages.game_page import render as render_game  # noqa: E402
from frontend_user.app_pages.game_page import finish_deleted_game  # noqa: E402
from frontend_user.app_pages.home_page import load_games, should_load_games  # noqa: E402
from frontend_user.app_pages.home_page import render as render_home  # noqa: E402
from frontend_user.app_pages.result_page import render as render_result  # noqa: E402
from frontend_user.app_pages.role_reveal_page import render as render_role_reveal  # noqa: E402
from frontend_user.components.identity_bridge import (  # noqa: E402
    IDENTITY_COMPONENT_CHANGED_SESSION_KEY,
    load_identity,
)
from frontend_user.components.theme import render_app_theme, sync_page_navigation  # noqa: E402
from frontend_user.components.action_panel import (  # noqa: E402
    maintain_speech_queue, prefer_current_snapshot, speech_queue_busy,
)
from frontend_user.core.api_client import ApiClient, ApiResponseError  # noqa: E402
from frontend_user.core.identity import parse_uuid_v4  # noqa: E402
from frontend_user.core.session import (  # noqa: E402
    IDENTITY_PERSISTENCE_SESSION_KEY,
    IDENTITY_SCOPE_SESSION_KEY,
    IDENTITY_WARNING_SESSION_KEY,
    IDENTITY_WRITE_SESSION_KEY,
    get_identity,
    maintain_special_roles,
    request_identity_write,
    set_identity,
)


def main() -> None:
    """UUID를 한 번 bootstrap한 뒤 Backend 연동 준비 화면을 표시한다."""

    st.set_page_config(page_title="AI 마피아", page_icon="🕵️", layout="wide")
    render_app_theme()
    # bridge는 매 rerun에서 같은 key로 유지한다. 교체 확인 후에도 저장 응답 전에는
    # 이전 UUID로 API를 호출하거나 이전 홈·게임 화면을 다시 표시하지 않는다.
    write_request = st.session_state.get(IDENTITY_WRITE_SESSION_KEY)
    user_id, persistence, error_code = load_identity(
        scope_version=st.session_state.get(IDENTITY_SCOPE_SESSION_KEY, "1"),
        current_user_id=get_identity(st.session_state),
        current_persistence=st.session_state.get(IDENTITY_PERSISTENCE_SESSION_KEY),
        replacement=parse_uuid_v4(write_request.get("user_id")) if isinstance(write_request, dict) else None,
        reset_stored=isinstance(write_request, dict) and write_request.get("user_id") is None,
    )
    st.session_state.pop(IDENTITY_COMPONENT_CHANGED_SESSION_KEY, None)
    if user_id is None:
        maintain_special_roles(st.session_state)
        maintain_speech_queue(user_id=None, page="home", game_id=None)
        if error_code == "INVALID_STORED_UUID":
            st.error("저장된 게임 식별자가 손상됐어요. 새 UUID를 생성해 주세요.")
            if st.button("새 UUID 생성", key="identity.reset_stored"):
                request_identity_write(user_id=None, session_state=st.session_state)
                st.rerun()
        elif error_code:
            st.error("게임 식별자를 확인하지 못했어요. 브라우저를 새로고침해 주세요.")
        else:
            st.info("게임 식별자를 확인하고 있어요.")
        return
    set_identity(user_id=user_id, persistence=persistence, session_state=st.session_state)
    if isinstance(write_request, dict):
        st.session_state.pop(IDENTITY_WRITE_SESSION_KEY, None)
        st.session_state.pop("identity.replacement_input", None)
        st.session_state["navigation.page"] = "home"

    client = ApiClient(user_id=get_identity(st.session_state))
    st.session_state["game.client"] = client
    if st.session_state.get(IDENTITY_WARNING_SESSION_KEY):
        st.warning("브라우저 저장소를 사용할 수 없어 이번 세션에서만 게임을 복구할 수 있어요.")
    page = st.session_state.get("navigation.page", "home")
    page = sync_page_navigation(page)
    maintain_speech_queue(user_id=user_id, page=page, game_id=st.session_state.get("game.game_id"))
    if page != "game":
        maintain_special_roles(st.session_state)
    load_home_games = False
    if page == "feedback":
        render_feedback(client=client, feedback_type="GENERAL")
    elif page == "game_feedback":
        render_feedback(
            client=client,
            feedback_type="GAME",
            game_id=st.session_state.get("game.game_id"),
            snapshot=st.session_state.get("game.latest_snapshot"),
        )
    elif page == "create":
        render_create(client)
    elif page == "creation_complete":
        pending = st.session_state.get("game.create_pending")
        if isinstance(pending, dict) and pending.get("status") == "SUCCEEDED":
            render_creation_complete(pending)
        else:
            st.session_state["navigation.page"] = "home"
            st.rerun()
    elif page == "game":
        game_id = st.session_state.get("game.game_id")
        if not isinstance(game_id, str):
            st.session_state["navigation.page"] = "home"
            st.rerun()
        try:
            # 제출 callback이 보존한 최초 body를 처리하기 전에 GET으로 대기하거나
            # 다른 rerun을 일으키지 않는다. 재진입·일반 조회는 기존 경로를 유지한다.
            # 재사용 표식이 있어도 아래에서 현재 게임 ID가 일치하는 캐시만 선택한다.
            cached = st.session_state.get("game.latest_snapshot")
            reuse = st.session_state.pop("game.sync_render_snapshot", False)
            pending = st.session_state.get("game.command_pending")
            reuse = reuse or (isinstance(pending, dict) and pending.get("game_id") == game_id
                              and pending.get("status") in {"PENDING_TO_RENDER", "IN_FLIGHT"})
            reuse = reuse or speech_queue_busy(game_id)
            if (reuse and isinstance(cached, dict)
                    and cached.get("game", {}).get("game_id") == game_id):
                response = cached
            else:
                response = client.get_game(game_id)
            snapshot = response.get("data") if isinstance(response.get("data"), dict) else response
            if not isinstance(snapshot, dict) or not isinstance(snapshot.get("game"), dict):
                raise ValueError("INVALID_RESPONSE")
            snapshot = prefer_current_snapshot(snapshot=snapshot, game_id=game_id, user_id=user_id)
            st.session_state["game.latest_snapshot"] = snapshot
            maintain_special_roles(st.session_state, snapshot)
            maintain_speech_queue(user_id=user_id, page=page, game_id=game_id, snapshot=snapshot)
        except Exception as error:
            maintain_special_roles(st.session_state)
            # DELETE 응답 유실 뒤 첫 재조회가 404라면 팝업을 다시 그릴 snapshot이 없다.
            # 이 게임에 사용자가 제출한 삭제 요청이 있을 때만 이탈 완료로 처리한다.
            pending_delete = st.session_state.get("game.delete_pending")
            if (isinstance(error, ApiResponseError) and error.status_code == 404
                    and error.code == "GAME_NOT_FOUND" and isinstance(pending_delete, dict)
                    and pending_delete.get("game_id") == game_id):
                finish_deleted_game()
            st.error("게임 상태를 불러오지 못했어요.")
            if st.button("홈으로", key="game.load_home"):
                st.session_state["navigation.page"] = "home"
                st.session_state.pop("game.game_id", None)
                st.rerun()
        else:
            if snapshot["game"].get("status") in {"COMPLETED", "FAILED"}:
                render_result(snapshot)
            elif snapshot["game"].get("phase") == "ROLE_REVEAL":
                render_role_reveal(snapshot)
            else:
                render_game(snapshot)
    else:
        load_home_games = should_load_games(st.session_state) or bool(
            st.session_state.get("home.games_loading")
        )
        # 기존 카드를 loading 화면으로 가리면 TTL 만료와 함께 도착한 카드 클릭을
        # 읽지 못한다. 최초 조회만 loading으로 표시하고 캐시가 있으면 입력부터 처리한다.
        if load_home_games and "home.games" not in st.session_state:
            st.session_state["home.games_loading"] = True
        render_home(client)
    # TTL 만료 때 먼저 rerun하면 이번 요청의 버튼 trigger가 초기화된다.
    # 카드·홈 이동·UUID 최종 확인을 먼저 처리하고, 남아 있는 목록 조회만 수행한다.
    if load_home_games:
        load_games(client)
        st.rerun()


if __name__ == "__main__":
    main()
