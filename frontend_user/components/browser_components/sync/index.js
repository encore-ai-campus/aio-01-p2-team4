const instances = new WeakMap();

export default function ({ data, parentElement, setStateValue }) {
  const scope = JSON.stringify([data.backend_url, data.game_id, data.user_id,
    data.component_instance_id, data.scope_version]);
  let state = instances.get(parentElement);
  if (state && state.scope !== scope) state.stop();
  if (!state || state.stopped) {
    state = createConnection(data, scope, setStateValue, parentElement);
    instances.set(parentElement, state);
    state.start();
  } else {
    // rerun에서 받은 cursor만 서버에 재전송한다. 브라우저가 수신했다는 이유만으로
    // cursor를 전진시키면 Python의 schema 검증 실패 뒤 batch를 잃을 수 있다.
    state.data = data;
    state.publish = setStateValue;
    const sequence = Number.isSafeInteger(data.last_sequence) ? data.last_sequence : null;
    if (sequence !== null && sequence > state.renderedSequence) {
      state.renderedSequence = sequence;
      state.scrollTimelineToLatest();
    }
  }
  clearTimeout(state.cleanupTimer);
  return () => {
    // 같은 DOM의 데이터 갱신은 기존 transport를 재사용하고 실제 unmount·scope
    // 교체만 정리한다. Streamlit의 effect cleanup 직후 재실행도 한 연결로 유지한다.
    state.cleanupTimer = setTimeout(() => state.stop(), 0);
  };
}

