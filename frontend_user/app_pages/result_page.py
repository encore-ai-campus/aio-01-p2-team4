"""완료·실패 게임의 결과 화면."""

from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st

from frontend_user.components.theme import render_application_header, render_header_back_button
from frontend_user.core.scenario_images import result_image_path, scenario_image_path
from frontend_user.core.time_display import display_timestamp

RESULT_PAGE_CSS = """
<style>
:root {
  --result-blue: #2468ed;
  --result-dark: #071426;
  --result-ink: #172033;
  --result-muted: #52617a;
  --result-border: #d9e2ef;
  --result-green: #16864d;
}
[data-testid="stAppViewContainer"] { color: var(--result-ink); background: #f4f7fb; }
[data-testid="stHeader"] { background: transparent; }
[data-testid="stMainBlockContainer"] {
  width: min(100%, 1280px); max-width: 1280px; padding: 0 1.4rem 3rem;
}
.result-header {
  display: flex; align-items: center; justify-content: space-between;
  min-height: 4.2rem; margin: 0 -1.4rem 1.25rem; padding: 0 1.5rem;
  color: #fff; background: var(--result-dark); border-bottom: 1px solid #24324c;
}
.result-brand { font-size: 1.55rem; font-weight: 850; letter-spacing: -.05em; }
.result-status {
  display: inline-flex; align-items: center; gap: .4rem; margin-left: 1rem;
  padding: .42rem .7rem; border: 1px solid #2b3b57; border-radius: .55rem;
  color: #d8e2f3; font-size: .78rem;
}
.result-status::before {
  content: ""; width: .45rem; height: .45rem; border-radius: 50%; background: #31c477;
}
.result-settings {
  padding: .55rem .8rem; border: 1px solid #2b3b57; border-radius: .5rem;
  color: #d8e2f3; font-size: .82rem;
}
[class*="st-key-result-hero"] {
  width: 100%; height: 100%; min-height: 100%; display: block; position: relative; overflow: hidden;
  padding: 0 !important; align-content: center; border: 0 !important;
  border-radius: .85rem !important; color: #fff !important; background: #071426 !important;
  box-shadow: 0 1rem 2rem rgba(20,42,81,.14);
}
[class*="st-key-result-hero"] h1,
[class*="st-key-result-hero"] h2,
[class*="st-key-result-hero"] p { position: relative; z-index: 1; color: #fff !important; }
[class*="st-key-result-summary"] {
  height: 100%; min-height: 100%; box-sizing: border-box; padding: 1.1rem !important;
  border: 1px solid var(--result-border) !important;
  border-radius: .85rem !important; background: #fff !important;
  box-shadow: 0 .5rem 1.5rem rgba(20, 42, 81, .05);
}
[class*="st-key-result-player-"] {
  min-height: 8.5rem; padding: .9rem !important; border: 1px solid var(--result-border) !important;
  border-radius: .7rem !important; background: #fff !important;
}
[class*="st-key-result-records"] {
  margin-top: 1rem; padding: .9rem !important; border: 1px solid var(--result-border) !important;
  border-radius: .75rem !important; background: #fff !important;
}
[class*="st-key-result-hero"] img {
  display: block; width: 100%; height: 100%; max-height: none; object-fit: contain;
  position: relative; z-index: 1; border-radius: .85rem; opacity: .96;
}
[class*="st-key-result-hero"] > div,
[class*="st-key-result-hero"] [data-testid="stImage"] { width: 100% !important; height: 100% !important; }
.result-last-vote {
  margin-top: .55rem; color: var(--result-ink); font-size: .92rem; font-weight: 750;
  line-height: 1.35; overflow-wrap: anywhere;
}
[class*="st-key-result-night-"],
[class*="st-key-result-vote-"] {
  margin-bottom: .55rem; padding: .7rem .8rem !important;
  border: 1px solid #c8d4e5 !important; border-radius: .6rem !important;
  color: var(--result-ink) !important; background: #f0f4fa !important;
}
/* 밝은 결과 카드 안의 st.text·metric은 다크 테마의 독립 전경색을 상속하지 않는다.
   승리 배너·상태 배지까지 덮지 않도록 결과 카드의 텍스트 요소에만 적용한다. */
:is(.st-key-result-summary, .st-key-result-records, [class*="st-key-result-player-"])
  :is([data-testid="stText"], [data-testid="stText"] *,
      [data-testid="stMetricLabel"], [data-testid="stMetricValue"],
      [data-testid="stMetricLabel"] *, [data-testid="stMetricValue"] *) {
  color: var(--result-ink) !important;
  -webkit-text-fill-color: var(--result-ink) !important;
  opacity: 1 !important;
}
.st-key-result-records [data-testid="stMarkdownContainer"],
.st-key-result-records [data-testid="stMarkdownContainer"] :is(p, li, strong, div, h4) {
  color: var(--result-ink) !important;
  -webkit-text-fill-color: var(--result-ink) !important;
}
:is(.st-key-result-summary, .st-key-result-records, [class*="st-key-result-player-"])
  [data-testid="stCaptionContainer"],
:is(.st-key-result-summary, .st-key-result-records, [class*="st-key-result-player-"])
  [data-testid="stCaptionContainer"] * {
  color: var(--result-muted) !important;
  -webkit-text-fill-color: var(--result-muted) !important;
  opacity: 1 !important;
}
[class*="st-key-result-actions"] { margin-top: 1rem; }
[class*="st-key-result-actions"] [data-testid="stButton"] button {
  min-height: 3rem; font-weight: 750;
}
@media (max-width: 768px) {
  [data-testid="stMainBlockContainer"] { padding: 0 .8rem 2rem; }
  .result-header { margin: 0 -.8rem 1rem; padding: 0 .9rem; }
  [class*="st-key-result-hero"], [class*="st-key-result-summary"] { height: auto; min-height: auto; }
}
</style>
"""

