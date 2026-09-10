"""관리자 게임 상세."""

from __future__ import annotations

import streamlit as st


def render(detail: dict) -> None:
    """비밀정보가 제거된 상세만 read-only로 표시한다."""

    st.subheader("게임 상세")
    st.caption("Backend가 허용한 운영용 공개 데이터만 확인할 수 있습니다.")
    with st.container(border=True):
        st.json(detail)
