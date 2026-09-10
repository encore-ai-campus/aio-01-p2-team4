"""관리자 게임 목록."""

from __future__ import annotations

from html import escape

import streamlit as st


LIST_CSS = """
<style>
.admin-list-heading { display:flex; align-items:center; justify-content:space-between; gap:1rem; }
.admin-list-title { color:#172033; font-size:1.05rem; font-weight:800; letter-spacing:-.02em; }
.admin-list-subtitle { margin:.25rem 0 1rem; color:#68738a; font-size:.83rem; }
.admin-game-card { padding:.15rem 0; }
.admin-list-meta { margin:.35rem 0 .7rem; color:#66758f; font-size:.83rem; }
.admin-list-status { display:inline-block; margin-right:.35rem; padding:.25rem .5rem; border-radius:999px; color:#5f35c9; background:#f0ebff; font-size:.72rem; font-weight:800; }
[data-testid="stVerticalBlockBorderWrapper"] { border-color:#e1e4ed; border-radius:.8rem; background:#fff; box-shadow:0 8px 20px rgba(25,35,70,.045); }
</style>
"""


def render(items: list[dict]) -> str | None:
    """공개 관리자 요약 필드만 표시하고 선택한 game id를 반환한다."""

    st.markdown(LIST_CSS, unsafe_allow_html=True)
    st.markdown(
        '<div class="admin-list-heading"><div class="admin-list-title">게임 목록</div></div>'
        '<div class="admin-list-subtitle">운영에 필요한 공개 요약 정보만 표시됩니다.</div>',
        unsafe_allow_html=True,
    )
    selected = None
    for item in items:
        game_id = item.get("game_id")
        with st.container(border=True):
            title = escape(str(item.get("game_id", "게임")))
            status = escape(str(item.get("status", "-")))
            phase = escape(str(item.get("phase", "-")))
            count = escape(str(item.get("player_count", "-")))
            st.markdown(
                f'<div class="admin-game-card"><div class="admin-list-title">{title}</div>'
                f'<div class="admin-list-meta"><span class="admin-list-status">{status}</span>'
                f'{phase} · {count}명</div></div>',
                unsafe_allow_html=True,
            )
            if isinstance(game_id, str) and st.button("상세 보기", key=f"admin.game.{game_id}"):
                selected = game_id
    return selected