ROLE_PRESENTATION = {
    "MAFIA": ("마피아", "🥷", "🔴"),
    "DETECTIVE": ("탐정", "🕵️", "🔵"),
    "DOCTOR": ("의사", "🩺", "🟢"),
    "CITIZEN": ("시민", "🧑", "⚪"),
}

WINNER_PRESENTATION = {
    "CITIZEN": ("시민 진영 승리", "모든 마피아를 찾아냈습니다!"),
    "MAFIA": ("마피아 진영 승리", "마피아가 끝까지 정체를 숨겼습니다."),
}

WIN_REASON_LABELS = {
    "ALL_MAFIA_ELIMINATED": "모든 마피아 처형",
    "MAFIA_PARITY": "마피아와 시민 수 동률",
    "FINAL_MAFIA_SELECTED": "최종 지목으로 마피아 발견",
    "FINAL_NON_MAFIA_SELECTED": "최종 지목 실패",
}

PUBLIC_EVENT_FIELDS = {
    "GAME_BEGAN": {"message"},
    "TURN_OPENED": {"player_id", "cycle", "prompt"},
    "PLAYER_SPOKE": {"player_id", "message"},
    "PLAYER_PASSED": {"player_id"},
    "NIGHT_RESOLVED": {"round", "killed_player_id"},
    "VOTE_RESOLVED": {"round", "phase", "counts", "tied", "needs_revote"},
    "PLAYER_EXECUTED": {"player_id", "revealed_role"},
    "FAST_FORWARD_ENABLED": {"enabled"},
    "GAME_SAVED": {"phase", "round"},
    "GAME_RESUMED": {"phase", "round"},
    "GAME_ENDED": {"winner", "win_reason"},
}


