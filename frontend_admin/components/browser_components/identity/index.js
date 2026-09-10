const instances = new WeakMap();

export default function ({ data, parentElement, setStateValue }) {
  // 관리자 UUID도 강한 인증이 아니므로 Backend allowlist 검사를 반드시 통과해야 한다.
  const key = data?.storage_key || "ai_mafia_admin_user_id_v1";
  const valid = value => typeof value === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
  const publish = (userId, errorCode = null) => {
    const identity = {
      scope_version: data?.scope_version,
      user_id: userId,
      error_code: errorCode,
    };
    const serialized = JSON.stringify(identity);
    // 같은 응답을 다시 통지하면 rerun이 반복되므로 component 인스턴스별로 억제한다.
    if (instances.get(parentElement) !== serialized) {
      instances.set(parentElement, serialized);
      setStateValue("identity", identity);
    }
  };
  try {
    const stored = window.localStorage.getItem(key);
    const userId = data?.replacement ?? stored;
    if (userId === null) {
      // 관리자는 기존 allowlist UUID를 직접 입력하며 임의 UUID를 자동 생성하지 않는다.
      publish(null, "MISSING_UUID");
    } else if (!valid(userId)) {
      publish(null, "INVALID_STORED_UUID");
    } else {
      const normalized = userId.toLowerCase();
      if (stored !== normalized) window.localStorage.setItem(key, normalized);
      publish(normalized);
    }
  } catch (_) {
    publish(null, "STORAGE_BLOCKED");
  }
}
