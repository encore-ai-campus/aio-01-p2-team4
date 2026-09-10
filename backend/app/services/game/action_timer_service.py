"""시간 제한이 있는 행동의 deadline을 계산하는 모듈."""

from __future__ import annotations

from datetime import datetime, timedelta

from backend.app.models.enums import GamePhase


_DURATION_SECONDS: dict[GamePhase, int] = {
    GamePhase.NIGHT_ACTION: 30,
    GamePhase.DAY_VOTE: 30,
    GamePhase.REVOTE: 30,
    GamePhase.FINAL_ACCUSATION: 30,
}


def timed_window_kind(phase: GamePhase) -> str | None:
    """phase에 대응하는 시간 제한 행동 종류를 반환한다."""

    return {
        GamePhase.NIGHT_ACTION: "NIGHT",
        GamePhase.DAY_VOTE: "VOTE",
        GamePhase.REVOTE: "REVOTE",
        GamePhase.FINAL_ACCUSATION: "FINAL_VOTE",
    }.get(phase)


def deadline_for(phase: GamePhase, now: datetime) -> datetime | None:
    """phase의 고정 제한 시간을 현재 시각부터 계산한다."""

    seconds = _DURATION_SECONDS.get(phase)
    return now + timedelta(seconds=seconds) if seconds is not None else None


__all__ = ["deadline_for", "timed_window_kind"]
