"""게임 생성 직후 플레이어와 다음 행동을 안내하는 완료 화면."""

from __future__ import annotations

from collections.abc import Mapping
from html import escape

import streamlit as st

from frontend_user.components.theme import render_application_header, render_header_back_button


def render(pending: dict[str, object]) -> None:
    """Backend 생성 성공 결과만 사용해 역할 공개 전 대기 화면을 표시한다."""

    st.markdown(
        """
        <style>
        [data-testid="stAppViewContainer"] { background:linear-gradient(145deg,#f4f8ff,#eef4fb); }
        .complete-card { max-width:760px; margin:3rem auto 1rem; padding:2.2rem; border:1px solid #d7e3f5;
          border-radius:1.2rem; background:#fff; box-shadow:0 1rem 2.5rem rgba(42,79,145,.12); text-align:center; }
        .complete-icon { font-size:3.2rem; } .complete-card h1 { color:#152238; margin:.5rem 0; }
        .complete-card p { color:#66758f; } .complete-id { margin:1.2rem 0; padding:1rem; border-radius:.7rem;
          color:#244d91; background:#eef5ff; font-family:monospace; word-break:break-all; }
        .complete-players { display:flex; flex-wrap:wrap; justify-content:center; gap:.5rem; margin:1.2rem 0; }
        .complete-player { padding:.45rem .7rem; border-radius:999px; color:#315a9f; background:#f0f5ff; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    render_application_header(
        title="AI 마피아",
        action_renderer=lambda: render_header_back_button(current_page="creation_complete"),
    )
    game_id = escape(str(pending.get("game_id", "확인 중")))
    snapshot = pending.get("snapshot")
    data = snapshot.get("data", snapshot) if isinstance(snapshot, Mapping) else {}
    players = data.get("players") if isinstance(data, Mapping) else None
    # 참가자 이름은 생성 직후 조회한 공개 snapshot만 사용한다. 응답이 손상되었을 때
    # 가짜 이름을 보충하지 않고 안내를 표시하며, HTML 삽입 전에는 문자열을 escape한다.
    names = [
        escape(player["display_name"])
        for player in players
        if isinstance(player, Mapping)
        and isinstance(player.get("display_name"), str)
        and player["display_name"].strip()
    ] if isinstance(players, list) else []
    if not names or len(names) != len(players):
        st.warning("참가자 정보를 확인하지 못했어요. 역할 공개 화면에서 다시 확인해 주세요.")
    description = (
        f"{len(names)}명의 플레이어가 사건 현장에 모였습니다."
        if names else "역할 공개 화면에서 참가자를 확인해 주세요."
    )

    st.markdown(
        f'<section class="complete-card"><div class="complete-icon">🎉</div>'
        f'<h1>게임이 만들어졌어요</h1><p>{description}</p>'
        f'<div class="complete-id">게임 식별자<br>{game_id}</div>'
        f'<div class="complete-players">{"".join(f"<span class=\"complete-player\">{name}</span>" for name in names)}</div>'
        f'<p>역할은 다음 화면에서 비공개로 공개됩니다.</p></section>',
        unsafe_allow_html=True,
    )
    left, right = st.columns(2)
    with left:
        if st.button("역할 공개 보기", type="primary", key="creation.complete.continue", width="stretch"):
            st.session_state["navigation.page"] = "game"
            st.rerun()
    with right:
        if st.button("홈으로", key="creation.complete.home", width="stretch"):
            st.session_state["navigation.page"] = "home"
            st.session_state.pop("game.game_id", None)
            st.rerun()
