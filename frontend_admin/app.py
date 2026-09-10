"""관리자 read-only dashboard의 UUID bootstrap과 fail-closed 진입점."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from importlib import reload
from pathlib import Path
from uuid import UUID

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    # Streamlit은 실행 스크립트 디렉터리만 import 경로에 넣을 수 있으므로,
    # 패키지 절대 import가 실행 위치와 무관하게 동작하도록 저장소 루트를 등록한다.
    sys.path.insert(0, str(PROJECT_ROOT))

from frontend_admin.app_pages import dashboard_page as dashboard_page_module

# Streamlit rerun은 이미 import된 모듈을 그대로 사용할 수 있으므로, 화면 파일을
# 수정한 뒤에도 이전 탭이 남지 않도록 entrypoint 실행마다 최신 모듈을 다시 읽는다.
render_dashboard = reload(dashboard_page_module).render
from frontend_admin.components.identity_bridge import (
    load_identity,
)
from frontend_admin.core.api_client import (
    AGENT_JOB_KIND_LABELS,
    AGENT_JOB_STATUS_LABELS,
    AUDIT_EVENT_LABELS,
    DEMO_API_KEY,
    AdminApiClient,
    AdminApiError,
    DemoAdminApiClient,
    is_demo_mode,
)
from frontend_admin.core.auth import (
    ADMIN_ACCESS_SESSION_KEY,
    ADMIN_USER_ID_SESSION_KEY,
    parse_admin_uuid,
)
from frontend_admin.core.models import reject_private_fields


@st.fragment(run_every="30s")
def _render_live_dashboard(client, *, synthetic: bool = False) -> None:
    """운영 분석을 주기적으로 다시 조회해 그래프가 최신 상태를 유지하게 한다.

    인증이 끝난 뒤에도 관리자 화면은 최초 조회 결과를 계속 붙잡지 않고,
    fragment가 실행될 때마다 공개 집계·페르소나·피드백·선택한 로그를 다시
    읽는다. 자동 갱신 중 Backend가 일시적으로 실패하면 오래된 수치를
    최신 수치처럼 남기지 않고 해당 영역에 오류를 표시한다.
    """

    try:
        metrics_response = client.metrics()
        metrics = metrics_response.get("data")
        if not isinstance(metrics, dict):
            raise AdminApiError(503, "INVALID_RESPONSE")
        metrics = reject_private_fields(metrics)
        insights, records = _dashboard_inputs(client, metrics)
    except AdminApiError as error:
        if error.status_code == 403:
            # 주기 갱신 중 권한이 회수되면 최초 진입과 같은 식별자 복구 흐름으로
            # 돌아간다. fragment 안에만 입력을 만들면 bridge가 새 UUID를 받지 못한다.
            st.session_state[ADMIN_ACCESS_SESSION_KEY] = False
            st.rerun(scope="app")
        else:
            st.error("관리자 Backend 연결 또는 응답 오류입니다. BACKEND_API_URL과 서버 상태를 확인해 주세요.")
        return
    except (ValueError, KeyError, TypeError):
        st.error("관리자 응답을 안전하게 표시할 수 없습니다.")
        return

    refreshed_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    render_dashboard(
        metrics,
        insights=insights,
        records=records,
        synthetic=synthetic,
        refreshed_at=refreshed_at,
    )


IDENTITY_UI_CSS = """
<style>
[data-testid="stPopoverButton"] {
    min-height: 2.75rem;
    padding: 0.45rem 0.9rem;
    border: 1px solid #6d4aff !important;
    border-radius: 0.7rem !important;
    color: #4b237a !important;
    background: #f2edff !important;
    font-weight: 800 !important;
    box-shadow: 0 4px 12px rgba(75, 35, 122, 0.14);
}
[data-testid="stPopoverButton"]:hover {
    border-color: #4b237a !important;
    color: #fff !important;
    background: #4b237a !important;
}
[data-testid="stPopoverButton"] p,
[data-testid="stPopoverButton"] span {
    color: inherit !important;
}
[data-testid="stPopoverBody"] {
    color: #c7ced9 !important;
    background: #10131a !important;
}
[data-testid="stPopoverBody"] [data-testid="stMarkdownContainer"] p,
[data-testid="stPopoverBody"] [data-testid="stCaptionContainer"] p,
[data-testid="stPopoverBody"] [data-testid="stWidgetLabel"] p,
[data-testid="stPopoverBody"] label p {
    color: #c7ced9 !important;
    opacity: 1 !important;
}
[data-testid="stPopoverBody"] [data-testid="stCode"] pre {
    color: #202632 !important;
    background: #f5f7fb !important;
}
[data-testid="stPopoverBody"] [data-testid="stTextInput"] input {
    color: #202632 !important;
    -webkit-text-fill-color: #202632 !important;
    background: #fff !important;
}
[data-testid="stPopoverBody"] [data-testid="stButton"] button {
    color: #fff !important;
    background: #5b2aa0 !important;
}
[data-testid="stPopoverBody"] [data-testid="stButton"] button p,
[data-testid="stPopoverBody"] [data-testid="stButton"] button span {
    color: #fff !important;
}
</style>
"""


def main() -> None:
    """실제 관리자 API 또는 명시된 로컬 가상 API로 화면을 시작한다."""

    # 팀 전달 사항: Backend는 X-User-Id가 ADMIN_USER_IDS allowlist에 정확히 있을
    # 때만 200을 반환한다. 빈 allowlist·잘못된 UUID·403에서는 partial data도 주지 않는다.
    st.set_page_config(page_title="관리자", page_icon="🛠️", layout="wide")
    if is_demo_mode():
        # 가상 모드는 외부 API 없이 화면을 확인하기 위한 명시적 개발 옵션이다.
        # 환경변수가 없으면 아래 실제 UUID allowlist 흐름만 실행된다.
        st.warning("개발용 가상 메타데이터 모드입니다. 실제 운영 데이터가 아닙니다.")
        with st.expander("데모 API 연결 설정"):
            st.caption("이 키는 공개 테스트 값입니다. 외부 API나 실제 관리자 인증에는 사용할 수 없습니다.")
            st.code(DEMO_API_KEY, language=None)
            with st.form("admin.demo.connection"):
                demo_key = st.text_input("데모 API 키", value=DEMO_API_KEY)
                connect = st.form_submit_button("연결 확인", type="primary")
            if connect:
                st.session_state["admin.demo.key"] = demo_key
        try:
            client = DemoAdminApiClient(api_key=st.session_state.get("admin.demo.key", DEMO_API_KEY))
        except AdminApiError:
            st.session_state[ADMIN_ACCESS_SESSION_KEY] = False
            st.error("데모 키가 일치하지 않습니다. 연결 설정에서 위의 예시 키를 다시 입력해 주세요.")
            return
        st.session_state[ADMIN_ACCESS_SESSION_KEY] = False
        _render_live_dashboard(client, synthetic=True)
        return

    replacement = parse_admin_uuid(st.session_state.get("admin.identity.write"))
    # bridge를 매 rerun에 같은 key로 유지해야 브라우저 응답과 입력 widget이 사라지지 않는다.
    user_id, identity_error = load_identity(
        scope_version=str(st.session_state.get("admin.identity.scope", 1)),
        replacement=replacement,
    )
    if user_id is not None:
        st.session_state[ADMIN_USER_ID_SESSION_KEY] = str(user_id)
        if replacement is not None:
            st.session_state.pop("admin.identity.write", None)
            st.session_state.pop("admin.identity.input", None)
    st.session_state[ADMIN_ACCESS_SESSION_KEY] = False
    # 로컬 Streamlit 개발 툴바가 표시되는 환경에서도 식별자 expander가
    # 툴바와 겹치지 않도록 앱 콘텐츠 시작 위치에 안정적인 여백을 둔다.
    st.space(40)
    st.markdown(IDENTITY_UI_CSS, unsafe_allow_html=True)
    if user_id is None:
        _render_identity(None)
        messages = {
            "MISSING_UUID": "Backend에 등록된 관리자 UUID를 입력해 주세요.",
            "INVALID_STORED_UUID": "저장된 식별자 형식이 올바르지 않습니다. 관리자 UUID를 다시 입력해 주세요.",
            "STORAGE_BLOCKED": "브라우저 저장소를 사용할 수 없습니다. 저장소 설정을 확인한 뒤 다시 시도해 주세요.",
        }
        if identity_error is None:
            st.info("브라우저의 관리자 식별자를 확인하고 있습니다.")
        else:
            st.warning(messages.get(identity_error, "관리자 식별자를 읽지 못했습니다. 다시 시도해 주세요."))
        if st.button("식별자 다시 확인", key="admin.identity.retry"):
            st.session_state["admin.identity.scope"] = st.session_state.get("admin.identity.scope", 1) + 1
            st.rerun()
        return
    try:
        client = AdminApiClient(user_id=st.session_state[ADMIN_USER_ID_SESSION_KEY])
        metrics_response = client.metrics()
        metrics = metrics_response.get("data")
        if not isinstance(metrics, dict):
            raise AdminApiError(503, "INVALID_RESPONSE")
        metrics = reject_private_fields(metrics)
        insights, records = _dashboard_inputs(client, metrics)
        st.session_state[ADMIN_ACCESS_SESSION_KEY] = True
    except AdminApiError as error:
        st.session_state[ADMIN_ACCESS_SESSION_KEY] = False
        _render_identity(None)
        if error.status_code == 403:
            st.error("관리자 접근이 거부되었습니다. Backend에 등록된 UUID를 입력해 주세요.")
        else:
            st.error("관리자 Backend 연결 또는 응답 오류입니다. BACKEND_API_URL과 서버 상태를 확인해 주세요.")
        st.button("접근 다시 확인", key="admin.access.retry")
        return
    except (ValueError, KeyError, TypeError):
        st.session_state[ADMIN_ACCESS_SESSION_KEY] = False
        _render_identity(None)
        st.error("관리자 응답을 안전하게 표시할 수 없습니다.")
        st.button("접근 다시 확인", key="admin.access.retry")
        return
    _render_identity(user_id)
    _render_live_dashboard(client)


def _render_identity(user_id: UUID | None) -> None:
    """정상 연결 시에는 아무 식별자 UI도 표시하지 않고 오류 때만 입력을 보여 준다."""

    current = parse_admin_uuid(st.session_state.get(ADMIN_USER_ID_SESSION_KEY))
    if user_id is None:
        # 최초 진입이나 권한 오류에서는 입력창을 숨기면 사용자가 다음 행동을
        # 찾기 어려우므로, 필요한 경우에만 안내 카드 형태로 펼쳐 둔다.
        with st.container(border=True):
            st.subheader("관리자 식별자 설정")
            _render_identity_fields(current)
    pending = parse_admin_uuid(st.session_state.get("admin.identity.pending"))
    if pending is not None:
        _confirm_identity(pending)


def _render_identity_fields(current: UUID | None) -> None:
    """현재 UUID와 교체 입력을 한 장소에 모아 식별자 변경 흐름을 유지한다."""

    if current is not None:
        st.caption("현재 브라우저의 관리자 UUID")
        st.code(str(current), language=None)
    st.caption("UUID는 비밀번호가 아니며, 관리자 화면은 loopback 또는 사설망에서만 사용합니다.")
    candidate = st.text_input("관리자 UUID v4", key="admin.identity.input")
    if st.button("입력값 확인", key="admin.identity.apply", type="primary"):
        parsed = parse_admin_uuid(candidate)
        if parsed is None:
            st.error("UUID v4 형식의 식별자를 입력해 주세요.")
        else:
            st.session_state["admin.identity.pending"] = str(parsed)


@st.dialog("관리자 UUID 적용 확인", dismissible=False)
def _confirm_identity(candidate: UUID) -> None:
    """명시적으로 확인한 UUID만 저장 요청으로 넘기며 이전 조회 선택을 비운다."""

    st.code(str(candidate), language=None)
    st.warning("이 식별자는 비밀번호가 아니며, 아는 사람은 같은 관리자 정보를 볼 수 있습니다.")
    st.caption("현재 식별자를 교체하고 Backend에서 권한을 다시 확인합니다. allowlist는 변경하지 않습니다.")
    if st.button("확인하고 적용", key="admin.identity.confirm"):
        st.session_state["admin.identity.write"] = str(candidate)
        st.session_state["admin.identity.scope"] = st.session_state.get("admin.identity.scope", 1) + 1
        st.session_state[ADMIN_ACCESS_SESSION_KEY] = False
        st.session_state.pop("admin.identity.pending", None)
        st.query_params.pop("game_id", None)
        st.rerun()
    if st.button("취소", key="admin.identity.cancel"):
        st.session_state.pop("admin.identity.pending", None)
        st.rerun()



def _dashboard_inputs(client, metrics: dict) -> tuple[dict, dict]:
    """모든 탭의 API 응답을 렌더링 전에 읽어 권한 오류 시 부분 노출을 막는다."""

    def data(response):
        value = response.get("data")
        if not isinstance(value, dict) or not isinstance(value.get("items"), list):
            raise ValueError("INVALID_RESPONSE")
        return reject_private_fields(value)

    personas = data(client.persona_win_rates())["items"]
    speech_period = st.session_state.get("admin.speech.period", "전체 기간")
    if speech_period not in {"전체 기간", "최근 7일", "최근 31일"}:
        speech_period = "전체 기간"
        st.session_state["admin.speech.period"] = speech_period
    speech_from_date = None
    speech_to_date = None
    if speech_period in {"최근 7일", "최근 31일"}:
        days = 7 if speech_period == "최근 7일" else 31
        now = datetime.now(UTC)
        speech_from_date = (now - timedelta(days=days)).isoformat().replace("+00:00", "Z")
        speech_to_date = now.isoformat().replace("+00:00", "Z")
    speech_persona_option = st.session_state.get("admin.speech.persona", "전체")
    if not isinstance(speech_persona_option, str) or not speech_persona_option.strip():
        speech_persona_option = "전체"
        st.session_state["admin.speech.persona"] = speech_persona_option
    speech_persona_id = None
    if speech_persona_option != "전체":
        speech_persona_id = str(speech_persona_option).split(" · ", 1)[0].strip() or None
    speech_round_option = st.session_state.get("admin.speech.round", "전체")
    if speech_round_option not in {"전체", "0", "1", "2", "3", "4", "5"}:
        speech_round_option = "전체"
        st.session_state["admin.speech.round"] = speech_round_option
    speech_round = None if speech_round_option == "전체" else int(speech_round_option)
    speech_game_text = str(st.session_state.get("admin.speech.game", "")).strip()
    speech_game_id = None
    if speech_game_text:
        try:
            speech_game_id = UUID(speech_game_text)
            st.session_state["admin.speech.game.invalid"] = False
        except ValueError:
            # 입력 중인 UUID 때문에 전체 화면을 실패시키지 않고, 화면에서 조건 오류를
            # 안내한다. 잘못된 값은 Backend로 보내지 않아 SQL 경계도 유지한다.
            st.session_state["admin.speech.game.invalid"] = True
    else:
        st.session_state["admin.speech.game.invalid"] = False
    speech_response = client.speech_analytics(
        from_date=speech_from_date,
        to_date=speech_to_date,
        game_id=speech_game_id,
        persona_id=speech_persona_id,
        round_number=speech_round,
    )
    speech_data = speech_response.get("data") if isinstance(speech_response, dict) else None
    if not isinstance(speech_data, dict):
        raise ValueError("INVALID_RESPONSE")
    speech_data = reject_private_fields(speech_data)
    insights = {
        "personas": [{"페르소나": row["persona_name"],
                      "성격": row["personality_summary"],
                      "참여 수": row["participations"], "승리 수": row["wins"],
                      "승률 (%)": round(float(row["win_rate"]) * 100, 1)}
                     for row in personas],
        "daily": [{"날짜": row["date"], "생성 게임": row["games_created"]}
                  for row in metrics.get("daily_games", [])],
        "speech_analytics": speech_data,
        "speech_filters": {
            "period": speech_period,
            "persona": speech_persona_option,
            "round": speech_round_option,
            "game": speech_game_text,
            "game_invalid": bool(st.session_state.get("admin.speech.game.invalid", False)),
        },
    }
    feedback_type = {"전체": None, "일반": "GENERAL", "게임": "GAME"}[
        st.session_state.get("admin.feedback.type", "전체")]
    rating_label = st.session_state.get("admin.feedback.rating", "전체")
    rating = None if rating_label == "전체" else int(rating_label)
    selected_event_label = st.session_state.get("admin.logs.type", "전체")
    if selected_event_label not in AUDIT_EVENT_LABELS:
        st.session_state["admin.logs.type"] = "전체"
        selected_event_label = "전체"
    event_type = AUDIT_EVENT_LABELS[selected_event_label]

    def cursor(name, filters):
        # 식별자 또는 필터가 바뀌면 이전 조건에서 받은 커서를 재사용하지 않는다.
        signature = (str(getattr(client, "user_id", "demo")), *filters)
        if st.session_state.get(name + ".signature") != signature:
            st.session_state[name + ".signature"] = signature
            st.session_state[name + ".cursors"] = [None]
        return st.session_state[name + ".cursors"][-1]

    feedback_cursor = cursor("admin.feedback", (feedback_type, rating))
    logs_cursor = cursor("admin.logs", (event_type,))
    log_source = st.session_state.get("admin.logs.source", "AI Agent 행동")
    if log_source not in {"AI Agent 행동", "관리자 조회 이력"}:
        log_source = "AI Agent 행동"
        st.session_state["admin.logs.source"] = log_source
    job_filters = {}
    for name, labels in (("kind", AGENT_JOB_KIND_LABELS), ("status", AGENT_JOB_STATUS_LABELS)):
        key = f"admin.agent_jobs.{name}"
        label = st.session_state.get(key, "전체")
        if label not in labels:
            label = "전체"
            st.session_state[key] = label
        job_filters[name] = labels[label]
    job_game_text = str(st.session_state.get("admin.agent_jobs.game", "")).strip()
    job_game_id = None
    job_game_invalid = False
    if job_game_text:
        try:
            job_game_id = UUID(job_game_text)
        except ValueError:
            # 잘못된 UUID를 전체 조회로 바꾸면 필터가 적용된 것처럼 오해할 수 있다.
            # 해당 목록만 비우고 입력 오류를 표시하며 Backend에는 요청하지 않는다.
            job_game_invalid = True
    jobs_cursor = cursor("admin.agent_jobs", (
        job_filters["kind"], job_filters["status"],
        str(job_game_id) if job_game_id else job_game_text,
    ))
    records = {
        "feedback": data(client.feedback(feedback_type=feedback_type, rating=rating,
                                         cursor=feedback_cursor)),
        "logs": {"items": [], "next_cursor": None},
        "agent_jobs": {"items": [], "next_cursor": None},
        "agent_jobs_game_invalid": job_game_invalid,
    }
    if log_source == "관리자 조회 이력":
        records["logs"] = data(client.audit_logs(event_type=event_type, cursor=logs_cursor))
    elif not job_game_invalid:
        records["agent_jobs"] = data(client.agent_jobs(
            game_id=job_game_id, job_kind=job_filters["kind"], status=job_filters["status"],
            cursor=jobs_cursor,
        ))
    return insights, records

if __name__ == "__main__":
    main()