def render(snapshot: dict[str, Any]) -> None:
    """COMPLETED는 Backend result만 상세 표시하고 FAILED는 공개 안내로 제한한다."""

    st.session_state.pop("game.special_roles", None)
    # Backend가 확정한 result만 역할·행동·투표 공개의 근거로 사용한다. Front는
    # public event나 생존자 수를 조합해 승패 또는 숨은 역할을 다시 판정하지 않는다.
    game = snapshot.get("game") if isinstance(snapshot.get("game"), dict) else {}
    scenario = snapshot.get("scenario") if isinstance(snapshot.get("scenario"), dict) else {}
    st.markdown(RESULT_PAGE_CSS, unsafe_allow_html=True)
    render_application_header(
        title="게임 종료",
        action_renderer=lambda: render_header_back_button(current_page="game"),
    )

    if game.get("status") != "COMPLETED":
        _render_failed(scenario=scenario)
        return
    result = snapshot.get("result")
    if not isinstance(result, dict):
        st.error("결과 정보를 확인할 수 없어요.")
        st.info("홈에서 게임 상태를 다시 확인해 주세요.")
        _render_actions(show_feedback=False)
        return

    winner_title, winner_caption = _winner_presentation(result.get("winner"))
    hero_col, summary_col = st.columns([1.4, 1])
    with hero_col:
        with st.container(key="result-hero"):
            image_path = result_image_path(result.get("winner")) or scenario_image_path(scenario)
            if image_path is not None:
                # 승리 배너 자체에 결과 문구가 포함되어 있으므로 원본 비율을 유지해
                # 별도 카드 안에 넣지 않고 결과 카드 전체를 채우도록 표시한다.
                st.image(str(image_path), width="stretch")
            else:
                st.markdown(f"# {winner_title}")
                st.markdown(f"### {winner_caption}")
                st.text(str(scenario.get("title", "AI 마피아 게임")))
    with summary_col:
        _render_summary(game=game, result=result)

    _render_players(result=result, me=snapshot.get("me"))
    _render_records(result=result, public_events=snapshot.get("public_events"))
    _render_actions(show_feedback=True)


def _render_summary(*, game: dict[str, Any], result: dict[str, Any]) -> None:
    """Backend 결과의 진행 횟수·생존자·마지막 투표 정보를 요약한다."""

    players = _objects(result.get("players"))
    survivor_count = sum(1 for player in players if player.get("alive"))
    round_count = _round_count(game=game, result=result)
    with st.container(key="result-summary", border=True):
        st.markdown("### 게임 요약")
        round_col, survivor_col, vote_col = st.columns(3)
        round_col.metric("🚩 진행 라운드", round_count)
        survivor_col.metric("👥 생존자", survivor_count)
        vote_col.markdown("🗳️ 마지막 투표")
        vote_col.markdown(
            f'<div class="result-last-vote">{escape(_last_vote_label(result=result))}</div>',
            unsafe_allow_html=True,
        )
        st.divider()
        st.success("이 결과는 서버에서 확인되었습니다.")
        st.caption(f"완료 시간: {_display_timestamp(result.get('finished_at'))}")
        reason = WIN_REASON_LABELS.get(str(result.get("win_reason")), "게임 종료 조건 충족")
        st.caption(f"종료 이유: {reason}")


def _render_players(*, result: dict[str, Any], me: Any = None) -> None:
    """종료 result에 공개된 전체 player 역할과 탈락 상태를 카드로 표시한다."""

    players = _objects(result.get("players"))
    st.markdown("## 전체 역할")
    if isinstance(me, dict):
        my_role = ROLE_PRESENTATION.get(str(me.get("role")))
        if isinstance(me.get("role_name"), str) and me.get("faction") in {"CITIZEN", "MAFIA"}:
            with st.container(key="result-my-role", border=True):
                st.text(f"내 역할 · {me['role_name']} · {'시민 진영' if me['faction'] == 'CITIZEN' else '마피아 진영'}")
        elif my_role:
            role_name, role_icon, _ = my_role
            with st.container(key="result-my-role", border=True):
                st.markdown(
                    f"**내 역할** · {escape(role_icon)} {escape(role_name)}",
                    unsafe_allow_html=True,
                )
    if not players:
        st.info("표시할 최종 플레이어 정보가 없습니다.")
        return
    for row_start in range(0, len(players), 6):
        row = players[row_start : row_start + 6]
        columns = st.columns(len(row))
        for offset, player in enumerate(row):
            index = row_start + offset
            role_name, role_icon, role_marker = ROLE_PRESENTATION.get(
                str(player.get("role")),
                ("확인 중", "❔", "⚪"),
            )
            with columns[offset]:
                with st.container(key=f"result-player-{index}", border=True):
                    st.markdown(f"### {role_icon}")
                    st.markdown(
                        f"<strong>{escape(str(player.get('display_name', '플레이어')))}</strong>",
                        unsafe_allow_html=True,
                    )
                    if isinstance(player.get("role_name"), str) and player.get("faction") in {"CITIZEN", "MAFIA"}:
                        st.text(f"{player['role_name']} · {'시민 진영' if player['faction'] == 'CITIZEN' else '마피아 진영'}")
                    else:
                        st.write(f"{role_marker} {role_name}")
                    status, detail = _player_status(player)
                    if status == "생존":
                        st.success(status)
                    else:
                        st.error(status)
                    if detail:
                        st.caption(detail)


