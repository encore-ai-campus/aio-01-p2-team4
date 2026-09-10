"""새 게임 설정과 생성 요청을 담당하는 F2 화면."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import streamlit as st

from frontend_user.components.theme import render_application_header, render_header_back_button
from frontend_user.core.api_client import ApiClient, ApiResponseError, ApiUnavailableError

from frontend_user.core.commands import ABILITY_DESCRIPTIONS, normalize_role_name, validate_ability_catalog

ROLE_COUNTS = {
    6: {"마피아": 1, "탐정": 1, "의사": 1, "시민": 3},
    7: {"마피아": 1, "탐정": 1, "의사": 1, "시민": 4},
    8: {"마피아": 2, "탐정": 1, "의사": 1, "시민": 4},
    9: {"마피아": 2, "탐정": 1, "의사": 1, "시민": 5},
}

SETUP_AI_IMAGE_PATH = Path(__file__).resolve().parents[1] / "assets" / "ai_image.jpg"

SETUP_CSS = """
<style>
:root { --setup-ink:#172033; --setup-muted:#65728b; --setup-blue:#2468ed; --setup-dark:#0b1730; --setup-border:#dfe5ef; --setup-bg:#f4f7fb; }
[data-testid="stAppViewContainer"] { background:var(--setup-bg); }
[data-testid="stHeader"] { background:transparent; }
[data-testid="stMainBlockContainer"] { width:min(100%,1180px); max-width:1180px; padding:0 1.5rem 3rem; }
.setup-header { display:flex; align-items:center; justify-content:space-between; min-height:4.2rem; margin:0 -1.5rem 2rem; padding:0 1.5rem; color:#fff; background:var(--setup-dark); border-bottom:1px solid #24324c; }
.setup-brand { font-size:1.55rem; font-weight:800; letter-spacing:-.06em; }
.setup-status { display:inline-flex; align-items:center; gap:.4rem; margin-left:1rem; padding:.42rem .7rem; border:1px solid #2b3b57; border-radius:.55rem; color:#d8e2f3; font-size:.78rem; }
.setup-status::before { content:""; width:.45rem; height:.45rem; border-radius:50%; background:#31c477; }
.setup-nav { display:flex; gap:.7rem; color:#d8e2f3; font-size:.82rem; }
.setup-nav span { padding:.55rem .75rem; border:1px solid #2b3b57; border-radius:.5rem; }
.setup-intro-copy { margin-bottom:1.25rem; }
.setup-breadcrumb { margin-bottom:1.5rem; color:var(--setup-muted); font-size:.9rem; }
.setup-breadcrumb strong { color:var(--setup-blue); }
.setup-intro-copy h1 { margin:0; color:var(--setup-ink); font-size:clamp(2.3rem,5vw,3.5rem); line-height:1.15; letter-spacing:-.06em; }
.setup-intro-copy p { margin:.85rem 0 0; color:var(--setup-muted); font-size:1.1rem; }
.setup-art { min-height:14rem; position:relative; overflow:hidden; border-radius:.7rem; background:linear-gradient(160deg,#eaf2fd 0%,#f9fbff 55%,#d9e5f5 100%); }
[class*="st-key-setup-ai-image"] { min-height:14rem; display:flex; align-items:center; overflow:hidden; padding:0 !important; border-radius:.7rem; background:#102e5c; box-shadow:0 1rem 2rem rgba(20,42,81,.14); }
[class*="st-key-setup-ai-image"] img { display:block; width:100%; height:auto; }
.setup-art::before { content:"☾"; position:absolute; top:.5rem; right:24%; color:#1f4c87; font-size:3.2rem; }
.setup-art::after { content:"🏠   🤖   🕵️   🤖   🤖   👓"; position:absolute; right:1rem; bottom:1.1rem; color:#18365f; font-size:2rem; white-space:nowrap; filter:saturate(.75); }
.setup-skyline { position:absolute; right:1rem; bottom:5rem; color:#557aab; font-size:2rem; letter-spacing:.5rem; }
.setup-panel { padding:1.2rem; border:1px solid var(--setup-border); border-radius:.8rem; background:#fff; box-shadow:0 .6rem 1.6rem rgba(20,42,81,.06); }
.setup-panel-title { margin-bottom:.9rem; color:var(--setup-ink); font-size:1.15rem; font-weight:800; }
[class*="st-key-game-player-count-"] button {
  min-height:10rem; padding:.8rem .6rem; white-space:pre-line; line-height:1.55;
  color:var(--setup-ink) !important; background:#fff !important;
  border:1px solid var(--setup-border) !important; border-radius:.8rem !important;
  font-size:1.05rem !important; font-weight:800 !important;
}
[class*="st-key-game-player-count-"] button:hover:not(:disabled) {
  border-color:#8db2ff !important; background:#f7faff !important;
}
[class*="st-key-game-player-count-6-selected"] button,
[class*="st-key-game-player-count-7-selected"] button,
[class*="st-key-game-player-count-8-selected"] button,
[class*="st-key-game-player-count-9-selected"] button {
  border:2px solid var(--setup-blue) !important; color:var(--setup-blue) !important;
  background:linear-gradient(145deg,#fff,#eef4ff) !important;
  box-shadow:0 0 0 3px rgba(36,104,237,.08) !important;
}
[data-testid="stButton"] button:not([kind="primary"]), [data-testid="baseButton-secondary"] { color:#1f4fbd !important; background:#f7faff !important; border:1px solid #b8cdf8 !important; }
[data-testid="stButton"] button:not([kind="primary"]) *, [data-testid="baseButton-secondary"] * { color:#1f4fbd !important; }
[data-testid="stButton"] button:not([kind="primary"]):hover:not(:disabled), [data-testid="baseButton-secondary"]:hover:not(:disabled) { color:#17449f !important; background:#eaf2ff !important; }
[data-testid="stButton"] button[kind="primary"] { color:#fff !important; background:linear-gradient(135deg,#3568f2,#5b83ff) !important; border-color:#3568f2 !important; }
[data-testid="stButton"] button[kind="primary"] p { color:#fff !important; }
[class*="st-key-game-create-cancel"] button:not([kind="primary"]), [class*="st-key-game-create-cancel"] [data-testid="baseButton-secondary"] { color:#53627a !important; background:#f1f4f8 !important; border-color:#cbd5e1 !important; }
[class*="st-key-game-create-cancel"] button:not([kind="primary"]) *, [class*="st-key-game-create-cancel"] [data-testid="baseButton-secondary"] * { color:#53627a !important; }
[class*="st-key-game-create-cancel"] button:not([kind="primary"]):hover:not(:disabled), [class*="st-key-game-create-cancel"] [data-testid="baseButton-secondary"]:hover:not(:disabled) { color:#334155 !important; background:#e3e9f1 !important; }
[data-testid="stMainBlockContainer"] :is(
  [data-testid="stWidgetLabel"], [data-testid="stRadio"], [data-testid="stText"],
  [data-testid="stCaptionContainer"]
),
[data-testid="stMainBlockContainer"] :is(
  [data-testid="stWidgetLabel"], [data-testid="stRadio"], [data-testid="stText"],
  [data-testid="stCaptionContainer"]
) * {
  color:var(--setup-ink) !important; -webkit-text-fill-color:var(--setup-ink) !important;
}
[data-testid="stMainBlockContainer"] [data-testid="stMultiSelect"] [role="group"]:has(> [data-testid="stMultiSelectTagsContainer"]) {
  color:var(--setup-ink) !important; background:#fff !important; border-color:#8292ad !important;
}
[data-testid="stMainBlockContainer"] [data-testid="stMultiSelect"] [role="group"]:has(> [data-testid="stMultiSelectTagsContainer"]) > button {
  color:var(--setup-ink) !important;
}
[data-testid="stMainBlockContainer"] [data-testid="stMultiSelect"] input {
  color:var(--setup-ink) !important; -webkit-text-fill-color:var(--setup-ink) !important;
}
[data-testid="stMainBlockContainer"] [data-testid="stMultiSelect"] input::placeholder {
  color:var(--setup-muted) !important; -webkit-text-fill-color:var(--setup-muted) !important; opacity:1;
}
[data-testid="stMultiSelectDropdown"] { color:var(--setup-ink) !important; background:#fff !important; }
[data-testid="stMultiSelectDropdown"] [role="option"] { color:var(--setup-ink) !important; }
.setup-rules { display:flex; align-items:center; gap:1.5rem; margin-top:1.1rem; padding:1rem 1.2rem; border:1px solid var(--setup-border); border-radius:.8rem; background:#fff; }
.setup-rule-book { font-size:2.6rem; }
.setup-rules-title { margin-bottom:.4rem; color:var(--setup-ink); font-size:1.05rem; font-weight:800; }
.setup-rules-list { display:flex; flex-wrap:wrap; gap:1rem 1.7rem; margin:0; padding:0; color:var(--setup-muted); list-style:none; }
.setup-rules-list li::before { content:"•"; margin-right:.5rem; color:var(--setup-blue); font-size:1.2rem; }
.setup-note { margin-top:1rem; color:var(--setup-muted); text-align:center; }
@media (max-width:760px) { .setup-art, .setup-ai-image { min-height:10rem; } .setup-nav { display:none; } .setup-rules { align-items:flex-start; } .setup-rules-list { display:block; } .setup-rules-list li { margin:.35rem 0; } }
</style>
"""


def render(client: ApiClient) -> None:
    """인원 선택을 검증하고 생성 POST를 rerun 이후 한 번만 실행한다."""

    # 성공 직후에는 완료 경로로 바로 이동하므로, 생성 화면에 남은 성공 값은
    # 이전 게임에서 돌아온 상태다. 결과가 불명확한 요청은 같은 key 재시도를 위해 보존한다.
    previous = st.session_state.get("game.create_pending")
    if isinstance(previous, dict) and previous.get("status") == "SUCCEEDED":
        st.session_state.pop("game.create_pending", None)
        st.session_state.pop("game.game_id", None)
        st.session_state.pop("game.latest_snapshot", None)

    st.markdown(SETUP_CSS, unsafe_allow_html=True)
    render_application_header(
        title="AI 마피아",
        action_renderer=lambda: render_header_back_button(current_page="create"),
    )
    intro_copy, intro_art = st.columns([.8, 1.2], gap="large")
    with intro_copy:
        st.markdown(
            '<div class="setup-intro-copy"><h1>새 게임 설정</h1>'
            '<p>함께 플레이할 인원을 선택해 주세요</p></div>',
            unsafe_allow_html=True,
        )
    with intro_art:
        if SETUP_AI_IMAGE_PATH.is_file():
            with st.container(key="setup-ai-image"):
                st.image(str(SETUP_AI_IMAGE_PATH), width="stretch")
        else:
            st.markdown(
                '<div class="setup-art"><span class="setup-skyline">▰ ▰ ▰ ▰ ▰</span></div>',
                unsafe_allow_html=True,
            )

    pending = st.session_state.get("game.create_pending")
    in_flight = isinstance(pending, dict) and pending.get("status") in {
        "PENDING_TO_RENDER", "IN_FLIGHT", "RETRYABLE_UNKNOWN",
    }
    selected = _render_player_choices(in_flight=in_flight)
    custom_role, custom_valid = _render_role_settings(client, in_flight=in_flight)
    role_assignment_text = (
        "사용자는 커스텀한 역할로 배정됩니다"
        if st.session_state.get("game.create_mode") == "CUSTOM_ROLE"
        else "역할은 무작위로 배정됩니다"
    )
    st.markdown(
        '<section class="setup-rules"><div class="setup-rule-book">📘</div><div>'
        '<div class="setup-rules-title">게임 방식</div><ul class="setup-rules-list">'
        f'<li>{role_assignment_text}</li><li>최대 5번째 밤까지 진행됩니다</li>'
        '<li>게임 중 언제든 저장할 수 있습니다</li></ul></div></section>',
        unsafe_allow_html=True,
    )

    button_left, button_right = st.columns([1.1, .6])
    with button_left:
        create_clicked = st.button("게임 만들기", type="primary", key="game.create_submit", disabled=in_flight or not custom_valid, width="stretch")
    with button_right:
        cancel_clicked = st.button("취소", key="game.create_cancel", disabled=in_flight, width="stretch")
    if create_clicked:
        st.session_state["game.create_pending"] = {
            "status": "PENDING_TO_RENDER",
            "player_count": selected,
            "custom_role": deepcopy(custom_role),
            "idempotency_key": str(uuid4()),
        }
        st.rerun()
    if cancel_clicked:
        st.session_state["navigation.page"] = "home"
        st.rerun()

    pending = st.session_state.get("game.create_pending")
    if not isinstance(pending, dict):
        return
    if pending.get("status") == "PENDING_TO_RENDER":
        pending["status"] = "IN_FLIGHT"
        st.session_state["game.create_pending"] = pending
        st.rerun()
    if pending.get("status") != "IN_FLIGHT":
        _render_terminal(pending)
        return

    st.info("게임을 만들고 있어요. 잠시만 기다려 주세요.")
    try:
        kwargs = {"mode": "CUSTOM_ROLE", "custom_role": deepcopy(pending["custom_role"])} if pending.get("custom_role") else {}
        response = client.create_game(player_count=int(pending["player_count"]), idempotency_key=str(pending["idempotency_key"]), **kwargs)
        data = response.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("game_id"), str):
            raise ApiUnavailableError(status_code=503, code="INVALID_RESPONSE")
        snapshot = client.get_game(data["game_id"])
        st.session_state["game.create_pending"] = {**pending, "status": "SUCCEEDED", "game_id": data["game_id"], "snapshot": snapshot}
        st.session_state["game.latest_snapshot"] = snapshot
        st.session_state["game.game_id"] = data["game_id"]
        # 생성 직후 받은 snapshot은 ROLE_REVEAL 상태다. 중간 완료 화면을 거치지 않고
        # dispatcher가 같은 snapshot의 비공개 역할 공개 화면으로 바로 이동하게 한다.
        st.session_state["navigation.page"] = "game"
    except ApiResponseError as error:
        status = "RETRYABLE_UNKNOWN" if error.status_code >= 500 else "REJECTED"
        st.session_state["game.create_pending"] = {**pending, "status": status, "code": error.code}
    except (ApiUnavailableError, ValueError) as error:
        st.session_state["game.create_pending"] = {**pending, "status": "RETRYABLE_UNKNOWN", "code": getattr(error, "code", "DEPENDENCY_UNAVAILABLE")}
    st.rerun()


def _render_player_choices(*, in_flight: bool) -> int:
    """6~9명 선택을 하나의 큰 button으로 표시하고 기존 session 선택값을 유지한다.

    인원 카드와 별도의 ``선택`` button을 함께 두면 같은 결정을 두 번 해야 하는 것처럼
    보인다. 각 인원 option 자체를 단일 제어로 만들어 클릭 영역과 선택 결과를 일치시킨다.
    """

    selected = st.session_state.setdefault("game.player_count", 6)
    if selected not in ROLE_COUNTS:
        selected = 6
        st.session_state["game.player_count"] = selected
    columns = st.columns(4)
    for column, count in zip(columns, (6, 7, 8, 9), strict=True):
        with column:
            selected_label = "✓ 선택됨\n" if selected == count else ""
            with st.container(key=f"game-player-count-{count}{'-selected' if selected == count else ''}"):
                if st.button(
                    f"{selected_label}♟  {count}명\nAI 플레이어 {count - 1}명",
                    key=f"game.player_count.{count}",
                    disabled=in_flight,
                    width="stretch",
                ):
                    st.session_state["game.player_count"] = count
                    st.rerun()
    return int(selected)


def _render_terminal(pending: dict[str, object]) -> None:
    """생성 terminal 결과를 고정 문구로 표시하고 같은 key 재시도를 제공한다."""

    status = pending.get("status")
    if status == "SUCCEEDED":
        st.session_state["navigation.page"] = "game"
        st.rerun()
    elif status == "RETRYABLE_UNKNOWN":
        st.warning("결과를 확인하지 못했어요. 같은 요청으로 다시 확인할 수 있습니다.")
        if st.button("같은 요청 다시 시도", key="game.create_retry"):
            st.session_state["game.create_pending"] = {**pending, "status": "IN_FLIGHT"}
            st.rerun()
    elif status == "REJECTED":
        st.error("게임을 만들 수 없어요. 입력과 Backend 상태를 확인해 주세요.")


def _render_role_settings(client: ApiClient, *, in_flight: bool) -> tuple[dict | None, bool]:
    """catalog 실패는 커스텀 생성만 막으며 응답 불명 요청의 선택값은 고정한다."""

    with st.container(border=True, key="game-role-settings"):
        st.subheader("직업 설정")
        mode = st.radio("게임 모드", ["STANDARD", "CUSTOM_ROLE"],
                        format_func=lambda value: {"STANDARD": "기본 역할", "CUSTOM_ROLE": "커스텀 직업"}[value],
                        key="game.create_mode", disabled=in_flight, horizontal=True)
        if mode == "STANDARD":
            return None, True
        faction = st.radio("진영", ["CITIZEN", "MAFIA"],
                           format_func=lambda value: "시민 진영" if value == "CITIZEN" else "마피아 진영",
                           key="game.create_faction", disabled=in_flight, horizontal=True)
        name = st.text_input(
            "자유 직업명",
            key="game.create_role_name",
            disabled=in_flight,
            placeholder="직업명은 공백 정리 후 1~40자로 입력해 주세요.",
        )
        if "game.ability_catalog" not in st.session_state:
            with st.spinner("능력 목록을 불러오고 있습니다."):
                try:
                    response = client.get_custom_role_abilities()
                    data = validate_ability_catalog(response)
                    st.session_state["game.ability_catalog"] = data
                except ApiResponseError:
                    st.session_state["game.ability_catalog"] = None
        data = st.session_state.get("game.ability_catalog")
        abilities = data.get("abilities") if isinstance(data, dict) else None
        if validate_ability_catalog({"data": data}) is None:
            st.warning("능력 목록을 확인할 수 없습니다. 기본 역할로 생성하거나 다시 시도해 주세요.")
            if st.button("능력 목록 다시 시도", key="game.catalog_retry", disabled=in_flight):
                st.session_state.pop("game.ability_catalog", None)
                st.rerun()
            return None, False
        allowed = {item["id"]: item for item in abilities if faction in item["factions"]
                   and (faction == "MAFIA" or item["id"] != "night.attack.v1")}
        if not allowed or faction == "MAFIA" and "night.attack.v1" not in allowed:
            st.warning("현재 진영의 능력 목록이 비어 있습니다.")
            if st.button("능력 목록 다시 시도", key="game.catalog_retry", disabled=in_flight):
                st.session_state.pop("game.ability_catalog", None)
                st.rerun()
            return None, False
        for ability_id, item in allowed.items():
            with st.container(border=True):
                if ability_id in {"night.attack.v1"}:
                    st.markdown("**공격** · 기본 능력")
                else:
                    st.text(item["label"])
                    st.caption(ABILITY_DESCRIPTIONS[ability_id])
        mandatory = ["night.attack.v1"] if faction == "MAFIA" else []
        options = [ability_id for ability_id in allowed if ability_id not in mandatory]
        key = f"game.create_abilities.{faction}"
        previous = st.session_state.get(key, [])
        previous = [value for value in previous if value in options] if isinstance(previous, list) else []
        # 시민은 4개 능력 중 3개까지, 마피아는 공격을 포함한 전체 3개까지
        # 선택하게 한다. 공격은 별도 checkbox가 아닌 기본 능력이므로, 마피아의
        # 실제 추가 선택 수는 2개이며 화면 문구에도 전체 기준을 명시한다.
        max_abilities = 3
        max_optional = max_abilities - len(mandatory)
        selection_label = (
            "**마피아 진영 능력 선택 · 최대 3개 (공격 포함)**"
            if faction == "MAFIA"
            else "**시민 진영 능력 선택 · 최대 3개**"
        )
        st.markdown(selection_label)
        if mandatory:
            st.caption("공격은 기본 능력으로 포함됩니다.")
        selected = []
        for ability_id in options:
            option_key = f"{key}.{ability_id}"
            if option_key not in st.session_state:
                st.session_state[option_key] = ability_id in previous
            checked = st.checkbox(
                allowed[ability_id]["label"],
                key=option_key,
                disabled=in_flight or (len(selected) >= max_optional and not st.session_state[option_key]),
            )
            if checked:
                selected.append(ability_id)
        # 다음 rerun에서도 현재 선택을 복원하되, 최대 개수 밖의 값은 저장하지 않는다.
        selected = selected[:max_optional]
        st.session_state[key] = selected
        ability_ids = mandatory + selected
        try:
            name = normalize_role_name(name)
        except ValueError as error:
            # 빈 입력은 placeholder가 안내하므로 같은 문구를 오류로 반복하지 않는다.
            if name.strip():
                st.caption(str(error))
            return None, False
        if not 1 <= len(ability_ids) <= max_abilities or len(set(ability_ids)) != len(ability_ids):
            st.caption(
                "공격을 포함해 능력을 최대 3개 선택해 주세요."
                if faction == "MAFIA"
                else "총 4개 능력 중 최대 3개를 선택해 주세요."
            )
            return None, False
        return {"name": name, "faction": faction, "catalog_version": data["catalog_version"],
                "ability_ids": ability_ids}, True
