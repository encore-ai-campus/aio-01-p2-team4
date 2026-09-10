"""역할 공개 단계 화면."""

from __future__ import annotations

from typing import Any

import streamlit as st

from frontend_user.app_pages.game_page import (
    _process_shell_pending,
    _render_save_control,
    _render_shell_command,
    render_game_exit_error,
    render_game_back_button,
    render_saved_control,
)
from frontend_user.components.action_panel import render_status_bar
from frontend_user.components.theme import render_application_header
from frontend_user.core.view_models import (
    own_private_view, private_fact_first_person, public_players, custom_role_description,
)

ROLE_REVEAL_CSS = """
<style>
:root {
  --role-blue: #2468ed;
  --role-blue-soft: #eaf2ff;
  --role-dark: #071426;
  --role-ink: #172033;
  --role-muted: #65728b;
  --role-border: #d9e2ef;
}
[data-testid="stAppViewContainer"] {
  color: var(--role-ink);
  background:
    radial-gradient(circle at 76% 22%, rgba(52, 101, 164, .32), transparent 24rem),
    linear-gradient(115deg, #06111f 0%, #0a1e38 52%, #06111f 100%);
}
[data-testid="stHeader"] { background: transparent; }
[data-testid="stMainBlockContainer"] {
  width: min(100%, 1180px);
  max-width: 1180px;
  padding: 0 1.5rem 3rem;
}
.role-header {
  display: flex; align-items: center; justify-content: space-between;
  min-height: 4.2rem; margin: 0 -1.5rem 2rem; padding: 0 1.5rem;
  color: #fff; background: rgba(5, 16, 32, .96); border-bottom: 1px solid #24324c;
}
.role-brand { font-size: 1.55rem; font-weight: 800; letter-spacing: -.06em; }
.role-status {
  display: inline-flex; align-items: center; gap: .4rem; margin-left: 1rem;
  padding: .42rem .7rem; border: 1px solid #2b3b57; border-radius: .55rem;
  color: #d8e2f3; font-size: .78rem;
}
.role-status::before { content: ""; width: .45rem; height: .45rem; border-radius: 50%; background: #31c477; }
.role-nav { display: flex; gap: .7rem; color: #d8e2f3; font-size: .82rem; }
.role-nav span { padding: .55rem .75rem; border: 1px solid #2b3b57; border-radius: .5rem; }
[class*="st-key-role-reveal-card"] {
  width: min(100%, 620px); margin: 0 auto; padding: 1.6rem 1.7rem 1.5rem !important;
  border: 4px solid #8cb5ff !important; border-radius: 1.35rem !important;
  background: rgba(255, 255, 255, .98) !important;
  box-shadow: 0 1.7rem 4rem rgba(0, 8, 25, .42);
}
[class*="st-key-role-reveal-card"] h2,
[class*="st-key-role-reveal-card"] h3,
[class*="st-key-role-reveal-card"] p { color: var(--role-ink); }
[class*="st-key-role-reveal-card"] [data-testid="stText"] {
  color: var(--role-ink) !important;
  -webkit-text-fill-color: var(--role-ink) !important;
  font-size: 1.7rem; font-weight: 800; line-height: 1.35;
  overflow-wrap: anywhere;
}
.role-pill {
  width: fit-content; margin: 0 auto .7rem; padding: .42rem .9rem;
  border-radius: 999px; color: #fff; background: var(--role-blue);
  font-size: .82rem; font-weight: 750;
}
.role-avatar {
  display: grid; width: 9.5rem; height: 9.5rem; margin: .8rem auto 1.1rem;
  place-items: center; border-radius: 50%; color: #174a93;
  background: radial-gradient(circle, #fff 0 26%, #dceaff 27% 65%, #edf4ff 66%);
  font-size: 4.8rem; box-shadow: inset 0 0 0 1px #d3e2f9;
}
.role-private-note {
  margin: .85rem 0 1rem; padding: .65rem .8rem; border-radius: .55rem;
  color: var(--role-blue); background: var(--role-blue-soft);
  font-size: .82rem; font-weight: 700; text-align: center;
}
[class*="st-key-role-alibi"], [class*="st-key-role-observation"] {
  padding: .8rem 1rem !important; border: 1px solid var(--role-border) !important;
  border-radius: .7rem !important; background: #fff !important;
}
[class*="st-key-role-alibi"] h4, [class*="st-key-role-observation"] h4 {
  margin-bottom: .15rem; color: var(--role-blue); font-size: .95rem;
}
[class*="st-key-role-begin"] button {
  min-height: 3.35rem; border: 0 !important; border-radius: .65rem !important;
  color: #fff !important; background: linear-gradient(135deg, #245fd6, #1f5ee5) !important;
  font-size: 1rem !important; font-weight: 750 !important;
}
.role-scenario {
  margin-bottom: .9rem; padding-bottom: .85rem; border-bottom: 1px solid var(--role-border);
  color: var(--role-muted); font-size: .84rem; text-align: center;
}
@media (max-width: 680px) {
  [data-testid="stMainBlockContainer"] { padding: 0 .8rem 2rem; }
  .role-header { margin: 0 -.8rem 1rem; padding: 0 .9rem; }
  .role-nav { display: none; }
  [class*="st-key-role-reveal-card"] { padding: 1.2rem 1rem !important; border-width: 2px !important; }
  .role-avatar { width: 7.5rem; height: 7.5rem; font-size: 3.7rem; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { transition-duration: .01ms !important; animation-duration: .01ms !important; }
}
</style>
"""