def _render_records(*, result: dict[str, Any], public_events: Any = None) -> None:
    """result의 밤·투표 확정값을 이름으로 변환해 접을 수 있는 기록으로 표시한다."""

    players = _objects(result.get("players"))
    player_names = {
        player["player_id"]: player["display_name"]
        for player in players
        if isinstance(player.get("player_id"), str)
        and isinstance(player.get("display_name"), str) and player["display_name"].strip()
    }
    with st.container(key="result-records", border=True):
        with st.expander("게임 기록 보기", expanded=False):
            night_col, vote_col = st.columns(2)
            with night_col:
                st.markdown("#### 밤별 주요 기록")
                nights = _objects(result.get("nights"))
                if not nights:
                    st.caption("확정된 밤 기록이 없습니다.")
                for index, night in enumerate(nights):
                    with st.container(key=f"result-night-{index}", border=True):
                        _render_night_record(night=night, player_names=player_names)
            with vote_col:
                st.markdown("#### 투표별 주요 기록")
                votes = _objects(result.get("votes"))
                if not votes:
                    st.caption("확정된 투표 기록이 없습니다.")
                for index, vote in enumerate(votes):
                    with st.container(key=f"result-vote-{index}", border=True):
                        _render_vote_record(vote=vote, player_names=player_names)
            _render_public_records(result=result, events=public_events, player_names=player_names)


def _render_public_records(*, result: dict[str, Any], events: Any, player_names: dict[str, str]) -> None:
    """종료 결과에 연결된 공개 사건만 서버 순서대로 표시하고 private·trace는 읽지 않는다."""

    st.markdown("#### 공개 사건·발언")
    identifiers = result.get("public_event_ids")
    allowed = {value for value in identifiers if isinstance(value, str)} if isinstance(identifiers, list) else set()
    seen = set()
    for event in _objects(events):
        identifier = event.get("event_id")
        if not isinstance(identifier, str) or identifier not in allowed or identifier in seen:
            continue
        timestamp = _display_timestamp(event.get("created_at"))
        text = _public_event_text(event, player_names)
        if timestamp == "확인할 수 없음" or text is None:
            continue
        # 발언의 HTML·Markdown을 실행하지 않는다. 기록 순서는 시간 문자열이 아니라
        # Backend가 전달한 배열 순서이며 같은 event ID는 한 번만 표시한다.
        st.markdown(f'<div style="white-space:pre-wrap">{escape(text)}</div>', unsafe_allow_html=True)
        st.caption(timestamp)
        seen.add(identifier)
    if not seen:
        st.caption("표시할 공개 사건·발언 기록이 없습니다.")


