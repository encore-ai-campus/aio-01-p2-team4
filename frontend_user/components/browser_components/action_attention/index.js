const instances = new WeakMap();

export default function ({ data, parentElement }) {
  // 같은 행동 window의 매초 countdown rerender에는 같은 문구를 반복해서
  // 읽지 않는다. 이 component는 안내 live region만 갱신하고 화면 이동은 하지 않는다.
  const previous = instances.get(parentElement) || {
    announcement: null,
  };
  const windowId = typeof data?.window_id === "string" ? data.window_id : null;
  const announcement = typeof data?.announcement === "string" ? data.announcement : null;
  if (announcement !== previous.announcement) {
    const liveRegion = parentElement.querySelector("[data-ai-mafia-action-attention]");
    if (liveRegion) liveRegion.textContent = announcement || "";
    previous.announcement = announcement;
  }
  instances.set(parentElement, previous);
}
