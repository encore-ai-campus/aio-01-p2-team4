"""게임 목록과 새 게임 CTA를 표시하는 F2 홈 화면."""

from __future__ import annotations

from collections.abc import Mapping
from html import escape
from time import monotonic
from typing import Any

import streamlit as st

from frontend_user.components.theme import render_application_header
from frontend_user.core.api_client import ApiClient, ApiResponseError, ApiUnavailableError
from frontend_user.core.scenario_images import home_image_path, scenario_image_path

HOME_GAMES_TTL_SECONDS = 30

HOME_CSS = """
<style>
:root { --home-ink:#172033; --home-muted:#65728b; --home-blue:#2468ed; --home-dark:#0b1730; --home-border:#dfe5ef; --home-bg:#f4f7fb; }
[data-testid="stAppViewContainer"] { background:var(--home-bg); }
[data-testid="stHeader"] { background:transparent; }
[data-testid="stMainBlockContainer"] { width:min(100%,1180px); max-width:1180px; padding:0 1.5rem 3rem; }
.home-header { display:flex; align-items:center; justify-content:space-between; min-height:4.2rem; margin:0 -1.5rem 2rem; padding:0 1.5rem; color:#fff; background:var(--home-dark); border-bottom:1px solid #24324c; }
.home-brand { font-size:1.55rem; font-weight:800; letter-spacing:-.06em; }
.home-status { display:inline-flex; align-items:center; gap:.4rem; margin-left:1rem; padding:.42rem .7rem; border:1px solid #2b3b57; border-radius:.55rem; color:#d8e2f3; font-size:.78rem; }
.home-status::before { content:""; width:.45rem; height:.45rem; border-radius:50%; background:#31c477; }
.home-nav { display:flex; gap:.7rem; color:#d8e2f3; font-size:.82rem; }
.home-nav span { padding:.55rem .75rem; border:1px solid #2b3b57; border-radius:.5rem; }
.home-hero { display:grid; grid-template-columns:.9fr 1.1fr; gap:1.5rem; align-items:stretch; margin-bottom:1.25rem; }
.home-hero-copy { padding:.5rem 0 0; }
.home-hero h1 { margin:0; color:var(--home-ink); font-size:clamp(2rem,4vw,3rem); line-height:1.15; letter-spacing:-.055em; }
.home-hero p { margin:.8rem 0 1.5rem; color:var(--home-muted); font-size:1rem; }
.home-hero-art { min-height:13.5rem; overflow:hidden; position:relative; border-radius:.65rem; background:linear-gradient(160deg,#102e5c,#061327 65%,#1b3152); box-shadow:0 1rem 2rem rgba(20,42,81,.14); }
[class*="st-key-home-hero-image"] { overflow:hidden; padding:0 !important; border-radius:.65rem; box-shadow:0 1rem 2rem rgba(20,42,81,.14); }
[class*="st-key-home-hero-image"] img { display:block; width:100%; height:auto; }
.home-hero-art::before { content:"☾"; position:absolute; top:.75rem; right:24%; color:#8ec8fa; font-size:3rem; }
.home-hero-art::after { content:"🤖  🤖  🤖  🤖  🤖  🤖"; position:absolute; right:1rem; bottom:.85rem; color:#f6f8fb; font-size:2.1rem; letter-spacing:-.5rem; filter:saturate(.8); }
.home-hero-scene { position:absolute; right:1rem; bottom:4.1rem; color:#80a6d6; font-size:.75rem; letter-spacing:.35rem; }
.home-section-title { margin:1.3rem 0 .7rem; color:var(--home-ink); font-size:1.25rem; font-weight:800; }
.home-player-box { padding:1rem 1.15rem; border:1px solid var(--home-border); border-radius:.65rem; background:#fff; }
.home-player-title { margin-bottom:.5rem; color:var(--home-ink); font-weight:800; }
.home-card { min-height:8.5rem; padding:.55rem; border:1px solid var(--home-border); border-radius:.65rem; background:#fff; box-shadow:0 .35rem 1rem rgba(20,42,81,.05); }
.home-card-thumb { display:grid; min-height:6.5rem; place-items:center; overflow:hidden; border-radius:.45rem; color:#fff; background:linear-gradient(145deg,#0a1c39,#315a86); font-size:2rem; }
.home-card-thumb.snow { background:linear-gradient(145deg,#20395d,#8eb2da); }
.home-card-title { margin-top:.65rem; color:var(--home-ink); font-size:1rem; font-weight:800; }
.home-card-meta { margin:.25rem 0 .6rem; color:var(--home-muted); font-size:.75rem; }
[class*="st-key-home-game-card"] { padding:.55rem !important; }
.home-card-badge { display:inline-block; padding:.25rem .45rem; border-radius:.35rem; color:#16864d; background:#e5f8ec; font-size:.72rem; }
.home-card-badge.saved { color:#c66c08; background:#fff2d9; }
[data-testid="stButton"] button:not([kind="primary"]), [data-testid="baseButton-secondary"] { color:#1f4fbd !important; background:#f7faff !important; border:1px solid #b8cdf8 !important; }
[data-testid="stButton"] button:not([kind="primary"]) *, [data-testid="baseButton-secondary"] * { color:#1f4fbd !important; }
[data-testid="stButton"] button:not([kind="primary"]):hover:not(:disabled), [data-testid="baseButton-secondary"]:hover:not(:disabled) { color:#17449f !important; background:#eaf2ff !important; }
[data-testid="stButton"] button[kind="primary"] { color:#fff !important; background:linear-gradient(135deg,#3568f2,#5b83ff) !important; border-color:#3568f2 !important; }
[data-testid="stButton"] button[kind="primary"] p { color:#fff !important; }
[class*="st-key-home-retry"] button { color:#fff !important; background:linear-gradient(135deg,#3568f2,#5b83ff) !important; border-color:#3568f2 !important; }
[class*="st-key-home-retry"] button p { color:#fff !important; }
@media (max-width:760px) { .home-hero { grid-template-columns:1fr; } .home-hero-art { min-height:10rem; } .home-nav { display:none; } }
</style>
"""