def _public_event_text(event: dict[str, Any], player_names: dict[str, str]) -> str | None:
    """PublicEvent의 폐쇄형 data만 문장으로 바꾸며 미지원·개인 필드가 섞이면 거부한다."""

    kind, data = event.get("event_type"), event.get("data")
    if not isinstance(kind, str) or kind not in PUBLIC_EVENT_FIELDS or not isinstance(data, dict):
        return None
    if set(data) != PUBLIC_EVENT_FIELDS[kind]:
        return None
    name = _player_name(data.get("player_id"), player_names)
    if "player_id" in data and not name:
        return None
    if "round" in data and _record_round(data["round"]) == "기록 없음":
        return None
    if kind in {"GAME_BEGAN", "PLAYER_SPOKE"}:
        message = data["message"]
        if not isinstance(message, str) or not 1 <= len(message.strip()) <= 200:
            return None
        return f"{name}: {message}" if kind == "PLAYER_SPOKE" else f"게임 시작: {message}"
    if kind == "TURN_OPENED":
        if type(data["cycle"]) is not int or data["cycle"] not in {1, 2}:
            return None
        prompt = data["prompt"]
        if prompt is not None and (not isinstance(prompt, str) or not 1 <= len(prompt) <= 200):
            return None
        return f"{name}의 발언 차례 · {data['cycle']}번째 순환" + (f" · {prompt}" if prompt else "")
    if kind == "PLAYER_PASSED":
        return f"{name}이 발언을 넘겼습니다."
    if kind == "NIGHT_RESOLVED":
        target = _record_target(data, "killed_player_id", player_names)
        if data["round"] == 0 or target == "기록 확인 불가":
            return None
        return f"밤 {data['round']} 결과 · 사망자: {target}"
    if kind == "VOTE_RESOLVED":
        phase = data["phase"]
        if not isinstance(phase, str) or phase not in {"DAY_VOTE", "REVOTE", "FINAL_ACCUSATION"}:
            return None
        if data["round"] == 0 or type(data["tied"]) is not bool or type(data["needs_revote"]) is not bool:
            return None
        counts = _count_labels(data["counts"], player_names)
        if not counts or len(counts) != len(data["counts"]):
            return None
        outcome = " · 재투표 예정" if data["needs_revote"] else " · 동률" if data["tied"] else ""
        return f"라운드 {data['round']} {_phase_label(phase)} · {', '.join(counts)}{outcome}"
    if kind == "PLAYER_EXECUTED":
        role = data["revealed_role"]
        if not isinstance(role, str) or role not in ROLE_PRESENTATION:
            return None
        return f"{name} 처형 · 공개 역할: {ROLE_PRESENTATION[role][0]}"
    if kind == "FAST_FORWARD_ENABLED":
        return "관전 빠른 진행이 활성화되었습니다." if data["enabled"] is True else None
    if kind in {"GAME_SAVED", "GAME_RESUMED"}:
        if not isinstance(data["phase"], str):
            return None
        action = "저장" if kind == "GAME_SAVED" else "재개"
        return f"게임 {action} · 라운드 {data['round']} · {_phase_label(data['phase'])}"
    if kind == "GAME_ENDED":
        if not isinstance(data["winner"], str) or data["winner"] not in WINNER_PRESENTATION:
            return None
        if not isinstance(data["win_reason"], str) or data["win_reason"] not in WIN_REASON_LABELS:
            return None
        return "게임이 종료되었습니다. 승리 진영과 종료 이유는 위의 최종 결과를 확인해 주세요."
    return None


def _render_night_record(*, night: dict[str, Any], player_names: dict[str, str]) -> None:
    """종료 원장의 선택과 확정 결과를 표시하며 누락값을 무행동으로 추정하지 않는다."""

    st.markdown(f"**🌙 밤 {_record_round(night.get('round'))}**")
    for field, label in (
        ("resolved_attack_target_player_id", "최종 공격 대상"),
        ("protect_player_id", "보호 대상"), ("killed_player_id", "사망자"),
    ):
        st.text(f"{label}: {_record_target(night, field, player_names)}")
    choices = [choice for choice in _objects(night.get("attack_choices"))
               if _player_name(choice.get("actor_player_id"), player_names)
               and _player_name(choice.get("target_player_id"), player_names)
               and type(choice.get("is_auto")) is bool]
    targets = {choice["target_player_id"] for choice in choices}
    actors = {choice["actor_player_id"] for choice in choices}
    # 종료 공개 원장의 두 유효 선택과 확정 대상이 일치할 때만 규칙의 사유를 설명한다.
    if len(choices) == len(actors) == len(targets) == 2 and night.get("resolved_attack_target_player_id") in targets:
        st.info("마피아 투표가 갈려서 두 후보 중 RNG(무작위 선택)로 최종 공격 대상이 결정되었습니다.")
    _render_choices(night.get("attack_choices"), label="마피아 선택", player_names=player_names)
    _render_choices(night.get("investigations"), label="조사", player_names=player_names)


