"""게임 업무 Service가 공유하는 순수 보조 함수."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from backend.app.models.game_state import GameState


def create_game_result(state: GameState) -> dict[str, Any]:
    """게임 생성과 replay가 공유할 최소 불변 응답을 만든다."""

    return {
        "game_id": str(state.game_id),
        "status": state.status.value,
        "phase": state.phase.value,
        "round": state.round,
        "state_version": state.state_version,
        "snapshot_url": f"/api/v1/games/{state.game_id}",
    }


def request_hash(value: dict[str, Any]) -> str:
    """멱등성 receipt 비교용 요청 지문을 안정적으로 계산한다."""

    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def window_id(game_id: UUID, state_version: int) -> UUID:
    """게임과 state version으로 재현 가능한 action window ID를 만든다."""

    return uuid5(NAMESPACE_URL, f"mafia-window:{game_id}:{state_version}")
