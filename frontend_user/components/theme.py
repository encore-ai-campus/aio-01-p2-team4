"""일반 사용자 화면 전체에서 공유하는 시각 토큰과 접근성 스타일."""

from __future__ import annotations

from collections.abc import Callable
from html import escape

import streamlit as st

NAVIGATION_PAGES = frozenset({
    "home",
    "create",
    "creation_complete",
    "feedback",
    "game_feedback",
    "game",
})
NAVIGATION_HISTORY_KEY = "navigation.history"
NAVIGATION_CURRENT_KEY = "navigation.current_page"


APP_THEME_CSS = """
<style>
:root {
  --ai-ink: #152238;
  --ai-muted: #66758f;
  --ai-primary: #245fd6;
  --ai-surface: #ffffff;
  --ai-bg: #f5f7fb;
  --ai-border: #e1e7f0;
}
html { color-scheme: light; }
[data-testid="stAppViewContainer"] {
  background: radial-gradient(circle at 92% 2%, rgba(160, 190, 255, .2), transparent 24rem), var(--ai-bg);
  color: var(--ai-ink);
}
[data-testid="stHeader"] { background: transparent; }
[data-testid="stToolbar"] { visibility: hidden; }
[data-testid="stMainBlockContainer"] { padding-top: 1.1rem; }
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li { line-height: 1.65; }
[data-testid="stWidgetLabel"] p { color: var(--ai-ink); font-weight: 650; }
[data-testid="stButton"] button {
  min-height: 2.9rem; border-radius: .72rem; border: 1px solid var(--ai-border); font-weight: 720;
  color: var(--ai-ink) !important; background: var(--ai-surface) !important;
  transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
}
[data-testid="stButton"] button:hover:not(:disabled) {
  transform: translateY(-1px); border-color: #a8bced; box-shadow: 0 8px 18px rgba(39, 78, 170, .12);
}
[data-testid="stButton"] button[kind="primary"] { color: #fff !important; border-color: var(--ai-primary); background: linear-gradient(135deg, var(--ai-primary), #1f5ee5) !important; }
[data-testid="stButton"] button:disabled {
  color: #536179 !important; background: #e5eaf2 !important;
  border-color: #aab6c9 !important; opacity: 1 !important; cursor: not-allowed;
}
[data-testid="stButton"] button [data-testid="stMarkdownContainer"] *,
[data-testid="stButton"] button [data-testid="stMarkdownContainer"] {
  color: inherit !important; -webkit-text-fill-color: currentColor !important;
}
[data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea, [data-testid="stSelectbox"] > div > div { border-radius: .68rem; }
[data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea {
  color: #152238 !important; -webkit-text-fill-color: #152238 !important;
  background: #fff !important; caret-color: #152238; border: 1px solid #8292ad;
}
[data-testid="stTextInput"] input::placeholder, [data-testid="stTextArea"] textarea::placeholder {
  color: #586880 !important; -webkit-text-fill-color: #586880 !important; opacity: 1;
}
[data-testid="stTextInput"] input:disabled, [data-testid="stTextArea"] textarea:disabled {
  color: #536179 !important; -webkit-text-fill-color: #536179 !important;
  background: #e5eaf2 !important; opacity: 1;
}
[data-testid="stWidgetLabel"] { color: var(--ai-ink); }
[data-testid="stWidgetLabel"] [data-testid="stMarkdownContainer"],
[data-testid="stWidgetLabel"] [data-testid="stMarkdownContainer"] p { color: inherit !important; }
[data-testid="stExpander"] details, [data-testid="stExpander"] summary {
  color: #152238 !important; background: #fff !important;
}
[data-testid="stExpander"] summary [data-testid="stMarkdownContainer"],
[data-testid="stExpander"] summary [data-testid="stMarkdownContainer"] * {
  color: inherit !important;
}
[data-testid="stAlert"] { border-radius: .75rem; }
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]),
[data-testid="stAlertContentSuccess"] {
  color: #173626 !important; background: #e8f5ec !important;
}
[data-testid="stAlertContentSuccess"] [data-testid="stMarkdownContainer"] * { color: inherit !important; }
[class*="st-key-app-header"] {
  /* 헤더와 첫 콘텐츠는 구분하되 과도한 빈 공간은 줄인다. */
  margin: 0 -1.5rem .25rem; padding: .7rem 1.5rem .55rem;
  background: #0b1730; border-bottom: 1px solid #24324c;
}
[class*="st-key-app-header"] [data-testid="stHorizontalBlock"] { align-items: center; }
[class*="st-key-app-header"] [data-testid="stColumn"]:last-child {
  display: flex; justify-content: flex-end; align-items: center;
}
.app-header-brand { color: #fff; font-size: 1.55rem; font-weight: 800; letter-spacing: -.06em; }
.app-header-status { display: inline-flex; align-items: center; gap: .4rem; margin-left: 1rem; padding: .42rem .7rem;
  border: 1px solid #2b3b57; border-radius: .55rem; color: #d8e2f3; font-size: .78rem; }
.app-header-status::before { content: ""; width: .45rem; height: .45rem; border-radius: 50%; background: #31c477; }
.app-header-phase { color: #fff; font-size: 1.35rem; font-weight: 800; text-align: center; }
/* 페이지별 버튼 스타일보다 헤더 규칙이 우선하도록 body부터 포함한 선택자를 사용한다. */
body [class*="st-key-app-header"] [data-testid="stButton"] button,
body [class*="st-key-app-header"] [data-testid="stButton"] button:not(:disabled) {
  min-height: 2.65rem; color: #eef4ff !important; background: #0b1730 !important;
  border: 1px solid #405374 !important; box-shadow: inset 0 0 0 1px rgba(255,255,255,.03);
}
body [class*="st-key-app-header"] [data-testid="stButton"] button:hover:not(:disabled) {
  color: #fff !important; background: #152846 !important; border-color: #8ba8d4 !important;
}
body [class*="st-key-app-header"] [data-testid="stButton"] button:active:not(:disabled),
body [class*="st-key-app-header"] [data-testid="stButton"] button:focus-visible {
  color: #fff !important; background: #1b3157 !important; border-color: #a9c5ef !important;
}
body [class*="st-key-app-header"] [data-testid="stButton"] button *,
body [class*="st-key-app-header"] [data-testid="stButton"] button [data-testid="stMarkdownContainer"] * {
  color: inherit !important; -webkit-text-fill-color: currentColor !important;
}
button:focus-visible, input:focus-visible, textarea:focus-visible {
  outline: 3px solid #245fd6 !important; outline-offset: 3px;
  box-shadow: 0 0 0 2px #fff !important;
}
@media (max-width: 768px) {
  [data-testid="stMainBlockContainer"] { padding: .6rem .8rem 2rem; }
  [data-testid="stButton"] button { min-height: 3.1rem; }
}
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { transition-duration: .01ms !important; } }
</style>
"""