function createConnection(data, scope, publish, parentElement) {
  const policy = data.policy;
  const state = {data, scope, publish, stopped: false, live: false, status: "CONNECTING",
    sseFailures: 0, pollFailures: 0, lastEnvelope: null, lastTick: 0,
    renderedSequence: Number.isSafeInteger(data.last_sequence) ? data.last_sequence : 0};
  // 공개 event가 추가된 뒤 Streamlit rerun으로 생성된 timeline container를 찾는다.
  // 입력 focus는 이동하지 않아 키보드 사용자의 발언 작성 흐름을 방해하지 않는다.
  state.scrollTimelineToLatest = () => {
    const documentRoot = parentElement.ownerDocument;
    const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
    let attemptsRemaining = 6;
    const scrollWhenReady = () => {
      if (state.stopped) return;
      const timeline = documentRoot.querySelector(
        '[class*="st-key-game-timeline-scroll"], [class*="st-key-spectator-timeline-scroll"]'
      );
      if (!timeline && attemptsRemaining-- > 0) {
        state.scrollTimer = setTimeout(scrollWhenReady, 50);
        return;
      }
      if (timeline) {
        timeline.scrollTo({top: timeline.scrollHeight, behavior: reducedMotion ? "auto" : "smooth"});
      }
    };
    requestAnimationFrame(scrollWhenReady);
  };
  const hidden = () => document.visibilityState === "hidden";
  const interval = () => hidden() ? policy.background_poll_ms : policy.foreground_poll_ms;
  const backoff = (base, failures) => Math.round(Math.min(policy.max_backoff_ms,
    base * 2 ** Math.min(Math.max(0, failures - 1), 10)) *
    (1 + (Math.random() * 2 - 1) * policy.jitter_ratio));
  const tickInterval = () => !state.live && state.pollFailures
    ? backoff(interval(), state.pollFailures) : interval();
  const headers = () => ({"X-User-Id": state.data.user_id, "X-Request-Id": crypto.randomUUID()});
  const baseUrl = () => `${state.data.backend_url}/api/v1/games/${encodeURIComponent(state.data.game_id)}`;
  const message = (type, fields) => ({schema_version: 1, type,
    component_instance_id: state.data.component_instance_id,
    scope_version: state.data.scope_version, ...fields});
  const emitTick = () => {
    if (state.stopped) return;
    state.lastTick = Math.max(Date.now(), state.lastTick + 1);
    state.publish("status_tick", message("SYNC_STATUS", {
      status: state.status, hidden: hidden(), tick: state.lastTick,
    }));
  };
  const scheduleTick = () => {
    clearTimeout(state.tickTimer);
    state.tickTimer = setTimeout(() => { emitTick(); scheduleTick(); }, tickInterval());
  };
  const emitEnvelope = envelope => {
    if (state.stopped) return;
    const part = envelope?.data || envelope;
    // no-op 응답은 상태 이벤트로 만들지 않는다. AI 처리는 cursor가 같아도 별도
    // tick이 snapshot 재조회를 유도하므로 heartbeat 빈도로 화면이 다시 실행되지 않는다.
    const noOp = part?.game_id === state.data.game_id && part?.mode === "DELTA" &&
      Array.isArray(part.operations) && part.operations.length === 0 &&
      part.last_sequence === state.data.last_sequence &&
      part.state_version === state.data.after_state_version &&
      part.from_state_version === state.data.after_state_version;
    if (noOp) return;
    const serialized = JSON.stringify(envelope);
    if (serialized === state.lastEnvelope) return;
    state.lastEnvelope = serialized;
    state.publish("envelope", message("SYNC_ENVELOPE", {
      event_id: crypto.randomUUID(), envelope,
    }));
  };
  const schedulePoll = milliseconds => {
    clearTimeout(state.pollTimer);
    if (!state.stopped) state.pollTimer = setTimeout(() => { state.pollTimer = null; poll(); }, milliseconds);
  };
  const poll = async (force = false) => {
    if (state.stopped || state.pollController || (state.live && !force)) return;
    if (navigator.onLine === false) {
      state.status = "STALE";
      schedulePoll(interval());
      return;
    }
    const controller = new AbortController();
    state.pollController = controller;
    const timeout = setTimeout(() => controller.abort(), policy.request_timeout_ms);
    try {
      const query = new URLSearchParams({after_state_version: String(state.data.after_state_version),
        after_sequence: String(state.data.last_sequence)});
      const response = await fetch(`${baseUrl()}/sync?${query}`, {headers: headers(), signal: controller.signal});
      if (!response.ok) throw new Error("SYNC_HTTP_FAILED");
      const envelope = await response.json();
      if (state.stopped || controller.signal.aborted) return;
      emitEnvelope(envelope);
      const recovered = state.pollFailures > 0;
      state.pollFailures = 0;
      state.status = state.live ? "LIVE" : "POLLING";
      // snapshot 진행 조회도 장애 중에는 polling과 함께 늦춘다. 응답이 회복되면
      // 정상 2초 tick으로 돌아가 오래된 AI 처리 상태를 계속 표시하지 않는다.
      if (recovered) scheduleTick();
    } catch (_) {
      if (state.stopped) return;
      state.pollFailures += 1;
      const previousStatus = state.status;
      state.status = state.live ? "LIVE" :
        state.pollFailures >= policy.stale_after_failures ? "STALE" : "POLLING";
      if (state.status === "STALE" && previousStatus !== "STALE") { emitTick(); scheduleTick(); }
    } finally {
      clearTimeout(timeout);
      state.pollController = null;
      if (!state.stopped && !state.live) schedulePoll(state.pollFailures
        ? backoff(interval(), state.pollFailures) : interval());
    }
  };
  const connect = async () => {
    if (state.stopped || state.sseController) return;
    const controller = new AbortController();
    state.sseController = controller;
    let reader;
    let connectTimeout = setTimeout(() => controller.abort(), policy.request_timeout_ms);
    try {
      if (navigator.onLine === false) throw new Error("OFFLINE");
      const response = await fetch(`${baseUrl()}/events`, {headers: {...headers(),
        "Last-Event-ID": String(state.data.last_sequence), "Accept": "text/event-stream"},
        signal: controller.signal});
      clearTimeout(connectTimeout);
      if (!response.ok || !response.body) throw new Error("SSE_HTTP_FAILED");
      const recovering = state.pollFailures > 0;
      state.live = true;
      state.status = "LIVE";
      state.pollFailures = 0;
      if (recovering) scheduleTick();
      clearTimeout(state.pollTimer);
      state.pollTimer = null;
      reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (!state.stopped) {
        // 연결만 열린 채 heartbeat도 오지 않으면 polling으로 복구한다. 실제
        // 진행 여부는 game operation이 아니라 stream 수신 여부로만 판단한다.
        connectTimeout = setTimeout(() => controller.abort(), policy.max_backoff_ms);
        const item = await reader.read();
        clearTimeout(connectTimeout);
        if (item.done) break;
        state.sseFailures = 0;
        buffer += decoder.decode(item.value, {stream: true});
        const frames = buffer.split(/\r?\n\r?\n/);
        buffer = frames.pop() || "";
        for (const frame of frames) {
          const lines = frame.split(/\r?\n/);
          const event = lines.find(line => line.startsWith("event:"))?.slice(6).trim();
          if (event && event !== "game_sync") continue;
          const payload = lines.filter(line => line.startsWith("data:")).map(line => line.slice(5).trimStart()).join("\n");
          if (!payload) continue;
          let envelope;
          try {
            envelope = JSON.parse(payload);
            const eventId = lines.find(line => line.startsWith("id:"))?.slice(3).trim();
            if (eventId !== undefined && (!/^\d+$/.test(eventId) ||
              Number(eventId) !== (envelope?.data || envelope)?.last_sequence)) throw new Error("SSE_CURSOR_INVALID");
          } catch (_) {
            // 파싱 실패도 조용히 건너뛰지 않고 reducer의 snapshot 복구 경로로 보낸다.
            emitEnvelope({});
            throw new Error("SSE_FRAME_INVALID");
          }
          emitEnvelope(envelope);
        }
      }
    } catch (_) {
      // 오류 원문·응답 payload·UUID를 로그나 연결 상태에 복사하지 않는다.
    } finally {
      clearTimeout(connectTimeout);
      controller.abort();
      if (reader) { try { await reader.cancel(); } catch (_) {} }
      state.sseController = null;
      if (!state.stopped) {
        state.live = false;
        state.sseFailures += 1;
        state.status = navigator.onLine === false || state.pollFailures >= policy.stale_after_failures ? "STALE" : "POLLING";
        if (!state.pollTimer && !state.pollController) schedulePoll(0);
        state.sseTimer = setTimeout(connect, backoff(policy.sse_retry_ms, state.sseFailures));
      }
    }
  };
  const wake = () => {
    if (state.stopped) return;
    emitTick();
    scheduleTick();
    clearTimeout(state.pollTimer);
    state.pollTimer = null;
    poll(true);
    if (!state.live) { clearTimeout(state.sseTimer); connect(); }
  };
  const visibilityChanged = () => {
    if (!hidden()) wake();
    else { emitTick(); scheduleTick(); }
  };
  const wentOffline = () => {
    state.status = "STALE";
    state.sseController?.abort();
    state.pollController?.abort();
    emitTick();
  };
  state.start = () => {
    document.addEventListener("visibilitychange", visibilityChanged);
    window.addEventListener("online", wake);
    window.addEventListener("offline", wentOffline);
    scheduleTick();
    connect();
    // 게임에 다시 들어온 경우에도 최신 공개 대화부터 읽을 수 있게 한 번 이동한다.
    state.scrollTimelineToLatest();
  };
  state.stop = () => {
    state.stopped = true;
    for (const timer of [state.cleanupTimer, state.tickTimer, state.pollTimer, state.sseTimer, state.scrollTimer]) clearTimeout(timer);
    state.sseController?.abort();
    state.pollController?.abort();
    document.removeEventListener("visibilitychange", visibilityChanged);
    window.removeEventListener("online", wake);
    window.removeEventListener("offline", wentOffline);
  };
  return state;
}
