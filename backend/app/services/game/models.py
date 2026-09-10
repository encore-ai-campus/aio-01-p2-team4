"""게임 업무 서비스가 공유하는 상태 record와 테스트 저장소."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from backend.app.models.game_state import GameState


@dataclass
class CanonicalGameRecord:
    """API가 사용하는 규칙 상태와 공개 동기화 기록을 묶는다."""

    state: GameState
    scenario: dict[str, Any]
    human_player_id: UUID
    owner_user_id: UUID
    alibi: str
    observation: str
    front_sequence: int = 0
    operations: list[dict[str, Any]] = field(default_factory=list)
    public_events: list[dict[str, Any]] = field(default_factory=list)
    eliminated: dict[UUID, tuple[str, int]] = field(default_factory=dict)
    action_window: dict[str, Any] | None = None
    private_events: list[dict[str, Any]] = field(default_factory=list)
    resolutions: list[dict[str, Any]] = field(default_factory=list)
