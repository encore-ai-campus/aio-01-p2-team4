"""외부 DB와 분리된 순수 게임 상태 모델.

이 파일의 객체는 게임 규칙 테스트와 replay에만 사용한다. 실제 PostgreSQL 저장은
B5/B7에서 Repository가 담당하며, 이 모델에 비밀번호·LLM 원문·Chain of Thought를
넣지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from backend.app.models.enums import (
    Faction,
    GamePhase,
    GameStatus,
    NightActionType,
    PlayerKind,
    PlayerRole,
    WinReason,
)


@dataclass
class PlayerState:
    """게임 한 판 안에서 변하지 않는 정보와 생존 여부를 보관한다."""

    player_id: UUID
    seat: int
    role: PlayerRole
    kind: PlayerKind = PlayerKind.AI
    display_name: str = ""
    alive: bool = True
    custom_role_name: str | None = None
    custom_role_catalog_version: str | None = None
    custom_ability_ids: tuple[str, ...] = ()
    custom_faction: Faction | None = None

    @property
    def faction(self) -> Faction:
        """역할에서 진영을 계산한다. 진영을 별도로 바꾸지 못하게 한다."""

        return self.custom_faction or (
            Faction.MAFIA if self.role is PlayerRole.MAFIA else Faction.CITIZEN
        )


@dataclass(frozen=True)
class NightAction:
    """한 플레이어가 제출한 유효한 첫 밤 행동이다."""

    actor_id: UUID
    action_type: NightActionType
    target_id: UUID


@dataclass(frozen=True)
class Vote:
    """검증된 능력 ID만 보관하고 숫자 가중치는 내부 규칙으로 계산하는 표다."""

    actor_id: UUID
    target_id: UUID
    ability_id: str | None = None

    @property
    def weight(self) -> int:
        """구형·일반 표는 1표이며 검증된 조작 능력 사용 표만 3표로 센다."""

        return 3 if self.ability_id == "vote.triple.v1" else 1


@dataclass(frozen=True)
class EngineOperation:
    """replay에 필요한 최소 명령 기록이다."""

    command: str
    actor_id: UUID | None = None
    target_id: UUID | None = None
    text: str | None = None
    result_state_version: int = 0
    ability_id: str | None = None


@dataclass
class GameState:
    """게임 규칙이 읽고 수정하는 단일 메모리 상태이다."""

    game_id: UUID
    seed: bytes
    players: list[PlayerState]
    phase: GamePhase = GamePhase.ROLE_REVEAL
    status: GameStatus = GameStatus.IN_PROGRESS
    round: int = 0
    day_number: int = 1
    state_version: int = 1
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    speech_actors: set[UUID] = field(default_factory=set)
    speech_question_cycle_used: bool = False
    speech_had_content: bool = False
    night_actions: dict[UUID, NightAction] = field(default_factory=dict)
    votes: dict[UUID, Vote] = field(default_factory=dict)
    # 첫 투표의 최다 득표자만 보관한다. 저장 계층은 재투표 window 후보에서 복원한다.
    revote_candidates: set[UUID] = field(default_factory=set)
    final_accusation_target: UUID | None = None
    last_detective_result: dict[UUID, bool] = field(default_factory=dict)
    remaining_ms_on_save: int | None = None
    deadline_at: datetime | None = None
    winner: Faction | None = None
    win_reason: WinReason | None = None
    operations: list[EngineOperation] = field(default_factory=list)
    # 인간 사망 여부와 별개의 명시적 설정이다. 영속 저장·복원과 변경 명령은 B5가 담당한다.
    fast_forward_enabled: bool = False
    mode: str = "STANDARD"

    @property
    def alive_players(self) -> list[PlayerState]:
        """좌석순 생존 플레이어 목록을 반환한다."""

        return sorted((player for player in self.players if player.alive), key=lambda p: p.seat)

    @property
    def player_by_id(self) -> dict[UUID, PlayerState]:
        """검증할 때 반복 검색하지 않도록 현재 플레이어를 색인한다."""

        return {player.player_id: player for player in self.players}

    @property
    def human_alive(self) -> bool:
        """생존한 인간이 있는지 반환한다."""

        return any(player.alive and player.kind is PlayerKind.HUMAN for player in self.players)
