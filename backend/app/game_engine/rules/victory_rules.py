"""게임의 승패 및 종료 상태를 계산하는 순수 규칙."""

from __future__ import annotations

from backend.app.models.enums import Faction, GamePhase, GameStatus, PlayerRole, WinReason
from backend.app.models.game_state import GameState


def standard_winner(state: GameState) -> tuple[Faction, WinReason] | None:
    """현재 생존자 수로 표준 승패를 계산한다."""

    mafia_count = sum(player.alive and player.faction is Faction.MAFIA for player in state.players)
    citizen_count = sum(player.alive and player.faction is Faction.CITIZEN for player in state.players)
    if mafia_count == 0:
        return Faction.CITIZEN, WinReason.ALL_MAFIA_ELIMINATED
    if mafia_count >= citizen_count:
        return Faction.MAFIA, WinReason.MAFIA_PARITY
    return None


def finish(state: GameState, winner: Faction, reason: WinReason) -> None:
    """승패와 종료 phase를 한 번에 기록한다."""

    state.winner = winner
    state.win_reason = reason
    state.status = GameStatus.COMPLETED
    state.phase = GamePhase.ENDED
