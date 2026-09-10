"""UUID bridge의 비동기 경계·복구 저장·사용자 scope 분리를 외부 API 없이 검증한다."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from frontend_user import app
from frontend_user.app_pages import home_page, settings_page
from frontend_user.components import action_panel, identity_bridge
from frontend_user.core.session import (
    IDENTITY_PERSISTENCE_SESSION_KEY,
    IDENTITY_SCOPE_SESSION_KEY,
    IDENTITY_WARNING_SESSION_KEY,
    IDENTITY_WRITE_SESSION_KEY,
    USER_ID_SESSION_KEY,
    get_identity,
    request_identity_write,
    set_identity,
)

USER = UUID("00000000-0000-4000-8000-000000000101")
REPLACEMENT = UUID("00000000-0000-4000-8000-000000000102")
GAME_ID = "00000000-0000-4000-8000-000000000201"


def _response(**updates):
    """성공 응답의 특정 필드만 바꿔 실패·지연 응답 경계를 구성한다."""

    return {
        "schema_version": 1,
        "component_instance_id": "identity-main",
        "scope_version": "1",
        "user_id": str(USER),
        "persistence": "LOCAL",
        "error_code": None,
        **updates,
    }


def _component(monkeypatch, identity):
    """실제 브라우저·Backend 없이 component가 반환하는 state만 주입한다."""

    component = Mock(return_value=SimpleNamespace(identity=identity))
    monkeypatch.setattr(identity_bridge, "IDENTITY_COMPONENT", component)
    return component


def test_initial_none_waits_without_creating_session_uuid(monkeypatch):
    """첫 비동기 응답을 저장소 오류로 오해하거나 반복 생성하지 않는지 확인한다."""

    component = _component(monkeypatch, None)
    generate = Mock(side_effect=AssertionError("대기 중 UUID 생성 금지"))
    monkeypatch.setattr(identity_bridge, "new_user_id", generate)
    for _ in range(2):
        assert identity_bridge.load_identity() == (None, None, None)
    assert component.call_count == 2
    generate.assert_not_called()


@pytest.mark.parametrize("updates", [
    {"schema_version": 2},
    {"schema_version": True},
    {"component_instance_id": "another-component"},
    {"user_id": "not-a-uuid"},
    {"user_id": "00000000-0000-1000-8000-000000000101"},
    {"persistence": "SESSION_ONLY"},
    {"persistence": "UNKNOWN"},
    {"error_code": "STORAGE_BLOCKED"},
    {"error_code": {}},
    {"error_code": []},
])
def test_malformed_response_never_grants_a_session_fallback(monkeypatch, updates):
    """검증 실패를 저장소 차단으로 바꿔 API 접근을 허용하지 않는지 확인한다."""

    _component(monkeypatch, _response(**updates))
    assert identity_bridge.load_identity() == (None, None, "INVALID_BRIDGE_RESPONSE")


def test_component_exception_is_distinct_from_storage_failure(monkeypatch):
    """component 실행 오류는 저장소 차단의 증거가 아니므로 식별자를 만들지 않는다."""

    component = _component(monkeypatch, None)
    component.side_effect = RuntimeError("synthetic component failure")
    assert identity_bridge.load_identity() == (None, None, "BRIDGE_UNAVAILABLE")


def test_stale_scope_and_wrong_replacement_ack_cannot_change_identity(monkeypatch):
    """연속 교체 중 늦은 응답과 UUID가 다른 저장 응답을 채택하지 않는다."""

    component = _component(monkeypatch, _response())
    assert identity_bridge.load_identity(scope_version="2", replacement=REPLACEMENT) == (
        None, None, None,
    )
    component.return_value.identity = _response(scope_version="2")
    assert identity_bridge.load_identity(scope_version="2", replacement=REPLACEMENT) == (
        None, None, "INVALID_BRIDGE_RESPONSE",
    )
    component.return_value.identity = _response(scope_version="2", user_id=str(REPLACEMENT))
    assert identity_bridge.load_identity(scope_version="2", replacement=REPLACEMENT) == (
        REPLACEMENT, "LOCAL", None,
    )


def test_explicit_storage_failure_preserves_current_or_recovered_uuid(monkeypatch):
    """저장소 차단 시 UUID 생성은 최초 한 번이며 복구 입력값이 최우선이다."""

    _component(monkeypatch, _response(
        user_id=None, persistence="SESSION_ONLY", error_code="STORAGE_BLOCKED",
    ))
    generate = Mock(return_value=USER)
    monkeypatch.setattr(identity_bridge, "new_user_id", generate)
    assert identity_bridge.load_identity() == (USER, "SESSION_ONLY", "STORAGE_BLOCKED")
    assert identity_bridge.load_identity(current_user_id=USER)[0] == USER
    assert identity_bridge.load_identity(current_user_id=USER, replacement=REPLACEMENT) == (
        REPLACEMENT, "SESSION_ONLY", "STORAGE_BLOCKED",
    )
    generate.assert_called_once()


def test_scope_reset_clears_home_widgets_and_private_state_only_on_change():
    """UUID가 실제 바뀔 때 목록·disabled 표시·private cache를 함께 제거한다."""

    state = {
        USER_ID_SESSION_KEY: str(USER),
        "home.games": [{"game_id": "synthetic"}],
        "home.games_error": "synthetic",
        "home.games_loaded_at": 1,
        "home.user_id": str(USER),
        "game.private": "synthetic",
        "navigation.page": "game",
        "form.target": "synthetic",
        "feedback.pending": "synthetic",
        "theme.preference": "dark",
    }
    set_identity(user_id=USER, persistence="LOCAL", session_state=state)
    assert state["home.games"]
    request_identity_write(user_id=REPLACEMENT, session_state=state)
    first_scope = state[IDENTITY_SCOPE_SESSION_KEY]
    assert get_identity(state) == USER
    assert state["game.private"] == "synthetic"
    request_identity_write(user_id=REPLACEMENT, session_state=state)
    assert state[IDENTITY_SCOPE_SESSION_KEY] != first_scope
    set_identity(user_id=REPLACEMENT, persistence="LOCAL", session_state=state)
    assert get_identity(state) == REPLACEMENT
    assert state["theme.preference"] == "dark"
    assert not any(key.startswith(("home.", "game.", "navigation.", "form.", "feedback.")) for key in state)
    state["home.games"] = []
    set_identity(user_id=REPLACEMENT, persistence="LOCAL", session_state=state)
    assert "home.games" in state


def test_session_mirror_rejects_non_v4_and_tracks_storage_warning():
    """잘못된 session UUID를 사용하지 않고 저장 복구가 확인되면 경고를 해제한다."""

    state = {USER_ID_SESSION_KEY: "00000000-0000-1000-8000-000000000101"}
    assert get_identity(state) is None
    with pytest.raises(ValueError):
        set_identity(user_id=UUID(int=1), persistence="LOCAL", session_state=state)
    set_identity(user_id=USER, persistence="SESSION_ONLY", session_state=state)
    assert state[IDENTITY_WARNING_SESSION_KEY] is True
    set_identity(user_id=USER, persistence="LOCAL", session_state=state)
    assert state[IDENTITY_WARNING_SESSION_KEY] is False


class _Rerun(Exception):
    """Streamlit rerun 이후 기존 Python 프레임이 계속 진행되지 않게 하는 테스트 경계."""


def _app_ui(monkeypatch, state):
    """dispatcher의 화면 렌더만 대체해 identity 앞뒤 API 생성 경계를 관찰한다."""

    ui = Mock(session_state=state)
    ui.rerun.side_effect = _Rerun
    monkeypatch.setattr(app, "st", ui)
    monkeypatch.setattr(app, "render_app_theme", Mock())
    monkeypatch.setattr(app, "render_home", Mock())
    monkeypatch.setattr(app, "load_games", Mock())
    monkeypatch.setattr(app, "should_load_games", lambda _state: False)
    client = Mock()
    monkeypatch.setattr(app, "ApiClient", client)
    return ui, client


def test_dispatcher_waits_and_keeps_bridge_mounted_on_every_rerun(monkeypatch):
    """identity가 준비되기 전 API client를 만들지 않고 준비 후에도 bridge를 유지한다."""

    state = {}
    _, client = _app_ui(monkeypatch, state)
    component = _component(monkeypatch, None)
    app.main()
    client.assert_not_called()
    assert USER_ID_SESSION_KEY not in state
    assert IDENTITY_WARNING_SESSION_KEY not in state
    component.return_value.identity = _response()
    app.main()
    app.main()
    assert component.call_count == 3
    assert {call.kwargs["key"] for call in component.call_args_list} == {"identity-bridge"}
    assert all(call.kwargs["user_id"] == USER for call in client.call_args_list)


def test_dispatcher_blocks_old_scope_until_write_ack_and_then_reloads_home(monkeypatch):
    """교체 저장 대기에는 옛 UUID API를 막고 승인된 UUID로 홈을 다시 조회한다."""

    state = {USER_ID_SESSION_KEY: str(USER), "home.games": [], "home.user_id": str(USER)}
    request_identity_write(user_id=REPLACEMENT, session_state=state)
    scope = state[IDENTITY_SCOPE_SESSION_KEY]
    ui, client = _app_ui(monkeypatch, state)
    component = _component(monkeypatch, _response())
    app.main()
    client.assert_not_called()
    assert state["home.user_id"] == str(USER)
    component.return_value.identity = _response(scope_version=scope, user_id=str(REPLACEMENT))
    monkeypatch.setattr(app, "should_load_games", lambda current: "home.games" not in current)
    with pytest.raises(_Rerun):
        app.main()
    client.assert_called_once_with(user_id=REPLACEMENT)
    assert get_identity(state) == REPLACEMENT
    assert IDENTITY_WRITE_SESSION_KEY not in state
    assert "home.user_id" not in state
    assert "home.games" not in state
    assert state["home.games_loading"] is True
    assert state["navigation.page"] == "home"
    assert state[IDENTITY_PERSISTENCE_SESSION_KEY] == "LOCAL"
    ui.warning.assert_not_called()


def test_settings_confirmation_queues_write_without_claiming_local_success(monkeypatch):
    """확인 버튼은 저장 요청만 예약하며 이미 생성한 입력 widget을 같은 실행에서 지우지 않는다."""

    state = {USER_ID_SESSION_KEY: str(USER), "identity.pending_replacement": str(REPLACEMENT)}
    ui = Mock(session_state=state)
    context = Mock()
    context.__enter__ = Mock(return_value=context)
    context.__exit__ = Mock(return_value=False)
    ui.expander.return_value = context
    ui.button.side_effect = lambda _label, *, key: key == "identity.confirm_replace"
    ui.rerun.side_effect = _Rerun
    monkeypatch.setattr(settings_page, "st", ui)
    with pytest.raises(_Rerun):
        settings_page.render()
    assert get_identity(state) == USER
    assert state[IDENTITY_WRITE_SESSION_KEY] == {"user_id": str(REPLACEMENT)}
    assert IDENTITY_PERSISTENCE_SESSION_KEY not in state


def test_streamlit_home_updates_readonly_uuid_after_scope_replacement():
    """UUID 교체 후 읽기 전용 홈 식별자가 이전 사용자 값을 유지하지 않는지 확인한다."""

    from streamlit.testing.v1 import AppTest

    tested = AppTest.from_string(f'''
import streamlit as st
from uuid import UUID
from frontend_user.app_pages.home_page import render
from frontend_user.core.session import set_identity
set_identity(
    user_id=UUID(st.session_state.get("synthetic.user_id", "{USER}")),
    persistence="LOCAL",
    session_state=st.session_state,
)
render(None)
''').run()
    assert not tested.exception
    assert tested.text_input(key="home.user_id").value == str(USER)
    assert tested.text_input(key="home.user_id").disabled
    tested.session_state["synthetic.user_id"] = str(REPLACEMENT)
    tested.run()
    assert not tested.exception
    assert tested.text_input(key="home.user_id").value == str(REPLACEMENT)
    assert tested.text_input(key="home.user_id").disabled


def _run_main_with_identity(tested, identity):
    """AppTest가 생략하는 v2 widget payload를 실제 브라우저 요청처럼 함께 전달한다."""

    # AppTest의 UnknownElement는 custom component state를 자동 직렬화하지 않는다.
    # session_state에 한 번 대입하면 다음 클릭에서 None으로 돌아가므로, 매 요청에
    # 실제 component ID와 JSON을 넣어 Python 등록·callback·rerun 경계를 그대로 검증한다.
    widget_states = tested._tree.get_widget_states()
    component_id = tested.get("bidi_component")[0].proto.id
    widget_states.widgets.add(
        id=component_id, json_value=json.dumps({"identity": identity}),
    )
    tested._run(widget_state=widget_states)
    assert not tested.exception


def _main_with_mock_transport(monkeypatch, *, items=None, snapshots=None):
    """실제 main을 실행하되 HTTP는 합성 목록과 명시한 snapshot 조회만 허용한다."""

    from streamlit.components.v2.component_manager import BidiComponentManager
    from streamlit.components.v2.component_registry import BidiComponentDefinition
    from streamlit.testing.v1 import AppTest

    requests = []

    def transport(request, timeout):
        """지정한 GET만 허용해 카드 클릭이 mutation이나 외부 API를 호출하지 않게 한다."""

        assert request.get_method() == "GET"
        requests.append(request)
        if request.full_url.endswith("/api/v1/games?limit=20"):
            data = {"items": items if items is not None else [], "next_cursor": None}
        else:
            game_id = request.full_url.rsplit("/", 1)[-1]
            assert request.full_url.endswith(f"/api/v1/games/{game_id}")
            assert snapshots is not None and game_id in snapshots
            data = snapshots[game_id]
        return 200, json.dumps({"data": data}).encode()

    monkeypatch.setattr("frontend_user.core.api_client._send", transport)
    tested = AppTest.from_file(Path(__file__).parents[1] / "app.py")
    # pytest 수집 때는 Streamlit runtime이 없어 component 등록이 임시 registry로 간다.
    # Python 모듈은 다시 import되지 않으므로 AppTest registry에 동일 정적 자산을 등록한다.
    tested._bidi_component_manager = BidiComponentManager()
    tested._bidi_component_manager.register(BidiComponentDefinition(
        name="ai_mafia_identity", html=identity_bridge.IDENTITY_HTML, js=identity_bridge.IDENTITY_JS,
    ))
    # 게임 카드가 역할 공개 화면까지 연결되면 공통 하단 시계도 주의 안내를 등록한다.
    # 실제 main 경로를 유지하므로 이 component 역시 테스트 runtime에 정적 자산을 제공한다.
    tested._bidi_component_manager.register(BidiComponentDefinition(
        name="ai_mafia_action_attention",
        html=(action_panel.ASSET_DIR / "index.html").read_text(encoding="utf-8"),
        js=(action_panel.ASSET_DIR / "index.js").read_text(encoding="utf-8"),
    ))
    tested.run()
    assert not tested.exception
    assert not requests
    _run_main_with_identity(tested, _response())
    return tested, requests


def _assert_home_player_ready(tested) -> None:
    """실제 UUID bootstrap만으로 게임 진입이 열리며 별도 닉네임 준비가 없음을 확인한다."""

    assert get_identity(tested.session_state.filtered_state) == USER
    assert not tested.button(key="home.new_game").disabled


@pytest.mark.parametrize("cache_expired", [False, True])
@pytest.mark.parametrize("button, page, destination", [
    ("home.new_game", "create", "game.create_submit"),
    ("home.feedback", "feedback", "feedback.submit"),
])
def test_actual_main_keeps_home_navigation_after_identity_rerun(
    monkeypatch, cache_expired, button, page, destination,
):
    """같은 bridge 응답과 TTL 만료가 겹쳐도 홈 이동 클릭을 한 번에 처리한다."""

    tested, requests = _main_with_mock_transport(monkeypatch)
    component_id = tested.get("bidi_component")[0].proto.id
    _run_main_with_identity(tested, _response())
    _assert_home_player_ready(tested)
    if cache_expired:
        tested.session_state["home.games_loaded_at"] = 0
    tested.button(key=button).click()
    _run_main_with_identity(tested, _response())
    assert tested.session_state["navigation.page"] == page
    assert tested.button(key=destination)
    assert tested.get("bidi_component")[0].proto.id == component_id
    assert [request.headers["X-user-id"] for request in requests] == [str(USER)]


@pytest.mark.parametrize("cache_expired", [False, True])
@pytest.mark.parametrize("status", ["IN_PROGRESS", "SAVED", "COMPLETED", "FAILED"])
def test_actual_main_keeps_every_cached_card_click(monkeypatch, cache_expired, status):
    """목록이 갱신으로 사라질 상황에서도 표시된 카드의 첫 클릭을 snapshot 조회로 연결한다."""

    items = [{"game_id": GAME_ID, "status": status, "scenario_title": "합성 사건"}]
    snapshot = {
        "game": {
            "game_id": GAME_ID, "status": status, "state_version": 1,
            "phase": "ENDED" if status in {"COMPLETED", "FAILED"} else "ROLE_REVEAL",
        },
        "scenario": {"title": "합성 사건"}, "players": [], "legal_actions": [],
        "me": {"role": "CITIZEN"},
        "result": {"winner": "CITIZEN", "players": [], "nights": [], "votes": []},
    }
    tested, requests = _main_with_mock_transport(
        monkeypatch, items=items, snapshots={GAME_ID: snapshot},
    )
    component_id = tested.get("bidi_component")[0].proto.id
    _assert_home_player_ready(tested)
    items.clear()
    if cache_expired:
        tested.session_state["home.games_loaded_at"] = 0
    tested.button(key=f"home.card.{GAME_ID}").click()
    _run_main_with_identity(tested, _response())

    assert tested.session_state["navigation.page"] == "game"
    assert tested.session_state["game.game_id"] == GAME_ID
    assert tested.session_state["game.latest_snapshot"] == snapshot
    assert "home.games" not in tested.session_state
    assert tested.get("bidi_component")[0].proto.id == component_id
    assert [request.full_url.rsplit("/games", 1)[-1] for request in requests] == [
        "?limit=20", f"/{GAME_ID}",
    ]
    assert all(request.headers["X-user-id"] == str(USER) for request in requests)


def test_actual_main_refresh_renders_cached_cards_before_one_rerun(monkeypatch):
    """TTL 갱신은 기존 카드 입력을 먼저 읽고 한 번의 조회·후속 rerun으로 새 목록을 표시한다."""

    import streamlit as st

    items = [{"game_id": GAME_ID, "status": "IN_PROGRESS", "scenario_title": "변경 전 사건"}]
    tested, requests = _main_with_mock_transport(monkeypatch, items=items)
    _assert_home_player_ready(tested)
    items[0] = {**items[0], "status": "SAVED", "scenario_title": "저장 후 사건"}
    tested.session_state["home.games_loaded_at"] = 0
    pending = {"status": "RETRYABLE_UNKNOWN", "player_count": 6, "idempotency_key": GAME_ID}
    tested.session_state["game.create_pending"] = pending
    render = home_page.render
    rendered = []

    def record_render(client):
        """실제 홈 renderer를 유지해 갱신 전후 카드와 loading 경계의 순서를 관찰한다."""

        rendered.append((st.session_state["home.games"][0]["scenario_title"],
                         st.session_state.get("home.games_loading", False)))
        render(client)

    monkeypatch.setattr(home_page, "render", record_render)
    rerun = Mock(wraps=st.rerun)
    monkeypatch.setattr(st, "rerun", rerun)
    _run_main_with_identity(tested, _response())

    assert rendered == [("변경 전 사건", False), ("저장 후 사건", False)]
    rerun.assert_called_once_with()
    assert len(requests) == 2
    assert tested.button(key=f"home.card.{GAME_ID}").label == "불러오기  ›"
    assert tested.session_state["game.create_pending"] == pending
    _run_main_with_identity(tested, _response())
    assert len(requests) == 2


def test_actual_main_manual_refresh_failure_waits_for_explicit_retry(monkeypatch):
    """수동 갱신 실패는 UUID를 유지하며 자동 반복 없이 재시도 클릭으로 최신 카드를 표시한다."""

    items = [{"game_id": GAME_ID, "status": "IN_PROGRESS", "scenario_title": "변경 전 사건"}]
    tested, requests = _main_with_mock_transport(monkeypatch, items=items)
    _assert_home_player_ready(tested)
    failure = Mock(return_value=(503, b'{"error":{"code":"DEPENDENCY_UNAVAILABLE"}}'))
    with monkeypatch.context() as failing:
        failing.setattr("frontend_user.core.api_client._send", failure)
        tested.button(key="home.refresh").click()
        _run_main_with_identity(tested, _response())
        assert tested.session_state["home.games_error"] == "DEPENDENCY_UNAVAILABLE"
        assert "home.games" not in tested.session_state
        _run_main_with_identity(tested, _response())
        failure.assert_called_once()

    items[0] = {**items[0], "status": "SAVED", "scenario_title": "저장 후 사건"}
    tested.button(key="home.retry").click()
    _run_main_with_identity(tested, _response())
    assert "home.games_error" not in tested.session_state
    assert tested.session_state["home.games"] == items
    assert tested.button(key=f"home.card.{GAME_ID}").label == "불러오기  ›"
    assert tested.text_input(key="home.user_id").value == str(USER)
    assert tested.text_input(key="home.user_id").disabled
    assert len(requests) == 2


def test_actual_main_refreshes_expired_home_without_losing_identity_controls(monkeypatch):
    """목록 갱신 후에도 현재 UUID 표시와 복구 입력을 사용할 수 있는지 확인한다."""

    tested, requests = _main_with_mock_transport(monkeypatch)
    tested.session_state["home.games_loaded_at"] = 0
    _run_main_with_identity(tested, _response())
    assert len(requests) == 2
    assert tested.session_state["home.games_loading"] is False
    assert tested.text_input(key="home.user_id").value == str(USER)
    assert tested.text_input(key="home.user_id").disabled
    assert tested.button(key="identity.replace_button")


@pytest.mark.parametrize("cache_expired", [False, True])
def test_actual_main_confirmation_waits_for_ack_then_replaces_uuid(monkeypatch, cache_expired):
    """최종 확인 클릭을 보존하고 새 scope 응답 뒤에만 UUID 표시와 API header를 바꾼다."""

    tested, requests = _main_with_mock_transport(monkeypatch)
    tested.text_input(key="identity.replacement_input").set_value(str(REPLACEMENT))
    tested.button(key="identity.replace_button").click()
    _run_main_with_identity(tested, _response())
    assert tested.session_state["identity.pending_replacement"] == str(REPLACEMENT)
    if cache_expired:
        tested.session_state["home.games_loaded_at"] = 0
    tested.button(key="identity.confirm_replace").click()
    _run_main_with_identity(tested, _response())
    scope = tested.session_state[IDENTITY_SCOPE_SESSION_KEY]
    assert scope != "1"
    assert tested.session_state[IDENTITY_WRITE_SESSION_KEY] == {"user_id": str(REPLACEMENT)}
    assert get_identity(tested.session_state.filtered_state) == USER
    _run_main_with_identity(tested, _response())
    assert len(requests) == 1
    assert not tested.button
    _run_main_with_identity(tested, _response(scope_version=scope, user_id=str(REPLACEMENT)))
    assert get_identity(tested.session_state.filtered_state) == REPLACEMENT
    assert IDENTITY_WRITE_SESSION_KEY not in tested.session_state
    assert tested.text_input(key="home.user_id").value == str(REPLACEMENT)
    assert tested.text_input(key="home.user_id").disabled
    assert tested.text_input(key="identity.replacement_input").value == ""
    assert [request.headers["X-user-id"] for request in requests] == [str(USER), str(REPLACEMENT)]


def test_browser_identity_refresh_restore_and_storage_failure_lifecycle():
    """실제 bridge JS를 synthetic localStorage로 실행해 refresh·중복 render·차단을 검증한다."""

    node = shutil.which("node")
    if node is None:
        pytest.skip("브라우저 bridge JS 검증에는 Node.js가 필요합니다.")
    source = (Path(__file__).parents[1] / "components/browser_components/identity/index.js").read_text()
    script = r"""