ROLE_PRESENTATION = {
    "MAFIA": (
        "마피아",
        "🥷",
        "밤에 다른 플레이어를 제거합니다. 게임이 끝날 때까지 정체를 숨기면 승리합니다.",
    ),
    "DETECTIVE": (
        "탐정",
        "🕵️",
        "밤에 한 명을 조사합니다. 마피아가 모두 제거되면 시민 승리입니다.",
    ),
    "DOCTOR": (
        "의사",
        "🩺",
        "밤에 한 명을 보호합니다. 마피아가 모두 제거되면 시민 승리입니다.",
    ),
    "CITIZEN": (
        "시민",
        "🧑",
        "대화와 투표로 마피아를 찾습니다. 마피아가 모두 제거되면 승리합니다.",
    ),
}


def render(snapshot: dict[str, Any]) -> None:
    """사건 정보와 본인 역할만 표시하고 다른 player 역할은 노출하지 않는다."""

    # snapshot의 private projection 가운데 본인 필드만 일반 Streamlit 텍스트로
    # 렌더링한다. Backend 문자열을 unsafe HTML에 삽입하지 않아 마크업 주입과
    # 다른 플레이어 정보의 우발적 노출을 함께 방지한다.
    game = snapshot.get("game", {})
    game_id = str(game.get("game_id"))
    client = st.session_state["game.client"]
    _process_shell_pending(client=client, game_id=game_id)
    st.markdown(ROLE_REVEAL_CSS, unsafe_allow_html=True)

    def render_header_actions() -> None:
        """낮 토론과 같은 헤더 저장·이탈 제어를 역할 공개에도 배치한다."""

        save_column, back_column = st.columns(2)
        with save_column:
            _render_save_control(client=client, game_id=game_id, snapshot=snapshot)
        with back_column:
            render_game_back_button(snapshot=snapshot)

    render_application_header(
        title="AI 마피아",
        action_renderer=render_header_actions,
    )
    render_game_exit_error()

    scenario = snapshot.get("scenario", {})
    render_status_bar(game_id=game_id, snapshot=snapshot)
    me = own_private_view(snapshot)
    role_name, role_icon, role_text = ROLE_PRESENTATION.get(
        me.get("role"),
        ("역할 확인 중", "❔", "역할 정보를 확인하는 중입니다."),
    )

    if custom_role_description(me):
        role_name = me["role_name"]
        role_text = custom_role_description(me)
    with st.container(key="role-reveal-card", border=True):
        st.markdown('<div class="role-pill">🎭 &nbsp; 역할 공개</div>', unsafe_allow_html=True)
        if custom_role_description(me):
            st.text(f"당신은 {role_name}입니다")
        else:
            st.markdown(f"## 당신은 **{role_name}**입니다")
        st.markdown(f'<div class="role-avatar" aria-hidden="true">{role_icon}</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="role-scenario">현재 사건 정보</div>',
            unsafe_allow_html=True,
        )
        st.subheader(str(scenario.get("title", "사건 정보")))
        st.write(str(scenario.get("background", "")))
        locations = scenario.get("locations", [])
        location_text = ", ".join(str(item) for item in locations) if isinstance(locations, list) else ""
        st.caption(
            f"피해자: {scenario.get('victim', '알 수 없음')} · 장소: {location_text} · "
            f"전체 {game.get('player_count', len(public_players(snapshot)))}명 · "
            f"시작 마피아 {game.get('mafia_count', '확인 중')}명"
        )
        st.info(role_text)
        with st.container(key="role-alibi", border=True):
            st.markdown("#### ◷ 나의 알리바이")
            st.write(private_fact_first_person(
                me.get("alibi"), me=me, players=public_players(snapshot),
            ))
        with st.container(key="role-observation", border=True):
            st.markdown("#### ◉ 내가 본 것")
            st.write(private_fact_first_person(
                me.get("observation"), me=me, players=public_players(snapshot),
            ))
        st.markdown(
            '<div class="role-private-note">🔒 &nbsp; 이 정보는 나에게만 보여요</div>',
            unsafe_allow_html=True,
        )

        with st.container(key="role-begin"):
            _render_shell_command(client=client, game_id=game_id, snapshot=snapshot, command_type="BEGIN_GAME")
        if game.get("status") == "SAVED":
            render_saved_control(client=client, snapshot=snapshot)
        else:
            pending = st.session_state.get("game.resume_pending")
            if isinstance(pending, dict) and pending.get("game_id") == game_id:
                _render_shell_command(client=client, game_id=game_id, snapshot=snapshot, command_type="RESUME")
