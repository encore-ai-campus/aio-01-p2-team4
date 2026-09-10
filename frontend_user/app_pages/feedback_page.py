"""일반·게임별 feedback 화면."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import streamlit as st

from frontend_user.components.theme import render_application_header, render_header_back_button
from frontend_user.core.api_client import ApiClient, ApiResponseError, ApiUnavailableError
from frontend_user.core.feedback import ALLOWED_TAGS, build_feedback
from frontend_user.core.scenario_images import scenario_image_path
from frontend_user.core.time_display import display_timestamp

FEEDBACK_PAGE_CSS = """
<style>
:root {
  --feedback-blue: #2468ed;
  --feedback-dark: #071426;
  --feedback-ink: #172033;
  --feedback-muted: #65728b;
  --feedback-border: #d9e2ef;
}
[data-testid="stAppViewContainer"] { color: var(--feedback-ink); background: #f4f7fb; }
[data-testid="stHeader"] { background: transparent; }
[data-testid="stMainBlockContainer"] {
  width: min(100%, 1240px); max-width: 1240px; padding: 0 1.4rem 3rem;
}
.feedback-header {
  display: flex; align-items: center; justify-content: space-between;
  min-height: 4.2rem; margin: 0 -1.4rem 2rem; padding: 0 1.5rem;
  color: #fff; background: var(--feedback-dark); border-bottom: 1px solid #24324c;
}
.feedback-brand { font-size: 1.55rem; font-weight: 850; letter-spacing: -.05em; }
.feedback-status {
  display: inline-flex; align-items: center; gap: .4rem; margin-left: 1rem;
  padding: .42rem .7rem; border: 1px solid #2b3b57; border-radius: .55rem;
  color: #d8e2f3; font-size: .78rem;
}
.feedback-status::before {
  content: ""; width: .45rem; height: .45rem; border-radius: 50%; background: #31c477;
}
.feedback-nav { display: flex; gap: .7rem; color: #d8e2f3; font-size: .82rem; }
.feedback-nav span {
  padding: .55rem .75rem; border: 1px solid #2b3b57; border-radius: .5rem;
}
.feedback-title {
  margin-bottom: .25rem; font-size: clamp(2rem, 4vw, 2.7rem); letter-spacing: -.05em;
}
.feedback-caption { margin-bottom: 1.5rem; color: var(--feedback-muted); }
[class*="st-key-feedback-game-summary"],
[class*="st-key-feedback-form-card"] {
  min-height: 29rem; padding: 1.1rem !important;
  border: 1px solid var(--feedback-border) !important;
  border-radius: .8rem !important; background: #fff !important;
  box-shadow: 0 .5rem 1.5rem rgba(20, 42, 81, .05);
}
.feedback-scene {
  min-height: 10.5rem; display: grid; position: relative; place-items: end center;
  margin: -1.1rem -1.1rem 1rem; padding: 1rem; border-radius: .8rem .8rem 0 0;
  color: #dceaff; background: radial-gradient(circle at 75% 25%, #b9d7ff 0 3%, transparent 4%),
              linear-gradient(155deg, #07162b, #1b4e82);
}
.feedback-scene::after {
  content: "🤖  🕵️  🤖  🤖  🤖  🤖"; font-size: 1.35rem; letter-spacing: .25rem;
}
[class*="st-key-feedback-stars"] [data-testid="stFeedback"] button { transform: scale(1.2); }
[class*="st-key-feedback-form-card"] textarea { min-height: 8rem; }
[class*="st-key-feedback-actions"] [data-testid="stButton"] button {
  min-height: 3rem; font-weight: 750;
}
[class*="st-key-feedback-terminal"] {
  max-width: 44rem; margin: 2rem auto; padding: 1.2rem !important;
  border: 1px solid #9ebcf4 !important; border-radius: .8rem !important;
  background: #fff !important;
}
@media (max-width: 768px) {
  [data-testid="stMainBlockContainer"] { padding: 0 .8rem 2rem; }
  .feedback-header { margin: 0 -.8rem 1.25rem; padding: 0 .9rem; }
  .feedback-nav { display: none; }
  [class*="st-key-feedback-game-summary"],
  [class*="st-key-feedback-form-card"] { min-height: auto; }
}
</style>
"""

TAG_LABELS = {
    "BALANCE": "밸런스",
    "DIALOGUE": "대화",
    "UX": "UX",
}

WINNER_LABELS = {
    "CITIZEN": "시민 진영 승리",
    "MAFIA": "마피아 진영 승리",
}


def render(
    *,
    client: ApiClient,
    feedback_type: str = "GENERAL",
    game_id: str | None = None,
    scenario_title: str | None = None,
    snapshot: dict[str, Any] | None = None,
) -> None:
    """입력을 terminal 전까지 고정하고 game feedback은 결과 요약과 함께 표시한다."""

    # GAME feedback의 소유권·완료 여부·중복은 Backend가 최종 확인한다. 화면에 쓰는
    # snapshot은 직전 결과의 읽기 전용 설명일 뿐 feedback body나 Agent 입력에 섞지 않는다.
    st.markdown(FEEDBACK_PAGE_CSS, unsafe_allow_html=True)
    is_game_feedback = feedback_type == "GAME"
    render_application_header(
        title="AI 마피아",
        action_renderer=lambda: render_header_back_button(
            current_page="game_feedback" if is_game_feedback else "feedback"
        ),
    )
    st.markdown(
        '<div class="feedback-title">게임 피드백</div>'
        if is_game_feedback
        else '<div class="feedback-title">서비스 피드백</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="feedback-caption">여러분의 의견은 더 재미있는 마피아 게임을 '
        "만드는 데 큰 도움이 됩니다.</div>",
        unsafe_allow_html=True,
    )

    pending = _scoped_pending(feedback_type=feedback_type, game_id=game_id)
    _process_pending(client=client, pending=pending)
    pending = _scoped_pending(feedback_type=feedback_type, game_id=game_id)
    if isinstance(pending, dict) and pending.get("status") in {"SUCCEEDED", "ALREADY_SUBMITTED"}:
        _render_terminal(pending=pending, game_feedback=is_game_feedback)
        return

    locked = isinstance(pending, dict) and pending.get("status") in {
        "PENDING_TO_RENDER",
        "IN_FLIGHT",
        "RETRYABLE_UNKNOWN",
    }
    if is_game_feedback:
        left, right = st.columns([1, 2])
        with left:
            _render_game_summary(
                snapshot=snapshot,
                scenario_title=scenario_title,
            )
        with right:
            _render_form(
                feedback_type=feedback_type,
                game_id=game_id,
                pending=pending,
                locked=locked,
            )
    else:
        _, center, _ = st.columns([1, 2.2, 1])
        with center:
            _render_form(
                feedback_type=feedback_type,
                game_id=game_id,
                pending=pending,
                locked=locked,
            )
    st.info(
        "게임별 피드백은 한 번만 제출할 수 있습니다."
        if is_game_feedback
        else "의견은 서비스 개선 목적으로만 사용됩니다."
    )


def _render_game_summary(
    *,
    snapshot: dict[str, Any] | None,
    scenario_title: str | None,
) -> None:
    """직전 완료 snapshot에서 게임을 식별하는 읽기 전용 정보만 표시한다."""

    game_snapshot = snapshot if isinstance(snapshot, dict) else {}
    game = game_snapshot.get("game") if isinstance(game_snapshot.get("game"), dict) else {}
    scenario = (
        game_snapshot.get("scenario") if isinstance(game_snapshot.get("scenario"), dict) else {}
    )
    result = game_snapshot.get("result") if isinstance(game_snapshot.get("result"), dict) else {}
    title = scenario_title or str(scenario.get("title", "완료된 게임"))
    winner = WINNER_LABELS.get(str(result.get("winner")), "게임 결과 확인")
    players = result.get("players") if isinstance(result.get("players"), list) else []
    finished_at = result.get("finished_at")

    with st.container(key="feedback-game-summary", border=True):
        image_source = {**scenario, "title": title}
        image_source.pop("scenario_title", None)
        image_path = scenario_image_path(image_source)
        if image_path is not None:
            st.image(str(image_path), width="stretch")
        else:
            st.markdown('<div class="feedback-scene" aria-hidden="true"></div>', unsafe_allow_html=True)
        st.markdown(f"## {title}")
        st.success(winner)
        st.write(f"🚩 진행 라운드: {game.get('round', '-')}회")
        st.write(f"👥 플레이어 수: {len(players) if players else game.get('player_count', '-')}명")
        if isinstance(finished_at, str):
            st.write(f"▣ 완료 시간: {display_timestamp(finished_at)}")
        st.caption("게임 정보는 읽기 전용이며 피드백 본문에 포함되지 않습니다.")


def _render_form(
    *,
    feedback_type: str,
    game_id: str | None,
    pending: dict[str, Any] | None,
    locked: bool,
) -> None:
    """별점·의견·허용 태그를 입력받고 검증된 body를 다음 렌더에 고정한다."""

    with st.container(key="feedback-form-card", border=True):
        st.markdown(
            "## 이번 게임은 어떠셨나요?" if feedback_type == "GAME" else "## 서비스는 어떠셨나요?"
        )
        with st.container(key="feedback-stars"):
            rating_index = st.feedback(
                "stars",
                key="feedback.rating",
                default=4,
                disabled=locked,
                width="stretch",
            )
        rating = rating_index + 1 if isinstance(rating_index, int) else None
        st.caption(f"{rating}점" if rating else "별점을 선택해 주세요.")
        st.divider()
        comment = st.text_area(
            "의견을 남겨 주세요 (선택)",
            max_chars=1000,
            disabled=locked,
            key="feedback.comment",
            placeholder="자유롭게 의견을 남겨 주세요.",
        )
        st.caption(f"{len(comment)} / 1000")
        tags = st.pills(
            "관련 태그를 선택해 주세요 (선택)",
            ALLOWED_TAGS,
            selection_mode="multi",
            format_func=lambda tag: TAG_LABELS.get(tag, tag),
            disabled=locked,
            key="feedback.tags",
            width="stretch",
        )
        selected_tags = list(tags) if isinstance(tags, list) else []
        st.caption("태그는 최대 5개까지 선택할 수 있습니다.")

        _render_pending_feedback(pending)
        with st.container(key="feedback-actions"):
            submit_col, later_col = st.columns(2)
            if submit_col.button(
                "피드백 제출",
                type="primary",
                key="feedback.submit",
                disabled=locked or rating is None,
                use_container_width=True,
            ):
                _queue_feedback(
                    feedback_type=feedback_type,
                    game_id=game_id,
                    rating=rating,
                    comment=comment,
                    tags=selected_tags,
                )
            if later_col.button(
                "나중에 하기",
                key="feedback.later",
                disabled=locked,
                use_container_width=True,
            ):
                st.session_state["navigation.page"] = "game" if feedback_type == "GAME" else "home"
                st.rerun()


def _queue_feedback(
    *,
    feedback_type: str,
    game_id: str | None,
    rating: int,
    comment: str,
    tags: list[str],
) -> None:
    """검증된 feedback body와 새 Idempotency-Key를 다음 렌더 주기에 고정한다."""

    try:
        body = build_feedback(
            feedback_type=feedback_type,
            rating=rating,
            comment=comment,
            tags=tags,
            game_id=game_id,
        )
    except ValueError as error:
        st.error(str(error))
        return
    st.session_state["feedback.pending"] = {
        "status": "PENDING_TO_RENDER",
        "body": body,
        "idempotency_key": str(uuid4()),
    }
    st.rerun()


def _process_pending(*, client: ApiClient, pending: dict[str, Any] | None) -> None:
    """고정 feedback을 한 번 제출하고 terminal 응답을 session에 보존한다."""

    if not isinstance(pending, dict):
        return
    if pending.get("status") == "PENDING_TO_RENDER":
        st.session_state["feedback.pending"] = {**pending, "status": "IN_FLIGHT"}
        st.rerun()
    if pending.get("status") != "IN_FLIGHT":
        return
    try:
        client.submit_feedback(
            body=pending["body"],
            idempotency_key=pending["idempotency_key"],
        )
        st.session_state["feedback.pending"] = {**pending, "status": "SUCCEEDED"}
    except ApiResponseError as error:
        status = (
            "ALREADY_SUBMITTED"
            if error.status_code == 409
            else "RETRYABLE_UNKNOWN"
            if error.status_code >= 500
            else "REJECTED"
        )
        st.session_state["feedback.pending"] = {**pending, "status": status}
    except (ApiUnavailableError, ValueError):
        st.session_state["feedback.pending"] = {**pending, "status": "RETRYABLE_UNKNOWN"}
    st.rerun()


def _render_pending_feedback(pending: Any) -> None:
    """전송 중·결과 불명·거부 상태에 허용된 후속 동작만 표시한다."""

    if not isinstance(pending, dict):
        return
    status = pending.get("status")
    if status in {"PENDING_TO_RENDER", "IN_FLIGHT"}:
        st.info("피드백을 제출하고 있습니다.")
    elif status == "RETRYABLE_UNKNOWN":
        st.warning("제출 결과를 확인하지 못했습니다.")
        if st.button("같은 요청 다시 확인", key="feedback.retry"):
            st.session_state["feedback.pending"] = {
                **pending,
                "status": "PENDING_TO_RENDER",
            }
            st.rerun()
    elif status == "REJECTED":
        st.error("피드백을 제출할 수 없습니다. 입력 내용을 다시 확인해 주세요.")
        if st.button("입력 수정", key="feedback.edit"):
            st.session_state.pop("feedback.pending", None)
            st.rerun()


def _render_terminal(*, pending: dict[str, Any], game_feedback: bool) -> None:
    """성공 또는 게임별 중복 응답 뒤 입력 폼을 숨기고 완료 안내를 표시한다."""

    with st.container(key="feedback-terminal", border=True):
        if pending.get("status") == "SUCCEEDED":
            st.success("피드백이 제출되었습니다. 의견을 보내주셔서 감사합니다.")
        else:
            st.info("이 게임에는 이미 피드백을 제출했습니다.")
        if st.button("결과 화면으로" if game_feedback else "홈으로", use_container_width=True):
            st.session_state["navigation.page"] = "game" if game_feedback else "home"
            st.rerun()


def _scoped_pending(*, feedback_type: str, game_id: str | None) -> dict[str, Any] | None:
    """다른 종류나 다른 게임의 pending 상태가 현재 form을 잠그지 않게 한다."""

    pending = st.session_state.get("feedback.pending")
    if not isinstance(pending, dict):
        return None
    body = pending.get("body") if isinstance(pending.get("body"), dict) else {}
    same_type = body.get("feedback_type") == feedback_type
    same_game = feedback_type != "GAME" or body.get("game_id") == game_id
    if same_type and same_game:
        return pending
    st.session_state.pop("feedback.pending", None)
    return None