def render_app_theme() -> None:
    """공통 CSS를 주입해 페이지별 레이아웃이 같은 기본 경험을 갖게 한다."""

    st.markdown(APP_THEME_CSS, unsafe_allow_html=True)


def sync_page_navigation(current_page: str) -> str:
    """직접 page 값을 바꾸는 기존 화면 전환을 검증된 방문 기록으로 동기화한다."""

    page = (
        current_page
        if isinstance(current_page, str) and current_page in NAVIGATION_PAGES
        else "home"
    )
    previous = st.session_state.get(NAVIGATION_CURRENT_KEY)
    history = _navigation_history(current_page=page)
    if page == "home":
        history = []
    elif isinstance(previous, str) and previous in NAVIGATION_PAGES and previous != page:
        if not history or history[-1] != previous:
            history.append(previous)
    st.session_state["navigation.page"] = page
    st.session_state[NAVIGATION_HISTORY_KEY] = history[-12:]
    st.session_state[NAVIGATION_CURRENT_KEY] = page
    return page


def render_application_header(
    *,
    title: str,
    action_renderer: Callable[[], None],
    connection_label: str = "연결됨",
    phase_label: str | None = None,
) -> None:
    """브랜드·현재 단계·실제 동작 button을 하나의 상단 헤더에 배치한다.

    Streamlit button은 HTML header 내부에 넣을 수 없으므로, 같은 container의
    우측 열에 네이티브 button을 렌더링한다. 이 방식은 버튼의 접근성·rerun
    동작을 유지하면서도 시각적으로 헤더 오른쪽에 고정한다.
    """

    with st.container(key="app-header"):
        brand_column, phase_column, action_column = st.columns([2, 3, 2])
        with brand_column:
            st.markdown(
                f'<span class="app-header-brand">{escape(title)}</span>'
                f'<span class="app-header-status">{escape(connection_label)}</span>',
                unsafe_allow_html=True,
            )
        with phase_column:
            if phase_label:
                st.markdown(
                    f'<div class="app-header-phase">{escape(phase_label)}</div>',
                    unsafe_allow_html=True,
                )
        with action_column:
            action_renderer()


def render_header_back_button(*, current_page: str, on_back: Callable[[], None] | None = None) -> None:
    """진행 게임은 저장·삭제 확인을 먼저 열고 일반 화면은 홈으로 이동한다.

    방문 이력으로 역할 공개 화면에 되돌아가는 혼동을 피하면서도 진행 게임의
    이탈 확인 계약을 보존한다. callback이 있으면 navigation은 해당 화면이 맡는다.
    """

    if current_page == "home":
        return
    if st.button("홈으로", key="header.back", width="stretch"):
        if on_back is not None:
            on_back()
        else:
            _navigate(page="home", history=[])


def _navigation_history(*, current_page: str) -> list[str]:
    """session의 손상된 page 값과 현재 화면의 중복 기록을 제거한다."""

    raw_history = st.session_state.get(NAVIGATION_HISTORY_KEY)
    history = (
        [page for page in raw_history if isinstance(page, str) and page in NAVIGATION_PAGES]
        if isinstance(raw_history, list)
        else []
    )
    while history and history[-1] == current_page:
        history.pop()
    return history


def _navigate(*, page: str, history: list[str]) -> None:
    """게임 상태는 보존하고 목적 화면과 검증된 방문 기록만 원자적으로 교체한다."""

    target = page if isinstance(page, str) and page in NAVIGATION_PAGES else "home"
    if target == "home":
        # 홈으로 돌아오면 진행 게임 자체를 지우지 않고 목록 projection만 다시 읽는다.
        for key in ("home.games", "home.games_error", "home.games_loaded_at", "home.games_loading"):
            st.session_state.pop(key, None)
        history = []
    st.session_state["navigation.page"] = target
    st.session_state[NAVIGATION_CURRENT_KEY] = target
    st.session_state[NAVIGATION_HISTORY_KEY] = history[-12:]
    st.rerun()
