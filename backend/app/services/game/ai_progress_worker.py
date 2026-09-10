"""게임별 프로세스 없이 Backend가 AI 차례를 회복·진행하는 중앙 worker."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from backend.app.agent.activity import agent_activity
from backend.app.core.errors import ApiError


logger = logging.getLogger(__name__)

_WORKER_STAGES = frozenset({
    "worker_cycle", "vote_worker_cycle", "discussion_worker_cycle", "expired_lookup", "expired_processing",
    "expired_vote_processing", "speech_turn_lookup", "speech_turn_processing",
    "night_turn_lookup", "night_turn_processing", "vote_turn_lookup", "vote_turn_processing",
    "stale_game_cleanup",
})
_WORKER_API_REASONS = frozenset({
    "DUPLICATE_ACTION", "STALE_STATE_VERSION", "WINDOW_CLOSED", "ACTION_NOT_ALLOWED",
    "ACTION_ALREADY_SUBMITTED", "INVALID_PHASE", "GAME_NOT_FOUND", "DEPENDENCY_UNAVAILABLE",
})


class AiProgressWorker:
    """발언·밤 진행과 투표 scheduler를 분리해 열린 투표를 즉시 병렬 처리한다."""

    def __init__(
        self,
        runtime: Any,
        *,
        interval: float = 1.0,
        cleanup_interval: float = 30.0,
    ) -> None:
        """실행 runtime만 주입하고 DB 연결·저장소를 직접 소유하지 않는다."""

        self._runtime = runtime
        self._interval = interval
        self._cleanup_interval = cleanup_interval
        self._task: asyncio.Task[None] | None = None
        self._vote_task: asyncio.Task[None] | None = None
        self._discussion_task: asyncio.Task[None] | None = None
        self._cleanup_task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._vote_wakeup: asyncio.Event | None = None
        self._stopping = False
        self._fast_forward_progressed = False

    def start(self) -> None:
        """FastAPI event loop에서 단일 worker task를 시작한다."""

        if self._task is None or self._task.done():
            self._stopping = False
            self._loop = asyncio.get_running_loop()
            self._vote_wakeup = asyncio.Event()
            self._task = asyncio.create_task(self._run(), name="ai-progress-worker")
            self._vote_task = asyncio.create_task(self._run_votes(), name="ai-vote-worker")
            self._discussion_task = asyncio.create_task(
                self._run_discussions(), name="discussion-pre-vote-worker"
            )
            self._cleanup_task = asyncio.create_task(
                self._run_stale_game_cleanup(), name="stale-game-cleanup-worker"
            )

    def wake_votes(self) -> None:
        """command thread에서 투표 polling을 깨우되 아직 기동하지 않은 worker는 건너뛴다."""

        loop, wakeup = self._loop, self._vote_wakeup
        if loop is not None and wakeup is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(wakeup.set)
            except RuntimeError:
                # 종료와 commit 반환이 겹쳐 loop가 닫혀도 이미 저장한 command의
                # 성공을 실패 응답으로 바꾸지 않는다. 다음 기동 시 DB에서 복구한다.
                pass

    async def stop(self) -> None:
        """서버 종료 시 다음 polling을 기다리지 않고 worker를 종료한다."""

        self._stopping = True
        tasks = [
            task for task in (
                self._task, self._vote_task, self._discussion_task, self._cleanup_task,
            ) if task is not None
        ]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._task = self._vote_task = self._discussion_task = self._cleanup_task = None
        self._loop = None
        self._vote_wakeup = None

    async def _run_votes(self) -> None:
        """진행 중 LLM 작업을 기다리지 않고 새 투표와 deadline을 계속 관찰한다."""

        active: dict[tuple[UUID, UUID], asyncio.Task] = {}
        try:
            while not self._stopping:
                self._vote_wakeup.clear()
                try:
                    for key, task in list(active.items()):
                        if task.done():
                            del active[key]
                            if task.cancelled():
                                continue
                            try:
                                task.result()
                            except Exception as error:
                                _log_worker_error("vote_turn_processing", error)
                    expired = await asyncio.to_thread(self._runtime.list_expired_vote_windows)
                    for window in expired:
                        try:
                            await asyncio.to_thread(
                                self._runtime.auto_resolve_expired_vote,
                                UUID(str(window["owner_user_id"])), UUID(str(window["game_id"])),
                            )
                        except Exception as error:
                            _log_worker_error("expired_vote_processing", error)
                    turns = await asyncio.to_thread(self._runtime.list_ai_vote_turns)
                    grouped: dict[tuple[UUID, UUID], list[dict[str, Any]]] = {}
                    for turn in turns:
                        key = UUID(str(turn["game_id"])), UUID(str(turn["window_id"]))
                        grouped.setdefault(key, []).append(turn)
                    for (game_id, window_id), game_turns in grouped.items():
                        key = game_id, window_id
                        if key in active:
                            continue
                        task = asyncio.create_task(self._runtime.run_agent_vote_turn(
                            UUID(str(game_turns[0]["owner_user_id"])), game_id, game_turns,
                        ), name="ai-vote-window")
                        active[key] = task
                except Exception as error:
                    _log_worker_error("vote_worker_cycle", error)
                try:
                    await asyncio.wait_for(self._vote_wakeup.wait(), timeout=self._interval)
                except TimeoutError:
                    pass
        finally:
            for task in active.values():
                task.cancel()
            await asyncio.gather(*active.values(), return_exceptions=True)

    async def _run_discussions(self) -> None:
        """분석 준비 DB 지연을 기존 투표·밤 deadline scheduler와 분리한다."""

        if not hasattr(self._runtime, "expire_discussions"):
            return
        while not self._stopping:
            try:
                await asyncio.to_thread(self._runtime.expire_discussions)
            except Exception as error:
                _log_worker_error("discussion_worker_cycle", error)
            await asyncio.sleep(self._interval)

    async def _run_stale_game_cleanup(self) -> None:
        """15분 무동작 진행 게임을 AI 진행과 독립된 저빈도 sweep으로 정리한다."""

        if not hasattr(self._runtime, "cleanup_stale_games"):
            return
        while not self._stopping:
            try:
                await asyncio.to_thread(self._runtime.cleanup_stale_games)
            except Exception as error:
                # 정리 장애가 게임 진행 worker를 끝내지 않으며 외부 예외 원문도
                # 남기지 않는다. 다음 주기에는 DB 조건으로 같은 후보만 재확인한다.
                _log_worker_error("stale_game_cleanup", error)
            await asyncio.sleep(self._cleanup_interval)

    async def _run(self) -> None:
        """동기 psycopg 작업은 thread로 보내 API event loop를 점유하지 않는다."""

        while not self._stopping:
            try:
                await asyncio.to_thread(self.progress_once, include_votes=False)
            except Exception as error:
                # 다음 주기에 다시 조회한다. 개별 게임 실패가 worker 전체를 끝내면
                # 재시작 전까지 다른 게임의 AI 진행도 멈추므로 오류를 격리한다.
                _log_worker_error("worker_cycle", error)
            await asyncio.sleep(0 if self._fast_forward_progressed else self._interval)

    def progress_once(self, *, include_votes: bool = True) -> int:
        """현재 열린 AI speech 차례를 처리한 게임 수를 반환한다."""

        progressed = 0
        self._fast_forward_progressed = False
        for kind in (("night", "vote") if include_votes else ("night",)):
            lookup = getattr(self._runtime, f"list_expired_{kind}_windows", None)
            resolve = getattr(self._runtime, f"auto_resolve_expired_{kind}", None)
            if lookup is None or resolve is None:
                continue
            try:
                expired_windows = lookup()
            except Exception as error:
                _log_worker_error("expired_lookup", error)
                continue
            for window in expired_windows:
                try:
                    owner_id, game_id = UUID(str(window["owner_user_id"])), UUID(str(window["game_id"]))
                    result = resolve(owner_id, game_id)
                    if result is not None:
                        progressed += 1
                        self._note_fast_forward(owner_id, game_id)
                except Exception as error:
                    _log_worker_error("expired_processing", error)

        try:
            turns = self._runtime.list_ai_speech_turns()
        except Exception as error:
            _log_worker_error("speech_turn_lookup", error)
            turns = []
        logger.debug("AI worker speech turn lookup completed: count=%d", len(turns))
        for turn in turns:
            try:
                owner_id = UUID(str(turn["owner_user_id"]))
                game_id = UUID(str(turn["game_id"]))
                player_id = UUID(str(turn["turn_player_id"]))
                if hasattr(self._runtime, "run_agent_turn"):
                    # 원래 window가 끝난 오류를 새 PASS로 바꾸지 않는다. 의존성 fallback은
                    # 관찰한 binding을 가진 runtime에서만 처리한다.
                    result = asyncio.run(self._runtime.run_agent_turn(owner_id, game_id, player_id))
                    if isinstance(result, dict) and result.get("status") == "DEFERRED":
                        continue
                else:
                    self._runtime.agent_pass(
                        owner_id,
                        game_id,
                        player_id,
                        expected_state_version=int(turn["state_version"]),
                        window_id=UUID(str(turn["window_id"])),
                    )
            except Exception as error:
                _log_worker_error("speech_turn_processing", error)
                continue
            progressed += 1
            self._note_fast_forward(owner_id, game_id)
        if hasattr(self._runtime, "list_ai_night_turns") and hasattr(self._runtime, "run_agent_night_turn"):
            try:
                night_turns = self._runtime.list_ai_night_turns()
            except Exception as error:
                _log_worker_error("night_turn_lookup", error)
                night_turns = []
            grouped: dict[tuple[UUID, UUID], list[dict[str, Any]]] = {}
            for turn in night_turns:
                key = (UUID(str(turn["game_id"])), UUID(str(turn["window_id"])))
                grouped.setdefault(key, []).append(turn)
            for (game_id, _window_id), game_turns in grouped.items():
                try:
                    owner_id = UUID(str(game_turns[0]["owner_user_id"]))
                    result = asyncio.run(self._runtime.run_agent_night_turn(owner_id, game_id, game_turns))
                    if isinstance(result, tuple) and result[1]:
                        continue
                except Exception as error:
                    _log_worker_error("night_turn_processing", error)
                    continue
                progressed += 1
                self._note_fast_forward(owner_id, game_id)
        if include_votes and hasattr(self._runtime, "list_ai_vote_turns") and hasattr(self._runtime, "run_agent_vote_turn"):
            try:
                vote_turns = self._runtime.list_ai_vote_turns()
            except Exception as error:
                _log_worker_error("vote_turn_lookup", error)
                vote_turns = []
            grouped: dict[tuple[UUID, UUID], list[dict[str, Any]]] = {}
            for turn in vote_turns:
                key = (UUID(str(turn["game_id"])), UUID(str(turn["window_id"])))
                grouped.setdefault(key, []).append(turn)
            for (game_id, _window_id), game_turns in grouped.items():
                try:
                    owner_id = UUID(str(game_turns[0]["owner_user_id"]))
                    result = asyncio.run(self._runtime.run_agent_vote_turn(owner_id, game_id, game_turns))
                    if isinstance(result, tuple) and result[1]:
                        continue
                except Exception as error:
                    _log_worker_error("vote_turn_processing", error)
                    continue
                progressed += 1
                self._note_fast_forward(owner_id, game_id)
        return progressed


    def _note_fast_forward(self, owner_id: UUID, game_id: UUID) -> None:
        """원장을 정상 저장한 빠른 진행만 다음 주기의 대기 시간을 생략한다."""

        enabled = getattr(self._runtime, "fast_forward_enabled", None)
        if enabled is not None:
            try:
                self._fast_forward_progressed |= enabled(owner_id, game_id) is True
            except Exception:
                # 로그·관전 편의 조회 실패로 이미 성공한 행동을 실패로 뒤집지 않는다.
                pass


def _log_worker_error(stage: str, error: Exception) -> None:
    """외부 예외 원문·동적 class명·traceback 없이 승인된 고정 오류만 기록한다."""

    safe_stage = stage if type(stage) is str and stage in _WORKER_STAGES else "worker_cycle"
    reason = "UNEXPECTED_ERROR"
    if isinstance(error, ApiError) and type(error.code) is str and error.code in _WORKER_API_REASONS:
        reason = error.code
    elif isinstance(error, TimeoutError):
        reason = "DEPENDENCY_TIMEOUT"
    # 공개 activity의 phase·원인 enum을 넓히지 않고 운영 로그만 고정 코드로 보완한다.
    # 로그 출력 장애가 다음 게임 처리까지 중단시키지 않도록 예외도 격리한다.
    try:
        logger.warning("AI worker failed: stage=%s reason_code=%s", safe_stage, reason)
    except Exception:
        pass
    agent_activity.record(stage="WORKER_FAILED")