def should_load_games(session_state: Mapping[str, object]) -> bool:
    """최초 진입과 캐시 만료 뒤 재조회하되 실패 시 자동 재시도 반복을 막는다."""

    if "home.games_error" in session_state or session_state.get("home.games_loading"):
        return False
    loaded_at = session_state.get("home.games_loaded_at")
    return (
        "home.games" not in session_state
        or not isinstance(loaded_at, (int, float))
        or monotonic() - loaded_at >= HOME_GAMES_TTL_SECONDS
    )


def _invalidate_games() -> None:
    """홈 이탈과 명시적 새로고침에서 목록만 비워 저장·재개 뒤 최신 상태를 받는다."""

    for key in ("home.games", "home.games_error", "home.games_loaded_at", "home.games_loading"):
        st.session_state.pop(key, None)


def _player_info_ready() -> bool:
    """앱 시작 시 생성·확인된 UUID가 있을 때 게임 진입을 허용한다."""

    user_id = st.session_state.get("identity.user_id")
    return bool(user_id)


def render(client: ApiClient) -> None:
    """게임 목록의 loading·empty·error·success 상태를 홈 레이아웃 안에서 표시한다."""

    st.markdown(HOME_CSS, unsafe_allow_html=True)
    # 홈 헤더에는 별도 동작 버튼을 표시하지 않지만 공통 헤더의 필수 콜백 계약은 유지한다.
    render_application_header(title="AI 마피아", action_renderer=lambda: None)
    hero_copy, hero_art = st.columns([.9, 1.1], gap="large")
    with hero_copy:
        st.markdown(
            '<div class="home-hero-copy"><h1>AI 마피아게임</h1>'
            "<p>매번 새로운 AI 플레이어들과 펼치는 예측 불허 심리 추리전!</p>"
            "</p>시민이 되어 마피아를 찾을 것인가, 마피아가 되어 AI를 지배할 것인가?</p>"
            "<p>6~9명 · 약 15분</p></div>",
            unsafe_allow_html=True,
        )
    with hero_art:
        main_path = home_image_path()
        if main_path is not None:
            with st.container(key="home-hero-image"):
                st.image(str(main_path), width="stretch")
        else:
            st.markdown(
                '<div class="home-hero-art"><span class="home-hero-scene">▰ ▰ ▰ ▰ ▰</span></div>',
                unsafe_allow_html=True,
            )
    with st.container(border=True):
        st.markdown('<div class="home-player-title">플레이어 정보</div>', unsafe_allow_html=True)
        st.caption("현재 구조에서는 UUID를 게임 식별자로 사용합니다.")
        user_id = st.session_state.get("identity.user_id")
        st.text_input(
            "게임 식별자 (UUID)",
            value=str(user_id or ""),
            disabled=True,
            key="home.user_id",
        )

    player_info_ready = _player_info_ready()
    if st.button(
        "새 게임 시작  ›",
        type="primary",
        key="home.new_game",
        disabled=not player_info_ready,
        width="stretch",
    ):
        _invalidate_games()
        st.session_state["navigation.page"] = "create"
        st.rerun()

    home_tab, rules_tab = st.tabs(["홈", "게임 규칙"])
    with home_tab:
        # UUID를 확인하기 전에는 다른 게임의 시나리오·진행 상태를 노출하지 않는다.
        # UUID가 준비된 뒤에만 목록 API cache를 화면에 사용한다.
        if not player_info_ready:
            st.info("게임 식별자를 확인한 뒤 게임 목록을 불러올 수 있어요.")
        else:
            st.markdown('<div class="home-section-title">게임 불러오기</div>', unsafe_allow_html=True)
            if st.button("새로고침", key="home.refresh"):
                _invalidate_games()
                st.rerun()
            if st.session_state.get("home.games_loading"):
                st.info("게임 목록을 불러오는 중이에요.")
            else:
                error = st.session_state.get("home.games_error")
                if isinstance(error, str):
                    st.error("게임 목록을 불러오지 못했어요.")
                    if st.button("다시 시도", key="home.retry"):
                        _invalidate_games()
                        st.rerun()
                else:
                    games = st.session_state.get("home.games", [])
                    if not isinstance(games, list) or not games:
                        st.info("아직 게임이 없어요. 새 게임을 시작해 보세요.")
                    else:
                        groups = (
                            ("이어하기", {"IN_PROGRESS", "SAVED"}, "진행 중이거나 저장된 게임이 없습니다."),
                            ("최근 완료 게임", {"COMPLETED"}, "아직 완료한 게임이 없습니다."),
                            ("복구 필요", {"FAILED"}, "복구가 필요한 게임이 없습니다."),
                        )
                        for title, statuses, empty_message in groups:
                            st.markdown(
                                f'<div class="home-section-title">{title}</div>',
                                unsafe_allow_html=True,
                            )
                            _render_group(
                                [
                                    game for game in games
                                    if isinstance(game, dict) and game.get("status") in statuses
                                ][:3],
                                empty_message=empty_message,
                                player_info_ready=player_info_ready,
                            )

    with rules_tab:
        st.markdown('<div class="home-section-title">AI 마피아 게임 규칙</div>', unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown("### 게임 방식")
            st.write(
                "AI 마피아는 1명의 사용자와 AI 플레이어들이 함께 진행하는 추리 게임입니다."
                "사용자는 자신의 역할에 따라 시민 진영이면 마피아를 찾고, "
                "마피아면 정체를 숨기며 게임을 진행합니다."
            )

            st.divider()
            st.markdown("### 기본 진행")
            st.markdown(
                "- 6~9명의 플레이어가 참여합니다.\n"
                "- 역할은 게임 시작 시 무작위로 배정됩니다.\n"
                "- 낮에는 사건 정보를 확인하고 토론 후 투표합니다.\n"
                "- 밤에는 각 역할에 맞는 행동을 진행합니다.\n"
                "- 첫날은 토론만 진행하며 투표하지 않습니다.\n"
                "- 게임은 최대 5번째 밤까지 진행됩니다."
            )

            st.divider()
            st.markdown("### 직업별 역할")
            st.markdown(
                "- **마피아**: 밤에 공격할 플레이어를 선택합니다.\n"
                "- **탐정**: 밤에 한 명을 조사해 마피아 여부를 확인합니다.\n"
                "- **의사**: 밤에 본인을 포함해 한 명을 보호합니다.\n"
                "- **시민**: 밤 행동 없이 토론과 투표로 마피아를 찾습니다."
            )

            st.divider()
            st.markdown("### 승리 조건")
            st.markdown(
                "- **시민 진영**: 모든 마피아를 제거하면 승리합니다.\n"
                "- **마피아 진영**: 생존 마피아 수가 시민 진영 생존자 수 이상이면 승리합니다.\n"
                "- 마지막 지목에서 마피아를 찾으면 시민 승리, 시민을 지목하면 마피아 승리입니다."
            )

            st.divider()
            st.markdown("### 직업 커스텀")
            st.markdown(
                "- 새 게임 설정에서 `커스텀 직업` 모드를 선택할 수 있습니다.\n"
                "- 능력은 최대 3개까지 선택할 수 있습니다.\n"
                "- 설정한 커스텀 역할은 사용자에게 배정됩니다."
            )


def load_games(client: ApiClient) -> None:
    """목록 endpoint를 호출하고 raw payload를 화면에 노출하지 않는다."""

    # Backend가 소유한 목록만 사용하고, Front가 status나 소유권을 추론하지 않도록 한다.
    try:
        response = client.get_games(limit=20)
        data = response.get("data")
        items = data.get("items") if isinstance(data, Mapping) else None
        if not isinstance(items, list) or not all(
            isinstance(item, dict)
            and isinstance(item.get("game_id"), str)
            and bool(item["game_id"].strip())
            and isinstance(item.get("status"), str)
            and item["status"] in {"IN_PROGRESS", "SAVED", "COMPLETED", "FAILED"}
            for item in items
        ):
            raise ApiUnavailableError(status_code=503, code="INVALID_RESPONSE")
        st.session_state["home.games"] = items
        st.session_state["home.games_loaded_at"] = monotonic()
        st.session_state.pop("home.games_error", None)
    except (ApiResponseError, ApiUnavailableError) as error:
        st.session_state.pop("home.games", None)
        st.session_state.pop("home.games_loaded_at", None)
        st.session_state["home.games_error"] = getattr(error, "code", "DEPENDENCY_UNAVAILABLE")
    finally:
        st.session_state["home.games_loading"] = False


def _render_group(
    games: list[dict[str, Any]], *, empty_message: str, player_info_ready: bool,
) -> None:
    """공개 요약 필드만 카드에 표시하고 게임 상태 변경은 Backend에 위임한다."""

    if not games:
        st.caption(empty_message)
        return
    columns = st.columns(len(games))
    for column, game in zip(columns, games, strict=False):
        with column:
            status = game.get("status")
            title = escape(str(game.get("scenario_title", "사건 정보 없음")))
            label = {
                "IN_PROGRESS": "진행 중", "SAVED": "저장됨",
                "COMPLETED": "완료", "FAILED": "복구 필요",
            }.get(status, "상태 확인 필요")
            action_label = {
                "IN_PROGRESS": "이어하기",
                "SAVED": "불러오기",
                "COMPLETED": "결과 보기",
                "FAILED": "복구하기",
            }.get(status, "게임 열기")
            game_id = game.get("game_id")
            badge_class = " saved" if status == "SAVED" else ""
            with st.container(key=f"home-game-card.{game_id}", border=True):
                image_path = scenario_image_path(game)
                if image_path is not None:
                    st.image(str(image_path), width="stretch")
                else:
                    st.markdown('<div class="home-card-thumb">📺</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="home-card-title">{title}</div>', unsafe_allow_html=True)
                st.markdown(
                    f'<div class="home-card-meta"><span class="home-card-badge{badge_class}">{label}</span>'
                    f" · Day {escape(str(game.get('day_number', 1)))}"
                    f" · Round {escape(str(game.get('round', 0)))}</div>",
                    unsafe_allow_html=True,
                )
            if st.button(
                action_label + "  ›",
                key=f"home.card.{game_id}",
                disabled=not player_info_ready,
                width="stretch",
            ) and isinstance(game_id, str):
                _open_game(game_id)


def _open_game(game_id: str) -> None:
    """카드 이미지와 하단 CTA가 공유하는 기존 게임 진입 이벤트를 실행한다."""

    _invalidate_games()
    st.session_state["game.game_id"] = game_id
    st.session_state["navigation.page"] = "game"
    st.rerun()
