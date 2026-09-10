"""AI Mafia의 외부 서비스 없는 순수 규칙 엔진.

이 엔진은 DB, Redis, LLM, MCP를 호출하지 않는다. 하나의 명령을 검증하고 상태를
바꾸는 역할만 하며, 실제 저장·event·transaction 연결은 다음 Backend WU에서
서비스 계층이 담당한다. 따라서 이 파일만으로도 고정 seed 전체 replay가 가능하다.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from backend.app.game_engine.fallback import auto_night_target, auto_vote_target
from backend.app.game_engine.rng import DeterministicRng, generate_seed
from backend.app.game_engine.errors import RuleViolation
from backend.app.game_engine.rules.discussion_rules import normalize_speech
from backend.app.game_engine.rules.night_rules import ABILITY_ACTIONS, required_actors, role_action
from backend.app.game_engine.rules.player_rules import eliminate_player, find_player, require_alive_player
from backend.app.game_engine.replay import apply_operation
from backend.app.game_engine.rules.vote_rules import leaders
from backend.app.game_engine.rules.victory_rules import finish
from backend.app.game_engine.phases.transition import (
    after_night,
    after_vote,
    touch,
)
from backend.app.game_engine.phases import discussion as discussion_phase
from backend.app.game_engine.phases import night as night_phase
from backend.app.game_engine.phases import role_reveal as role_reveal_phase
from backend.app.game_engine.phases import final_accusation as final_accusation_phase
from backend.app.game_engine.phases import vote as vote_phase_module
from backend.app.models.enums import (
    Faction,
    GamePhase,
    GameStatus,
    NightActionType,
    PlayerKind,
    PlayerRole,
    WinReason,
)
from backend.app.models.game_state import EngineOperation, GameState, NightAction, PlayerState, Vote


ROLE_COUNTS: dict[int, tuple[int, int, int, int]] = {
    6: (1, 1, 1, 3),
    7: (1, 1, 1, 4),
    8: (2, 1, 1, 4),
    9: (2, 1, 1, 5),
}
class GameEngine:
    """명령을 순서대로 적용하는 게임 엔진."""

    @classmethod
    def new_game(
        cls,
        players: list[tuple[UUID, PlayerKind]] | list[PlayerState],
        *,
        seed: bytes | str | None = None,
        game_id: UUID | None = None,
    ) -> GameState:
        """6~9명에게 seed 기반 역할을 배정해 ROLE_REVEAL 상태를 만든다."""

        if not 6 <= len(players) <= 9:
            raise RuleViolation("PLAYER_COUNT_INVALID")
        seed_bytes = seed.encode("utf-8") if isinstance(seed, str) else seed or generate_seed()
        source: list[PlayerState] = []
        for seat, item in enumerate(players, start=1):
            if isinstance(item, PlayerState):
                source.append(copy.copy(item))
                source[-1].seat = seat
            else:
                player_id, kind = item
                source.append(PlayerState(player_id=player_id, seat=seat, role=PlayerRole.CITIZEN, kind=kind))

        mafia, detective, doctor, citizen = ROLE_COUNTS[len(source)]
        roles = (
            [PlayerRole.MAFIA] * mafia
            + [PlayerRole.DETECTIVE] * detective
            + [PlayerRole.DOCTOR] * doctor
            + [PlayerRole.CITIZEN] * citizen
        )
        shuffled = DeterministicRng(seed_bytes).shuffle(source, "role-assignment")
        # 역할표와 player 수가 일치하지 않으면 조용히 일부만 배정하지 않고 즉시 실패한다.
        for player, role in zip(shuffled, roles, strict=True):
            player.role = role
        # 역할 배정 순서와 좌석은 별개다. 공개 화면의 좌석은 생성 입력 순서를 유지한다.
        ordered = sorted(shuffled, key=lambda player: player.seat)
        return GameState(game_id=game_id or uuid4(), seed=seed_bytes, players=ordered)

    @classmethod
    def replay(
        cls,
        initial: GameState,
        operations: list[EngineOperation],
    ) -> GameState:
        """초기 상태의 복사본에 명령 기록을 재생한다.

        replay 입력은 서버가 검증해 만든 내부 기록만 받아야 한다. 클라이언트가
        임의로 만든 operation을 신뢰하거나 DB에 바로 반영하는 용도로 사용하지 않는다.
        """

        state = copy.deepcopy(initial)
        state.operations.clear()
        engine = cls()
        for operation in operations:
            apply_operation(engine, state, operation)
        return state

    def _player(self, state: GameState, player_id: UUID | None) -> PlayerState:
        return find_player(state, player_id)

    def _alive_actor(self, state: GameState, actor_id: UUID | None) -> PlayerState:
        return require_alive_player(state, actor_id)

    def _record(self, state: GameState, command: str, actor_id: UUID | None = None, **kwargs: object) -> None:
        state.operations.append(
            EngineOperation(command=command, actor_id=actor_id, result_state_version=state.state_version, **kwargs)
        )

    def _advance_if_speeches_done(self, state: GameState) -> None:
        """생존자 발언이 끝났을 때 첫날 예외 또는 다음 phase를 적용한다."""
        discussion_phase.advance_if_done(state)

    def _speech_pending(self, state: GameState, alive_ids: set[UUID]) -> bool:
        return alive_ids - state.speech_actors != set()

    def begin_game(self, state: GameState) -> GameState:
        """역할 공개 화면을 끝내고 첫날 토론을 시작한다."""

        role_reveal_phase.begin(state)
        self._record(state, "BEGIN_GAME")
        return state

    def speak(self, state: GameState, actor_id: UUID | None, text: str) -> GameState:
        """생존 플레이어의 발언을 1~200자로 정규화해 처리한다."""

        normalized = discussion_phase.speak(state, actor_id, text)
        self._record(state, "SPEAK", actor_id, text=normalized)
        return state

    def pass_turn(self, state: GameState, actor_id: UUID | None) -> GameState:
        """발언하지 않고 PASS한 것으로 처리한다."""

        actor = self._alive_actor(state, actor_id)
        discussion_phase.pass_turn(state, actor.player_id)
        self._record(state, "PASS", actor.player_id)
        return state

    @staticmethod
    def normalize_speech(text: str) -> str:
        """제어문자를 제거하고 Unicode NFC·공백 규칙을 적용한다."""
        return normalize_speech(text)

    def _role_action(self, state: GameState, actor_id: UUID | None) -> NightActionType:
        return role_action(state, actor_id)

    @staticmethod
    def _required_night_actors(state: GameState) -> list[PlayerState]:
        """마감 전 해소에는 모든 생존 마피아·탐정·의사의 제출을 요구한다."""

        return required_actors(state)

    def submit_night_action(
        self,
        state: GameState,
        actor_id: UUID | None,
        action_type: NightActionType,
        target_id: UUID,
    ) -> GameState:
        """역할에 맞는 밤 행동을 첫 유효 제출만 저장한다."""

        night_phase.submit_action(state, actor_id, action_type, target_id)
        actor = self._player(state, actor_id)
        # 커스텀 능력의 선택을 기록해야 재생 시 저장 순서의 첫 능력으로 바뀌지 않는다.
        ability_id = next((item for item in actor.custom_ability_ids
                           if ABILITY_ACTIONS.get(item) == action_type), None)
        self._record(state, "SUBMIT_NIGHT_ACTION", actor_id,
                     target_id=target_id, ability_id=ability_id)
        return state

    def resolve_night(self, state: GameState, *, force: bool = False) -> GameState:
        """밤 행동을 모으고 내부 NIGHT_RESOLUTION을 거쳐 다음 phase로 이동한다."""

        night_phase.resolve(state, force=force)
        self._record(state, "RESOLVE_NIGHT")
        return state

    def submit_vote(self, state: GameState, actor_id: UUID | None, target_id: UUID,
                    *, ability_id: str | None = None) -> GameState:
        """낮 투표 또는 재투표에서 유효한 첫 표를 저장한다."""

        actor = self._alive_actor(state, actor_id)
        vote_phase_module.submit(state, actor.player_id, target_id, ability_id=ability_id)
        self._record(state, "SUBMIT_VOTE", actor.player_id, target_id=target_id, ability_id=ability_id)
        return state

    def resolve_vote(self, state: GameState, *, force: bool = False) -> GameState:
        """표를 집계하고 동률이면 한 번만 REVOTE로 전환한다."""

        vote_phase = state.phase
        vote_phase_module.resolve(state, force=force)
        self._record(
            state,
            "RESOLVE_REVOTE" if vote_phase is GamePhase.REVOTE else "RESOLVE_VOTE",
        )
        return state

    def advance_final_discussion(self, state: GameState) -> GameState:
        """다섯 번째 밤 뒤 최종 토론을 최종 고발 단계로 넘긴다."""

        if state.phase is not GamePhase.FINAL_DISCUSSION:
            raise RuleViolation("INVALID_PHASE")
        state.phase = GamePhase.FINAL_ACCUSATION
        touch(state)
        self._record(state, "FINAL_DISCUSSION")
        return state

    def submit_final_accusation(self, state: GameState, actor_id: UUID | None, target_id: UUID) -> GameState:
        """최종 지목을 누적하고 생존자 전원 제출 뒤 다수결로 판정한다."""

        actor = self._alive_actor(state, actor_id)
        final_accusation_phase.submit(state, actor.player_id, target_id)
        self._record(state, "FINAL_ACCUSATION", actor.player_id, target_id=target_id)
        return state

    def resolve_final_accusation(self, state: GameState, *, force: bool = False) -> GameState:
        """최종 지목을 해소하며 마감 후에는 미제출자의 유효 표만 자동 보충한다."""

        final_accusation_phase.resolve(state, force=force)
        self._record(state, "RESOLVE_FINAL_ACCUSATION")
        return state

    def save(self, state: GameState, remaining_ms: int | None) -> GameState:
        """저장 시 deadline을 멈추고 timed window의 시간만 보관한다.

        발언 window와 ROLE_REVEAL처럼 deadline이 원래 없던 상태에는 ``None``을
        유지한다. 이를 0으로 바꾸면 재개 시 원래 시간 제한이 없던 화면이 즉시
        만료된 것처럼 보일 수 있으므로, 0은 실제 timed window가 이미 끝났을 때만
        허용한다.
        """

        if state.status is not GameStatus.IN_PROGRESS:
            raise RuleViolation("GAME_NOT_IN_PROGRESS")
        if remaining_ms is not None and remaining_ms < 0:
            raise RuleViolation("REMAINING_TIME_INVALID")
        state.status = GameStatus.SAVED
        state.remaining_ms_on_save = remaining_ms
        state.deadline_at = None
        touch(state)
        self._record(state, "SAVE_AND_EXIT")
        return state

    def resume(self, state: GameState, now: datetime | None = None) -> GameState:
        """저장된 게임을 재개하고 timed window에만 새 서버 deadline을 만든다.

        저장 당시 window가 없었거나 발언 차례였다면 남은 시간이 없다. 그 경우에도
        게임은 재개할 수 있지만 deadline은 만들지 않아야 한다.
        """

        if state.status is not GameStatus.SAVED:
            raise RuleViolation("GAME_NOT_SAVED")
        current = now or datetime.now(UTC)
        state.status = GameStatus.IN_PROGRESS
        if state.remaining_ms_on_save is None:
            state.deadline_at = None
        else:
            state.deadline_at = current + timedelta(milliseconds=state.remaining_ms_on_save)
        state.remaining_ms_on_save = None
        touch(state)
        self._record(state, "RESUME")
        return state

    def fast_forward(self, state: GameState) -> GameState:
        """인간이 사망한 게임을 AI fallback만으로 자동 진행한다."""

        if state.human_alive:
            raise RuleViolation("FAST_FORWARD_NOT_ALLOWED")
        for _ in range(100):
            if state.status is GameStatus.COMPLETED:
                return state
            if state.phase is GamePhase.ROLE_REVEAL:
                self.begin_game(state)
            elif state.phase is GamePhase.DAY_DISCUSSION:
                for player in state.alive_players:
                    if player.player_id not in state.speech_actors:
                        if state.day_number == 1:
                            self.speak(state, player.player_id, "난 앞으로 나온 주장과 그 근거가 맞는지 비교해 볼게.")
                        else:
                            self.pass_turn(state, player.player_id)
            elif state.phase is GamePhase.NIGHT_ACTION:
                self.resolve_night(state, force=True)
            elif state.phase in {GamePhase.DAY_VOTE, GamePhase.REVOTE}:
                self.resolve_vote(state, force=True)
            elif state.phase is GamePhase.FINAL_DISCUSSION:
                self.advance_final_discussion(state)
            elif state.phase is GamePhase.FINAL_ACCUSATION:
                self.resolve_final_accusation(state, force=True)
            else:
                raise RuleViolation("FAST_FORWARD_PHASE_INVALID")
        raise RuleViolation("FAST_FORWARD_STEP_LIMIT")

    @staticmethod
    def _eliminate(state: GameState, target_id: UUID) -> None:
        """대상을 사망 처리한다. 이미 죽은 대상은 다시 처리하지 않는다."""

        eliminate_player(state, target_id)