import assert from 'node:assert/strict';
const {default: render} = await import('data:text/javascript;base64,' + Buffer.from(SOURCE).toString('base64'));
const A = '00000000-0000-4000-8000-000000000101';
const B = '00000000-0000-4000-8000-000000000102';
let stored = null;
let readBlocked = false;
let writeBlocked = false;
let writes = 0;
globalThis.window = {localStorage: {
  getItem: () => { if (readBlocked) throw Error('synthetic blocked read'); return stored; },
  setItem: (_key, value) => {
    writes += 1;
    if (writeBlocked) throw Error('synthetic blocked write');
    stored = value;
  },
}};
const props = {storage_key: 'synthetic-key', schema_version: 1, component_instance_id: 'identity-main', scope_version: '1'};
const root = {};
const outputs = [];
function run(data = {}, parentElement = root) {
  render({data: {...props, ...data}, parentElement, setStateValue: (_key, value) => outputs.push(value)});
  return outputs.at(-1);
}
const first = run();
assert.equal(first.persistence, 'LOCAL');
assert.equal(first.user_id, stored);
run();
assert.equal(outputs.length, 1);
assert.equal(writes, 1);
assert.equal(run({}, {}).user_id, first.user_id);
const restored = run({scope_version: '2', replacement: B});
assert.equal(restored.user_id, B);
assert.equal(stored, B);
const count = outputs.length;
run({scope_version: '2', replacement: B});
assert.equal(outputs.length, count);
assert.equal(run({}, {}).user_id, B);