def _render_vote_record(*, vote: dict[str, Any], player_names: dict[str, str]) -> None:
    """개별 투표와 확정 집계를 구분하고 동률·최종 지목 대상을 재판정하지 않는다."""

    phase = _phase_label(str(vote.get("phase", "")))
    st.markdown(f"**☀️ {phase} · 라운드 {_record_round(vote.get('round'))}**")
    st.text(f"탈락자: {_record_target(vote, 'eliminated_player_id', player_names)}")
    counts = _count_labels(vote.get("counts"), player_names)
    if counts:
        for label in counts:
            st.text(label)
    else:
        st.caption("확정된 득표 기록이 없습니다.")
    _render_choices(vote.get("ballots"), label="투표", player_names=player_names)


def _render_choices(value: Any, *, label: str, player_names: dict[str, str]) -> None:
    """종료 공개 선택의 actor·target·boolean만 읽고 내부 추론 필드는 사용하지 않는다."""

    rendered = 0
    for choice in _objects(value):
        actor = _player_name(choice.get("actor_player_id"), player_names)
        target = _player_name(choice.get("target_player_id"), player_names)
        if not actor or not target or type(choice.get("is_auto")) is not bool:
            continue
        outcome = ""
        if label == "조사":
            if type(choice.get("is_mafia")) is not bool:
                continue
            outcome = " · 마피아" if choice["is_mafia"] else " · 마피아가 아닙니다"
        selection = "자동 선택" if choice["is_auto"] else "직접 선택"
        st.text(f"{label}: {actor} → {target}{outcome} · {selection}")
        rendered += 1
    if not rendered:
        st.caption(f"개별 {label} 기록이 없습니다.")


def _count_labels(value: Any, player_names: dict[str, str]) -> list[str]:
    """후보별 확정 득표만 표시하며 bool·음수·알 수 없는 참가자는 건너뛴다."""

    labels = []
    for count in _objects(value):
        name = _player_name(count.get("target_player_id"), player_names)
        votes = count.get("vote_count")
        if name and type(votes) is int and 0 <= votes <= len(player_names):
            labels.append(f"{name}: {votes}표")
    return labels


def _record_round(value: Any) -> str:
    """표시용 round도 계약 범위의 정수만 허용해 잘못된 원문을 출력하지 않는다."""

    return str(value) if type(value) is int and 0 <= value <= 5 else "기록 없음"


def _record_target(record: dict[str, Any], field: str, player_names: dict[str, str]) -> str:
    """명시적 null과 누락·알 수 없는 식별자를 구별해 없는 결과를 만들지 않는다."""

    if field not in record:
        return "기록 없음"
    if record[field] is None:
        return "없음"
    return _player_name(record[field], player_names) or "기록 확인 불가"


def _render_actions(*, show_feedback: bool) -> None:
    """완료 게임에는 피드백, 그 외에는 종료 후 이동 CTA만 제공한다."""

    with st.container(key="result-actions"):
        if show_feedback:
            feedback_column, home_column = st.columns(2)
            if feedback_column.button(
                "피드백 남기기",
                key="result.feedback",
                type="primary",
                use_container_width=True,
            ):
                # 게임이 완료되기 전 조회한 홈 목록을 그대로 사용하면 새 완료 게임이
                # 보이지 않는다. 피드백 화면을 거쳐 홈으로 가는 경로도 동일하게 갱신한다.
                _invalidate_home_games()
                st.session_state["navigation.page"] = "game_feedback"
                st.rerun()
        else:
            new_game_column, home_column = st.columns(2)
            if new_game_column.button(
                "새 게임",
                key="result.new_game",
                use_container_width=True,
            ):
                st.session_state["navigation.page"] = "create"
                st.session_state.pop("game.game_id", None)
                st.session_state.pop("game.latest_snapshot", None)
                # 이전 생성 성공 receipt가 새 설정을 건너뛰지 않게 제거한다. 결과 불명
                # 요청의 key와 body는 중복 생성 방지를 위해 F2 재시도 흐름에 그대로 넘긴다.
                previous = st.session_state.get("game.create_pending")
                if isinstance(previous, dict) and previous.get("status") == "SUCCEEDED":
                    st.session_state.pop("game.create_pending", None)
                st.rerun()
        if home_column.button(
            "홈으로",
            key="result.home",
            use_container_width=True,
        ):
            _invalidate_home_games()
            st.session_state["navigation.page"] = "home"
            st.session_state.pop("game.game_id", None)
            st.rerun()
        st.caption("게임 기록과 결과는 홈의 완료 게임 목록에서 다시 확인할 수 있습니다.")


