"""사용자 UUID 확인·복구·교체 화면."""

from __future__ import annotations

import streamlit as st

from frontend_user.core.identity import parse_uuid_v4
from frontend_user.core.session import get_identity, request_identity_write


def render() -> None:
    """현재 UUID를 표시하고 확인된 새 UUID로 사용자 scope를 교체한다."""

    # 팀 전달 사항: UUID 복구는 계정 인증이 아니며, Backend가 별도 계정 병합이나
    # 비밀번호 복구로 해석해서는 안 된다. 사용자가 UUID를 아는 경우 같은 게임을
    # 볼 수 있다는 경고를 유지한다.

    user_id = get_identity(st.session_state)
    if user_id is None:
        return
    with st.expander("설정", expanded=False):
        st.caption("내 게임 식별자")
        st.code(str(user_id), language=None)
        st.caption("이 식별자는 비밀번호가 아니며, 아는 사람은 같은 게임을 볼 수 있습니다.")
        replacement = st.text_input("복구할 UUID", key="identity.replacement_input")
        if st.button("UUID 교체", key="identity.replace_button"):
            candidate = parse_uuid_v4(replacement)
            if candidate is None:
                st.error("UUID v4 형식만 입력할 수 있어요.")
            else:
                st.session_state["identity.pending_replacement"] = str(candidate)
        pending = st.session_state.get("identity.pending_replacement")
        if isinstance(pending, str):
            st.warning("현재 UUID의 게임 목록과 진행 상태가 이 브라우저에서 사라집니다.")
            if st.button("확인하고 교체", key="identity.confirm_replace"):
                candidate = parse_uuid_v4(pending)
                if candidate is not None:
                    request_identity_write(user_id=candidate, session_state=st.session_state)
                    st.session_state.pop("identity.pending_replacement", None)
                    st.rerun()
            if st.button("취소", key="identity.cancel_replace"):
                st.session_state.pop("identity.pending_replacement", None)
                st.rerun()