// 저장소 읽기 차단과 쓰기만 차단된 경우 모두 같은 UUID로 재실행되어야 한다.
readBlocked = true;
const blocked = run({current_user_id: B});
assert.equal(blocked.error_code, 'STORAGE_BLOCKED');
assert.equal(blocked.persistence, 'SESSION_ONLY');
assert.equal(run({current_user_id: B}).user_id, B);
readBlocked = false;
stored = A;
writeBlocked = true;
assert.equal(run({scope_version: '3', replacement: B}).user_id, B);
assert.equal(stored, A);
assert.equal(run({scope_version: '3', current_user_id: B, session_only: true}).user_id, B);
assert.equal(run({current_user_id: B, session_only: true}, {}).user_id, B);
writeBlocked = false;
assert.equal(run({scope_version: '3', current_user_id: B, session_only: true}).persistence, 'LOCAL');
assert.equal(stored, B);

// 최초 저장 쓰기 실패 뒤 mirror가 아직 오지 않아도 임시 UUID를 반복 생성하지 않는다.
stored = null;
writeBlocked = true;
const firstBlockedRoot = {};
const temporary = run({}, firstBlockedRoot).user_id;
assert.equal(run({}, firstBlockedRoot).user_id, temporary);
writeBlocked = false;
stored = 'broken-value';
const damagedRoot = {};
assert.equal(run({}, damagedRoot).error_code, 'INVALID_STORED_UUID');
assert.equal(stored, 'broken-value');
const reset = run({scope_version: '4', reset_stored: true}, damagedRoot).user_id;
assert.equal(run({scope_version: '4', reset_stored: true}, damagedRoot).user_id, reset);
assert.equal(stored, reset);
console.log('identity browser lifecycle passed');
""".replace("SOURCE", json.dumps(source))
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "identity browser lifecycle passed" in result.stdout