def _invalidate_home_games() -> None:
    """게임 완료 직후 홈에 오래된 목록이 남지 않도록 목록 캐시만 비운다."""

    for key in ("home.games", "home.games_error", "home.games_loaded_at", "home.games_loading"):
        st.session_state.pop(key, None)


def _render_failed(*, scenario: dict[str, Any]) -> None:
    """FAILED 상태에서는 전체 역할이나 미확정 결과를 공개하지 않는다."""

    st.error("게임을 완료하지 못했어요.")
    st.text(str(scenario.get("title", "게임 결과")))
    st.info("마지막으로 확인된 공개 상태만 표시합니다. 게임 결과를 복구할 수 없습니다.")
    _render_actions(show_feedback=False)


def _winner_presentation(value: Any) -> tuple[str, str]:
    """Backend winner enum을 결과 화면의 고정 제목과 설명으로 변환한다."""

    return WINNER_PRESENTATION.get(str(value), ("게임 종료", "서버에서 최종 결과를 확정했습니다."))


def _player_status(player: dict[str, Any]) -> tuple[str, str | None]:
    """결과에 포함된 alive·eliminated field만 사용해 최종 상태를 표시한다."""

    if player.get("alive"):
        return "생존", None
    phase = str(player.get("eliminated_phase", ""))
    status = "처형됨" if phase in {"DAY_VOTE", "REVOTE", "FINAL_ACCUSATION"} else "사망"
    round_number = player.get("eliminated_round")
    detail = f"{_phase_label(phase)} · 라운드 {round_number}" if round_number is not None else None
    return status, detail


def _round_count(*, game: dict[str, Any], result: dict[str, Any]) -> int:
    """결과 배열에 기록된 최대 round를 표시용 진행 횟수로 사용한다."""

    rounds = [game.get("round", 0)]
    rounds.extend(item.get("round", 0) for item in _objects(result.get("nights")))
    rounds.extend(item.get("round", 0) for item in _objects(result.get("votes")))
    return max((value for value in rounds if isinstance(value, int)), default=0)


def _last_vote_label(*, result: dict[str, Any]) -> str:
    """마지막 투표 자체의 기록만 표시하며 게임 종료 시점이나 원인으로 해석하지 않는다."""

    votes = _objects(result.get("votes"))
    if votes:
        vote = votes[-1]
        return f"라운드 {_record_round(vote.get('round'))}"
    return "기록 없음"


def _phase_label(phase: str) -> str:
    """결과에 허용된 투표·탈락 phase enum을 짧은 한국어로 변환한다."""

    return {
        "NIGHT_ACTION": "밤 행동",
        "DAY_VOTE": "낮 투표",
        "REVOTE": "재투표",
        "FINAL_ACCUSATION": "최종 지목",
    }.get(phase, "게임 진행")


def _player_name(player_id: Any, player_names: dict[str, str]) -> str | None:
    """result player 식별자가 있을 때만 공개 이름으로 변환한다."""

    if not isinstance(player_id, str):
        return None
    return player_names.get(player_id)


def _objects(value: Any) -> list[dict[str, Any]]:
    """결과 배열에서 object 항목만 원래 순서대로 보존한다."""

    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _display_timestamp(value: Any) -> str:
    """결과 화면에서 사용하는 공통 시각 표시 함수의 호환용 진입점이다."""

    return display_timestamp(value)
