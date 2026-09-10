"""게임 원장과 분리한 제한 크기 진행 표시와 비밀정보 없는 순차 운영 로그."""

from __future__ import annotations

import json
from collections import OrderedDict, deque
from datetime import UTC, datetime
from threading import RLock
from uuid import UUID, uuid4

from backend.app.core.logging import progress_logger
from backend.app.llm_provider.schemas import PUBLIC_DECISION_BASES

FAILURE_REASONS = {
    "PROVIDER_TIMEOUT", "PROVIDER_AUTHENTICATION", "PROVIDER_RATE_LIMIT",
    "PROVIDER_MODEL_UNAVAILABLE", "PROVIDER_INCOMPLETE", "PROVIDER_UNAVAILABLE",
    "PROPOSAL_INVALID", "MCP_UNAVAILABLE", "MCP_SUBMISSION_FAILED", "AGENT_DEPENDENCY_ERROR",
}


STAGES = {
    "STARTED": "AI 행동 처리를 시작했습니다.",
    "CONTEXT_READY": "허용된 게임 정보를 확인했습니다.",
    "DECIDING": "허용된 행동을 선택하고 있습니다.",
    "DECIDED": "행동 선택을 마쳤습니다.",
    "FALLBACK": "규칙에 따른 기본 행동을 선택했습니다.",
    "APPLIED": "선택한 행동을 게임에 반영했습니다.",
    "FAILED": "행동을 반영하지 못했습니다.",
    "SKIPPED": "중복되거나 지난 작업을 건너뛰었습니다.",
}
EVENTS = {
    "CREATED": "게임을 생성했습니다.", "BEGIN_GAME": "게임을 시작했습니다.",
    "SAVE_AND_EXIT": "게임을 저장했습니다.", "RESUME": "게임을 재개했습니다.",
    "COMMAND_APPLIED": "게임 행동을 저장했습니다.", "PHASE_CHANGED": "게임 단계가 변경되었습니다.",
    "COMPLETED": "게임 결과를 확정했습니다.", "WORKER_FAILED": "진행 작업을 완료하지 못했습니다.",
}
PHASES = {"ROLE_REVEAL", "DAY_DISCUSSION", "NIGHT_ACTION", "DAY_VOTE", "REVOTE", "FINAL_DISCUSSION", "FINAL_ACCUSATION", "ENDED"}
PUBLIC_PHASES = {"DAY_DISCUSSION", "FINAL_DISCUSSION"}


class AgentActivity:
    """한 프로세스의 순서·출력을 잠그고 소유자별 공개 speech만 보관한다.

    메모리는 최대 128게임 × 50개로 제한하며 DB 이력 복원 수단으로 사용하지 않는다.
    비공개 actor와 대상은 출력 전 제거하고 외부 자유 문자열을 받지 않는다.
    """

    def __init__(self, *, max_games: int = 128, max_items: int = 50, logger=None) -> None:
        self.run_id = str(uuid4())
        self._sequence = 0
        self._lock = RLock()
        self._history: OrderedDict[tuple[UUID, UUID], deque] = OrderedDict()
        self._max_games = max(1, min(max_games, 128))
        self._max_items = max(1, min(max_items, 50))
        self._logger = logger

    def record(self, *, game_id: UUID | None = None, owner_user_id: UUID | None = None,
               player_id: UUID | None = None, phase: str | None = None,
               state_version: int | None = None, stage: str, action: str | None = None,
               dummy: bool = False, decision_source: str | None = None,
               reason_code: str | None = None, decision_basis: str | None = None) -> dict:
        """정본 enum과 UUID만 로그에 내보내고 두 출력의 순서를 동일하게 유지한다."""

        if not isinstance(stage, str) or (stage not in STAGES and stage not in EVENTS):
            raise ValueError("등록되지 않은 진행 상태입니다.")
        phase = phase if isinstance(phase, str) and phase in PHASES else None
        version = state_version if type(state_version) is int and state_version > 0 else None
        public = phase in PUBLIC_PHASES
        actor = str(player_id) if public and isinstance(player_id, UUID) else None
        action = action if public and isinstance(action, str) and action in {"SPEAK", "PASS"} else None
        summary = STAGES.get(stage, EVENTS.get(stage))
        if dummy and stage in {"DECIDING", "DECIDED"}:
            summary = "더미 제공자의 고정 행동을 처리하고 있습니다."
        if action and stage in {"DECIDED", "APPLIED"}:
            summary = f"{summary} ({'발언' if action == 'SPEAK' else '차례 넘김'})"
        source = decision_source if isinstance(decision_source, str) and decision_source in {"MODEL", "DUMMY", "FALLBACK"} else None
        source = "FALLBACK" if stage == "FALLBACK" else (source or ("DUMMY" if dummy else None))
        reason = reason_code if isinstance(reason_code, str) and reason_code in FAILURE_REASONS else None
        basis = decision_basis if isinstance(decision_basis, str) and decision_basis in PUBLIC_DECISION_BASES else None
        with self._lock:
            # 같은 actor·버전의 선택 원인은 적용 성공 뒤에도 유지한다. 새 STARTED는
            # 과거 실패를 상속하지 않으며 비공개 phase에는 actor별 메타데이터를 남기지 않는다.
            if public and actor and stage in {"APPLIED", "FAILED", "SKIPPED"}:
                previous = next((row for row in reversed(self._history.get((owner_user_id, game_id), ()))
                                 if row["player_id"] == actor and row["state_version"] == version
                                 and row["phase"] == phase), None)
                if previous:
                    source = source or previous.get("decision_source")
                    reason = reason or previous.get("reason_code")
                    basis = basis or previous.get("decision_basis")
            self._sequence += 1
            item = {"sequence": self._sequence, "run_id": self.run_id,
                    "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    "player_id": actor, "phase": phase, "state_version": version,
                    "stage": stage, "action": action, "summary": summary,
                    "decision_source": source if public else None,
                    "reason_code": reason if public else None,
                    "decision_basis": basis if public else None}
            if public and actor and version and isinstance(game_id, UUID) and isinstance(owner_user_id, UUID) and stage in STAGES:
                key = (owner_user_id, game_id)
                history = self._history.setdefault(key, deque(maxlen=self._max_items))
                history.append(dict(item))
                self._history.move_to_end(key)
                while len(self._history) > self._max_games:
                    self._history.popitem(last=False)
            entry = {**item, "game_id": str(game_id) if isinstance(game_id, UUID) else None}
            try:
                (self._logger or progress_logger()).info(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))
            except Exception:
                # 출력 장애는 이미 성공한 게임 transaction을 실패로 바꾸지 않는다.
                pass
            return dict(item)

    def recent(self, owner_user_id: UUID, game_id: UUID) -> list[dict]:
        """호출자가 게임 소유권을 검증한 뒤 해당 소유자·게임 기록만 복사한다."""

        with self._lock:
            return [dict(item) for item in self._history.get((owner_user_id, game_id), ())]


agent_activity = AgentActivity()
