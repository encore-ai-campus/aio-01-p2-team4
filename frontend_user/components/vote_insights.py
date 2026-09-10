"""공개 사용자·AI 대화 요약과 발언 분석을 게임 입력과 분리된 보조 화면으로 표시한다."""

from __future__ import annotations

from inspect import getattr_static
from typing import Any

import streamlit as st

from frontend_user.core.api_client import ApiResponseError

VOTE_PHASES = {"DAY_VOTE", "REVOTE", "FINAL_ACCUSATION"}
DISCUSSION_PHASES = {"DAY_DISCUSSION", "FINAL_DISCUSSION"}
SCOPES = {"current_discussion": "현재 토론", "game": "게임 누적"}
CACHE_KEY = "vote_insights.cache"


def _rows(value: Any) -> list[dict[str, Any]]:
    """불완전한 보조 응답이 기존 게임 화면 렌더링을 중단하지 않게 한다."""

    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _count(value: Any) -> int:
    """완료 수에는 음수·문자열·불리언을 허용하지 않는다."""

    return value if type(value) is int and value >= 0 else 0


def _load(*, client: Any, game_id: str, window_id: str, scope: str,
          refresh: bool = False) -> dict[str, Any] | None:
    """토론은 매 전체 rerun에서 읽고 투표는 고정 cutoff의 완료 응답을 재사용한다."""

    # 같은 식별자가 남더라도 토론의 움직이는 cutoff 응답을 투표 캐시로 쓰지 않는다.
    identity = (str(getattr(client, "user_id", "")), game_id, window_id, scope, refresh)
    cached = st.session_state.get(CACHE_KEY, {})
    if (not refresh and cached.get("identity") == identity
            and cached.get("status") not in {"PENDING", "PARTIAL"}):
        return cached.get("data")
    # 동적 속성 fallback이 있는 구형 fake도 명시적으로 제공한 메서드만 호출한다.
    method = (getattr(client, "get_vote_insights", None)
              if getattr_static(client, "get_vote_insights", None) is not None else None)
    data = None
    try:
        response = method(game_id=game_id, window_id=window_id, scope=scope) if callable(method) else None
        candidate = response.get("data") if isinstance(response, dict) else None
        if (isinstance(candidate, dict)
                and (candidate.get("game_id"), candidate.get("window_id"), candidate.get("scope"))
                == (game_id, window_id, scope)
                and candidate.get("status") in {"PENDING", "PARTIAL", "READY", "UNAVAILABLE"}):
            data = candidate
    except (ApiResponseError, OSError, ValueError, TypeError):
        # 오류 본문은 출력하지 않는다. 보조 API의 장애는 투표 제출이나 sync를 바꾸지 않는다.
        pass
    st.session_state[CACHE_KEY] = {
        "identity": identity, "status": data["status"] if data else "UNAVAILABLE", "data": data,
    }
    return data


def _evidence(rows: Any, names: dict[str, str]) -> None:
    """timeline deep link 대신 공개 event 식별자와 전문을 안전한 텍스트로 제공한다."""

    for evidence in _rows(rows):
        with st.expander("공개 발언 원문"):
            st.text(f"{names.get(str(evidence.get('player_id')), '플레이어')} · "
                    f"{evidence.get('created_at', '')} · 순서 {evidence.get('sequence', '')}")
            st.text(f"event ID: {evidence.get('event_id', '')}")
            st.text(str(evidence.get("message", "")))


def _conversation_summary(value: Any, names: dict[str, str]) -> None:
    """검증된 발언별 요약만 원문과 연결하고 구형 응답의 누락 필드는 빈 보기로 처리한다."""

    summary = value if isinstance(value, dict) else {}
    # 요약은 서버가 발언별 핵심 주장을 묶은 문자열이다. 화면에서 재해석하지 않으며
    # 원문 없는 항목·잘못된 문자열은 표시하지 않고 과도한 응답도 최신 20개로 제한한다.
    items = [row for row in _rows(summary.get("items"))
             if isinstance(row.get("summary"), str) and row["summary"].strip()
             and _rows(row.get("evidence"))][-20:]
    total = _count(summary.get("total"))
    omitted = max(_count(summary.get("omitted")), total - len(items))
    st.text("대화 요약")
    st.caption("발언별 핵심 주장 최대 3개를 모았습니다. 요약 가능한 최신 20개 발언까지 표시합니다.")
    st.text(f"요약된 발언 {total}개 · 표시 {len(items)}개 · 생략 {omitted}개")
    if not items:
        st.caption("아직 표시할 대화 요약이 없습니다.")
    for row in items:
        evidence = _rows(row.get("evidence"))[:1]
        # 원문을 펼치기 전에도 각 발언을 구분하도록 공개 명부의 이름만 보여준다.
        st.text(names.get(str(evidence[0].get("player_id")), "플레이어"))
        st.text(row["summary"])
        _evidence(evidence, names)


