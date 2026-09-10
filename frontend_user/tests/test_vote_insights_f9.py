"""합성 공개 발언으로 실시간 요약 조회와 게임 입력·타이머의 분리 경계를 검증한다."""

import json
from copy import deepcopy
from unittest.mock import patch
from urllib.error import URLError

import pytest
from streamlit.testing.v1 import AppTest

from frontend_user.components import vote_insights
from frontend_user.core.api_client import ApiClient, ApiUnavailableError

GAME = "00000000-0000-4000-8000-000000000201"
WINDOW = "00000000-0000-4000-8000-000000000202"
PLAYER = "00000000-0000-4000-8000-000000000203"
USER = "00000000-0000-4000-8000-000000000204"


def payload(status="READY"):
    """HTML처럼 보이는 공개 원문도 텍스트로만 표시되는 합성 응답을 만든다."""

    evidence = {"event_id": "synthetic-event", "player_id": PLAYER,
                "message": "<script>alert('원문')</script>",
                "created_at": "2026-09-07T00:00:00Z", "sequence": 3}
    return {"data": {"game_id": GAME, "window_id": WINDOW, "scope": "current_discussion",
                     "status": status, "cutoff_sequence": 4, "analysis_version": "v1",
                     "revision": "r1", "generated_at": "2026-09-07T00:00:01Z",
                     "coverage": {"total": 2, "embedding_ready": 2, "claims_ready": 1, "failed": 1},
                     "conversation_summary": {
                         "items": [{"summary": "<b>핵심 주장</b> · 두 번째 주장 · 세 번째 주장",
                                    "evidence": [evidence]}], "total": 1, "omitted": 0},
                     "similar_claims": [{"player_ids": [PLAYER], "target_player_id": PLAYER,
                                         "claim": f"주장 {i}", "evidence": [evidence]} for i in range(5)],
                     "suspicion_ranking": [{"target_player_id": PLAYER, "rank": i + 1,
                                            "accuser_count": 1, "speech_count": 2,
                                            "evidence": [evidence]} for i in range(5)],
                     "candidate_evidence": [{"target_player_id": PLAYER, "suspicion": [evidence],
                                             "defense": [], "questions": []}]}}


def snapshot(phase="DAY_VOTE"):
    return {"game": {"game_id": GAME, "phase": phase, "status": "IN_PROGRESS"},
            "action_window": {"window_id": WINDOW,
                              "kind": "SPEECH" if phase in {"DAY_DISCUSSION", "FINAL_DISCUSSION"}
                              else "VOTE"},
            "players": [{"player_id": PLAYER, "display_name": "합성 AI"}]}


