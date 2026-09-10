const instances = new WeakMap();

export default function ({ data, parentElement, setStateValue }) {
  // 저장값은 UUID v4 형식으로만 사용하고 임의의 값은 Python으로 반환하지 않는다.
  const key = data?.storage_key || "ai_mafia_user_id_v1";
  const valid = value => typeof value === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
  const previous = instances.get(parentElement) || {};
  const publish = (userId, persistence, errorCode = null) => {
    const identity = {
      schema_version: 1,
      component_instance_id: data?.component_instance_id,
      scope_version: data?.scope_version,
      user_id: userId,
      persistence,
      error_code: errorCode,
    };
    const serialized = JSON.stringify(identity);
    // component의 state 통지는 Streamlit을 다시 실행하므로 같은 응답은 반복 전송하지 않는다.
    const changed = previous.published !== serialized;
    previous.published = serialized;
    previous.sessionOnly = persistence === "SESSION_ONLY";
    if (valid(userId)) previous.userId = userId;
    instances.set(parentElement, previous);
    if (changed) setStateValue("identity", identity);
  };
  const generate = () => {
    try {
      return crypto.randomUUID();
    } catch (_) {
      return null;
    }
  };

  let stored = null;
  let storageBlocked = false;
  try {
    stored = window.localStorage.getItem(key);
  } catch (_) {
    storageBlocked = true;
  }

  let userId;
  if (data?.replacement != null) {
    if (!valid(data.replacement)) {
      publish(null, null, "INVALID_BRIDGE_RESPONSE");
      return;
    }
    userId = data.replacement.toLowerCase();
  } else if (data?.reset_stored) {
    // 손상된 저장값의 재생성 요청을 같은 scope로 다시 받아도 UUID는 한 번만 만든다.
    userId = previous.resetScope === data.scope_version ? previous.resetUserId : generate();
    previous.resetScope = data.scope_version;
    previous.resetUserId = userId;
  } else if (storageBlocked || data?.session_only || previous.sessionOnly) {
    // 복구 쓰기만 차단된 경우 저장소의 옛 UUID가 다음 rerun에서 새 scope를 덮지 않게 한다.
    userId = valid(data?.current_user_id) ? data.current_user_id : previous.userId || generate();
  } else if (stored === null) {
    userId = valid(data?.current_user_id) ? data.current_user_id : previous.userId || generate();
  } else if (valid(stored)) {
    userId = stored.toLowerCase();
  } else {
    publish(null, null, "INVALID_STORED_UUID");
    return;
  }

  if (!valid(userId)) {
    publish(null, storageBlocked ? "SESSION_ONLY" : null,
      storageBlocked ? "STORAGE_BLOCKED" : "CRYPTO_UNAVAILABLE");
    return;
  }
  if (!storageBlocked && stored !== userId) {
    try {
      window.localStorage.setItem(key, userId);
    } catch (_) {
      storageBlocked = true;
    }
  }
  publish(userId, storageBlocked ? "SESSION_ONLY" : "LOCAL",
    storageBlocked ? "STORAGE_BLOCKED" : null);
}