def render(*, client: Any, game_id: str, snapshot: dict[str, Any]) -> None:
    """선택·pending·timer에는 쓰지 않고 공개 snapshot의 이름과 선택만 읽는다."""

    game = snapshot.get("game") or {}
    window = snapshot.get("action_window") or {}
    discussion = game.get("phase") in DISCUSSION_PHASES
    if not discussion and game.get("phase") not in VOTE_PHASES:
        st.session_state.pop(CACHE_KEY, None)
        return
    with st.expander("대화 요약과 발언 분석", expanded=False):
        st.caption("공개 사용자·AI 발언을 AI가 요약·분석한 참고 정보이며 사실 판정이 아닙니다.")
        if game.get("status") != "IN_PROGRESS" or window.get("paused") or not window.get("window_id"):
            st.session_state.pop(CACHE_KEY, None)
            st.info("게임을 재개하면 발언 분석을 확인할 수 있어요.")
            return
        # 자유 토론은 발언마다 창이 교체된다. 범위 선택은 같은 토론 구간에 묶어
        # 새 발언 도착 시 유지하고 투표의 기존 창별 선택 상태는 별도로 보존한다.
        scope_key = (f"vote_insights.scope.{game_id}.{game['phase']}.{game.get('round')}"
                     if discussion else f"vote_insights.scope.{game_id}.{window['window_id']}")
        scope = st.radio("분석 범위", list(SCOPES), format_func=SCOPES.get,
                         key=scope_key, horizontal=True)
        data = _load(client=client, game_id=game_id, window_id=window["window_id"], scope=scope,
                     refresh=discussion)
        if not data or data["status"] == "UNAVAILABLE":
            st.info("발언 분석을 사용할 수 없어요. 공개 타임라인에서 발언을 확인해 주세요.")
            return
        coverage = data.get("coverage") if isinstance(data.get("coverage"), dict) else {}
        total = _count(coverage.get("total"))
        st.text(f"{SCOPES[scope]} · 공개 발언 {total}개 · "
                f"임베딩 {_count(coverage.get('embedding_ready'))}/{total} · "
                f"주장 분석 {_count(coverage.get('claims_ready'))}/{total} · "
                f"실패 {_count(coverage.get('failed'))}개")
        if data["status"] in {"PENDING", "PARTIAL"}:
            st.info("분석 중입니다. 부분 결과는 현재 분석된 공개 사용자·AI 발언 기준입니다.")
        elif total == 0:
            st.info("이 범위에는 분석할 공개 발언이 없습니다.")
        names = {str(p.get("player_id")): str(p.get("display_name", "플레이어"))
                 for p in _rows(snapshot.get("players"))}
        _conversation_summary(data.get("conversation_summary"), names)
        # 토론은 요약만 제공한다. 서버가 잘못 카드를 포함해도 투표 선택용 정보는 숨긴다.
        if discussion:
            return
        st.text("지목 순위 · 분석된 공개 발언 기준 (최대 3개)")
        for row in _rows(data.get("suspicion_ranking"))[:3]:
            st.text(f"{_count(row.get('rank'))}위 · {names.get(str(row.get('target_player_id')), '플레이어')} · "
                    f"지목 플레이어 {_count(row.get('accuser_count'))}명 · 발언 {_count(row.get('speech_count'))}개")
            _evidence(row.get("evidence"), names)
        st.text("유사 주장 (최대 3개)")
        for row in _rows(data.get("similar_claims"))[:3]:
            ids = row.get("player_ids") if isinstance(row.get("player_ids"), list) else []
            st.text(" · ".join(names.get(str(player_id), "플레이어") for player_id in ids))
            st.text(str(row.get("claim", "")))
            _evidence(row.get("evidence"), names)
        candidates = _rows(data.get("candidate_evidence"))
        options = list(dict.fromkeys(str(row.get("target_player_id")) for row in candidates
                                     if str(row.get("target_player_id")) in names))
        if not options:
            st.caption("표시할 후보별 근거가 없습니다.")
            return
        selected = st.session_state.get(f"form.vote_target.{game_id}.{window['window_id']}")
        target = st.selectbox(
            "근거를 볼 후보", options, index=options.index(selected) if selected in options else None,
            format_func=names.get, key=f"vote_insights.target.{game_id}.{window['window_id']}.{scope}",
        )
        st.caption("근거 확인은 투표 선택을 바꾸지 않습니다.")
        for row in candidates:
            if row.get("target_player_id") == target:
                st.text(f"선택 후보: {names.get(str(target), '플레이어')}")
                for key, label in (("suspicion", "의심"), ("defense", "옹호"), ("questions", "질문")):
                    st.text(label)
                    _evidence(row.get(key), names)