class FakeClient:
    """scope를 반영하며 응답 교체·오류 주입·호출 횟수를 관찰하는 로컬 fake다."""

    user_id = USER

    def __init__(self, response=None, error=None):
        self.response = response if response is not None else payload()
        self.error = error
        self.calls = []

    def get_vote_insights(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        response = deepcopy(self.response)
        response["data"]["scope"] = kwargs["scope"]
        return response


def app_body(client, current):
    import streamlit as st
    from frontend_user.components import vote_insights

    current = st.session_state.setdefault("test.snapshot", current)
    st.session_state.setdefault("form.vote_target." + current["game"]["game_id"] + "."
                                + current["action_window"]["window_id"],
                                "00000000-0000-4000-8000-000000000203")
    st.session_state.setdefault("game.command_pending", {"status": "IN_FLIGHT"})
    st.session_state.setdefault("game.action_clock", {"remaining_ms": 25000})
    st.session_state.setdefault("form.message." + current["game"]["game_id"], "작성 중인 발언")
    vote_insights.render(client=client, game_id=current["game"]["game_id"], snapshot=current)


@pytest.mark.parametrize("status,expected", [("READY", 1), ("UNAVAILABLE", 1), ("PENDING", 2), ("PARTIAL", 2)])
def test_only_processing_responses_refresh_on_existing_rerun(status, expected):
    client = FakeClient(payload(status))
    app = AppTest.from_function(app_body, args=(client, snapshot())).run().run()
    assert not app.exception
    assert len(client.calls) == expected
    assert app.session_state["game.command_pending"] == {"status": "IN_FLIGHT"}
    assert app.session_state["game.action_clock"] == {"remaining_ms": 25000}
    assert app.session_state[f"form.vote_target.{GAME}.{WINDOW}"] == PLAYER


@pytest.mark.parametrize("phase", ["DAY_VOTE", "REVOTE", "FINAL_ACCUSATION"])
def test_plain_text_evidence_names_and_three_summary_limit(phase):
    app = AppTest.from_function(app_body, args=(FakeClient(), snapshot(phase))).run()
    assert not app.exception
    texts = [entry.value for entry in app.text]
    assert "주장 2" in texts and "주장 3" not in texts
    assert any("합성 AI" in value for value in texts)
    assert any("event ID: synthetic-event" == value for value in texts)
    assert "<script>alert('원문')</script>" in texts
    assert any("실패 1개" in value for value in texts)
    assert any("사실 판정이 아닙니다" in entry.value for entry in app.caption)
    assert "<b>핵심 주장</b> · 두 번째 주장 · 세 번째 주장" in texts
    assert any("공개 발언 2개" in value for value in texts)
    assert any("지목 플레이어 1명" in value for value in texts)
    assert app.expander[0].label == "대화 요약과 발언 분석"
    assert not app.markdown


@pytest.mark.parametrize("phase", ["DAY_VOTE", "DAY_DISCUSSION", "FINAL_DISCUSSION"])
def test_scope_change_does_not_reuse_other_scope_or_change_vote(phase):
    client = FakeClient()
    app = AppTest.from_function(app_body, args=(client, snapshot(phase))).run()
    app.radio[0].set_value("game").run()
    assert not app.exception
    assert [call["scope"] for call in client.calls] == ["current_discussion", "game"]
    assert any("게임 누적 · 공개 발언" in entry.value for entry in app.text)
    assert app.session_state[f"form.vote_target.{GAME}.{WINDOW}"] == PLAYER
    assert app.session_state[f"form.message.{GAME}"] == "작성 중인 발언"


@pytest.mark.parametrize("phase", ["DAY_DISCUSSION", "FINAL_DISCUSSION"])
def test_discussion_scope_survives_speech_window_change(phase):
    """새 공개 발언의 창으로 갱신해도 선택한 범위로 최신 요약을 다시 요청해야 한다."""

    client = FakeClient()
    current = snapshot(phase)
    current["game"]["round"] = 2
    app = AppTest.from_function(app_body, args=(client, current)).run()
    app.radio[0].set_value("game").run()
    next_window = "00000000-0000-4000-8000-000000000206"
    app.session_state["test.snapshot"]["action_window"]["window_id"] = next_window
    client.response["data"]["window_id"] = next_window
    app.run()
    assert not app.exception
    assert app.radio[0].value == "game"
    assert client.calls[-1] == {"game_id": GAME, "window_id": next_window, "scope": "game"}
    assert any("게임 누적 · 공개 발언" in entry.value for entry in app.text)
    assert app.session_state[f"form.message.{GAME}"] == "작성 중인 발언"
    assert app.session_state["game.command_pending"] == {"status": "IN_FLIGHT"}
    assert app.session_state["game.action_clock"] == {"remaining_ms": 25000}


@pytest.mark.parametrize("phase", ["DAY_DISCUSSION", "DAY_VOTE"])
def test_each_summary_shows_speaker_before_text_with_unknown_speaker_fallback(phase):
    """화자는 원문을 펼치지 않아도 보이며 공개 이름과 요약에 마크업을 적용하지 않는다."""

    response = payload()
    original = response["data"]["conversation_summary"]["items"][0]
    response["data"]["conversation_summary"] = {
        "items": [original, {"summary": "알 수 없는 화자의 핵심 주장", "evidence": [
            {**original["evidence"][0], "player_id": "unknown-public-player", "event_id": "unknown-event"}]}],
        "total": 2, "omitted": 0,
    }
    current = snapshot(phase)
    current["players"][0]["display_name"] = "<b>공개 화자</b>"
    app = AppTest.from_function(app_body, args=(FakeClient(response), current)).run()
    assert not app.exception
    texts = [entry.value for entry in app.text]
    assert texts[texts.index(original["summary"]) - 1] == "<b>공개 화자</b>"
    assert texts[texts.index("알 수 없는 화자의 핵심 주장") - 1] == "플레이어"
    assert "event ID: synthetic-event" in texts
    assert "event ID: unknown-event" in texts
    assert "<script>alert('원문')</script>" in texts
    assert not app.markdown


@pytest.mark.parametrize("field,value", [("window_id", "old-window"), ("game_id", "other-game")])
def test_stale_response_is_discarded(field, value):
    response = payload()
    response["data"][field] = value
    app = AppTest.from_function(app_body, args=(FakeClient(response), snapshot())).run()
    assert not app.exception
    assert not app.text
    assert "사용할 수 없어요" in app.info[0].value


def test_stale_scope_is_discarded(monkeypatch):
    monkeypatch.setattr(vote_insights.st, "session_state", {})
    client = FakeClient()
    with patch.object(client, "get_vote_insights", return_value=payload()):
        assert vote_insights._load(client=client, game_id=GAME, window_id=WINDOW, scope="game") is None


@pytest.mark.parametrize("client", [object(), FakeClient(error=ApiUnavailableError(status_code=503, code="SYNTHETIC")),
                                     FakeClient(error=ValueError("synthetic"))])
@pytest.mark.parametrize("phase", ["DAY_VOTE", "DAY_DISCUSSION", "FINAL_DISCUSSION"])
def test_missing_optional_method_and_failure_leave_game_state_intact(client, phase):
    app = AppTest.from_function(app_body, args=(client, snapshot(phase))).run().run()
    assert not app.exception
    assert "사용할 수 없어요" in app.info[0].value
    assert app.session_state["game.command_pending"] == {"status": "IN_FLIGHT"}


def test_saved_resume_and_new_window_clear_completed_cache():
    client = FakeClient()
    app = AppTest.from_function(app_body, args=(client, snapshot())).run()
    app.session_state["test.snapshot"]["game"]["status"] = "SAVED"
    app.run()
    assert len(client.calls) == 1
    app.session_state["test.snapshot"]["game"]["status"] = "IN_PROGRESS"
    app.run()
    assert len(client.calls) == 2
    app.session_state["test.snapshot"]["action_window"]["window_id"] = "new-window"
    app.run()
    assert len(client.calls) == 3
    assert not app.text


def test_empty_and_partial_are_distinct():
    response = payload()
    response["data"]["coverage"] = {"total": 0}
    response["data"]["similar_claims"] = []
    response["data"]["suspicion_ranking"] = []
    app = AppTest.from_function(app_body, args=(FakeClient(response), snapshot())).run()
    assert "발언이 없습니다" in app.info[0].value
    partial = AppTest.from_function(app_body, args=(FakeClient(payload("PARTIAL")), snapshot())).run()
    assert "부분 결과" in partial.info[0].value


def test_api_uses_envelope_encoded_scope_and_short_timeout():
    captured = []

    def transport(request, timeout):
        captured.append((request, timeout))
        return 200, json.dumps(payload()).encode()

    client = ApiClient(user_id=USER, transport=transport)
    assert client.get_vote_insights(game_id=GAME, window_id=WINDOW) == payload()
    request, timeout = captured[0]
    assert request.full_url.endswith(f"/games/{GAME}/vote-insights?window_id={WINDOW}&scope=current_discussion")
    assert request.method == "GET" and request.data is None
    assert request.get_header("X-user-id") == USER
    assert timeout == 0.75
    with pytest.raises(ValueError):
        client.get_vote_insights(game_id=GAME, window_id=WINDOW, scope="other&injected=1")
    with pytest.raises(ValueError):
        client.get_vote_insights(game_id=GAME, window_id="invalid")
    assert len(captured) == 1


def test_api_timeout_isolated_as_safe_error():
    def transport(request, timeout):
        raise URLError("synthetic outage")

    client = ApiClient(user_id=USER, transport=transport)
    with pytest.raises(ApiUnavailableError):
        client.get_vote_insights(game_id=GAME, window_id=WINDOW)


def test_legacy_dynamic_fake_does_not_invent_optional_api(monkeypatch):
    from unittest.mock import Mock

    monkeypatch.setattr(vote_insights.st, "session_state", {})
    client = Mock()
    assert vote_insights._load(client=client, game_id=GAME, window_id=WINDOW, scope="game") is None
    assert client.mock_calls == []


@pytest.mark.parametrize("phase", ["ROLE_REVEAL", "NIGHT_ACTION", "DAWN", "COMPLETED"])
def test_unrelated_phase_never_queries(phase):
    client = FakeClient()
    app = AppTest.from_function(app_body, args=(client, snapshot(phase))).run()
    assert not app.exception
    assert client.calls == []
    assert not app.expander


def test_malformed_optional_response_does_not_break_game():
    response = payload()
    response["data"].update(coverage=[], similar_claims=[None], suspicion_ranking="invalid",
                            candidate_evidence=[None])
    app = AppTest.from_function(app_body, args=(FakeClient(response), snapshot())).run()
    assert not app.exception
    assert app.session_state["game.command_pending"] == {"status": "IN_FLIGHT"}


def test_evidence_candidate_control_does_not_submit_or_change_vote():
    other = "00000000-0000-4000-8000-000000000205"
    current = snapshot()
    current["players"].append({"player_id": other, "display_name": "다른 AI"})
    response = payload()
    response["data"]["candidate_evidence"].append({"target_player_id": other, "suspicion": [],
                                                  "defense": [], "questions": []})
    client = FakeClient(response)
    app = AppTest.from_function(app_body, args=(client, current)).run()
    app.selectbox[0].set_value(other).run()
    assert not app.exception
    assert "선택 후보: 다른 AI" in [entry.value for entry in app.text]
    assert app.session_state[f"form.vote_target.{GAME}.{WINDOW}"] == PLAYER
    assert len(client.calls) == 1


@pytest.mark.parametrize("phase", ["DAY_DISCUSSION", "FINAL_DISCUSSION"])
@pytest.mark.parametrize("status", ["READY", "PENDING", "PARTIAL", "UNAVAILABLE"])
def test_discussion_always_refreshes_without_vote_cards_or_game_state_changes(phase, status):
    client = FakeClient(payload(status))
    current = snapshot(phase)
    original = deepcopy(current)
    app = AppTest.from_function(app_body, args=(client, current)).run().run()
    assert not app.exception
    assert len(client.calls) == 2
    assert not app.selectbox
    assert not any("지목 순위" in entry.value or "유사 주장" in entry.value for entry in app.text)
    assert app.session_state[f"form.message.{GAME}"] == "작성 중인 발언"
    assert app.session_state[f"form.vote_target.{GAME}.{WINDOW}"] == PLAYER
    assert app.session_state["game.command_pending"] == {"status": "IN_FLIGHT"}
    assert app.session_state["game.action_clock"] == {"remaining_ms": 25000}
    assert app.session_state["test.snapshot"] == original


@pytest.mark.parametrize("error", [ApiUnavailableError(status_code=503, code="SYNTHETIC"),
                                  ValueError("synthetic")])
def test_discussion_retries_failed_read_and_displays_new_ready_summary(error):
    client = FakeClient(error=error)
    app = AppTest.from_function(app_body, args=(client, snapshot("DAY_DISCUSSION"))).run()
    assert "사용할 수 없어요" in app.info[0].value
    client.error = None
    app.run()
    assert not app.exception
    assert len(client.calls) == 2
    assert "<b>핵심 주장</b> · 두 번째 주장 · 세 번째 주장" in [entry.value for entry in app.text]
    client.response["data"]["conversation_summary"]["items"][0]["summary"] = "새 공개 발언의 주장"
    app.run()
    assert len(client.calls) == 3
    assert "새 공개 발언의 주장" in [entry.value for entry in app.text]


@pytest.mark.parametrize("paused", [False, True])
@pytest.mark.parametrize("phase", ["DAY_DISCUSSION", "FINAL_DISCUSSION", "DAY_VOTE"])
def test_saved_or_paused_skips_queries_then_resume_refreshes(phase, paused):
    client = FakeClient()
    current = snapshot(phase)
    app = AppTest.from_function(app_body, args=(client, current)).run()
    current = app.session_state["test.snapshot"]
    current["action_window"]["paused"] = paused
    current["game"]["status"] = "IN_PROGRESS" if paused else "SAVED"
    app.run().run()
    assert len(client.calls) == 1
    current["action_window"]["paused"] = False
    current["game"]["status"] = "IN_PROGRESS"
    app.run()
    assert not app.exception
    assert len(client.calls) == 2


def test_discussion_allows_expired_speech_window_and_spectator():
    client = FakeClient()
    current = snapshot("DAY_DISCUSSION")
    current["action_window"].update(deadline_at="2026-09-01T00:00:00Z", remaining_ms=0)
    current["me"] = {"player_id": PLAYER, "alive": False}
    current["legal_actions"] = []
    app = AppTest.from_function(app_body, args=(client, current)).run()
    assert not app.exception
    assert len(client.calls) == 1
    assert "<b>핵심 주장</b> · 두 번째 주장 · 세 번째 주장" in [entry.value for entry in app.text]


def test_summary_shows_latest_twenty_public_speeches_and_omitted_count():
    response = payload("PARTIAL")
    source = response["data"]["conversation_summary"]["items"][0]["evidence"][0]
    other = "00000000-0000-4000-8000-000000000205"
    response["data"]["conversation_summary"] = {
        "items": [{"summary": f"요약 {index}", "evidence": [
            {**source, "event_id": f"speech-{index}", "sequence": index,
             "player_id": PLAYER if index % 2 else other}]} for index in range(3, 23)],
        "total": 23, "omitted": 3,
    }
    response["data"]["coverage"] = {"total": 25, "claims_ready": 23, "embedding_ready": 0}
    current = snapshot("DAY_DISCUSSION")
    current["players"].append({"player_id": other, "display_name": "<i>합성 사용자</i>"})
    app = AppTest.from_function(app_body, args=(FakeClient(response), current)).run()
    assert not app.exception
    texts = [entry.value for entry in app.text]
    assert [value for value in texts if value.startswith("요약 ")] == [f"요약 {i}" for i in range(3, 23)]
    assert any("생략 3개" in value and "23개" in value for value in texts)
    assert any("최신 20" in entry.value for entry in app.caption)
    assert any("<i>합성 사용자</i>" in value for value in texts)
    assert any("합성 AI" in value for value in texts)
    assert "event ID: speech-22" in texts
    assert "<script>alert('원문')</script>" in texts
    assert not app.markdown
    assert "부분 결과" in app.info[0].value


@pytest.mark.parametrize("phase", ["DAY_DISCUSSION", "DAY_VOTE"])
@pytest.mark.parametrize("summary", [None, [], {"items": [None, {"summary": []}, {"summary": "  "}],
                                            "total": True, "omitted": -1}])
def test_missing_or_malformed_summary_keeps_existing_game_usable(phase, summary):
    response = payload()
    response["data"].pop("conversation_summary")
    if summary is not None:
        response["data"]["conversation_summary"] = summary
    app = AppTest.from_function(app_body, args=(FakeClient(response), snapshot(phase))).run()
    assert not app.exception
    assert app.session_state[f"form.message.{GAME}"] == "작성 중인 발언"
    assert bool(app.selectbox) == (phase == "DAY_VOTE")


def test_action_countdown_fragment_does_not_query_insights(monkeypatch):
    """시계 callback을 반복해도 입력·보조 조회가 다시 실행되지 않는지 확인한다."""

    from frontend_user.components import action_panel

    callbacks = []

    def fragment(**kwargs):
        def decorate(callback):
            callbacks.append(callback)
            return callback
        return decorate

    monkeypatch.setattr(action_panel.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(action_panel.st, "session_state", {})
    monkeypatch.setattr(action_panel.st, "fragment", fragment)
    monkeypatch.setattr(action_panel, "_process_pending", lambda **kwargs: None)
    monkeypatch.setattr(action_panel, "_countdown_remaining_ms", lambda **kwargs: 25000)
    monkeypatch.setattr(action_panel, "_timer_is_running", lambda snapshot: True)
    monkeypatch.setattr(action_panel, "_render_action_status", lambda **kwargs: None)
    monkeypatch.setattr(action_panel, "_mount_action_attention", lambda **kwargs: None)
    with patch.object(vote_insights, "render") as read, patch.object(action_panel, "_render_actions") as inputs:
        current = snapshot("DAY_DISCUSSION")
        action_panel.render_status_bar(game_id=GAME, snapshot=current)
        for _ in range(3):
            callbacks[0](game_id=GAME, snapshot=current, running=True)
        read.assert_not_called()
        inputs.assert_not_called()
