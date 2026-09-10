"""PostgreSQL 기반 게임 업무 Service 조합부."""

from __future__ import annotations

from datetime import UTC, datetime
import asyncio
from hashlib import sha256
import logging
import os
from typing import Any
from threading import RLock
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from psycopg.rows import dict_row
from psycopg.errors import LockNotAvailable, QueryCanceled
from redis import Redis

from backend.app.core.config import Settings
from backend.app.core.errors import ApiError
from backend.app.infrastructure.transaction import TransactionManager
from backend.app.infrastructure.redis.cache import RedisConversationHistory
from backend.app.llm_provider.factory import get_llm_provider
from backend.app.llm_provider.schemas import NormalizedAgentProposal
from backend.app.agent.activity import agent_activity
from backend.app.agent.orchestrator import AgentJobSpec, AgentOrchestrator, AgentRunResult
from backend.app.mcp.client import FastMcpGameContextClient
from backend.app.repositories.action_repository import PostgresActionRepository
from backend.app.repositories.feedback_repository import PostgresFeedbackRepository
from backend.app.repositories.game_repository import GameStateKeyring, PostgresGameRepository
from backend.app.repositories.player_repository import PostgresPlayerRepository
from backend.app.repositories.user_repository import PostgresUserRepository
from backend.app.schemas.command_schema import GameCommandRequest
from backend.app.schemas.feedback_schema import FeedbackRequest
from backend.app.schemas.game_schema import CreateGameRequest
from backend.app.services.game.command_service import (
    PostgresActionCommandService,
    PostgresAgentDiscussionService,
    PostgresBeginGameService,
    PostgresDiscussionCommandService,
)
from backend.app.services.game.ai_progress_worker import AiProgressWorker
from backend.app.services.game.creation_service import PostgresGameCreationService
from backend.app.services.game.feedback_service import PostgresFeedbackService
from backend.app.repositories.agent_repository import PostgresAgentRepository
from backend.app.services.game.actor_context import ActorContext, read_actor_context
from backend.app.services.game.game_read_service import PostgresGameReadService
from backend.app.services.game.lifecycle_service import (
    PostgresGameResumeService,
    PostgresGameSaveService,
)


class PostgresGameRuntime:
    """테이블 Repository를 게임 업무 Service로 조합하는 실행 계층."""

    def __init__(self, settings: Settings) -> None:
        """설정된 기존 PostgreSQL을 모든 업무 Service가 공유하게 한다."""

        database_url = settings.effective_database_url
        transactions = TransactionManager(database_url)
        self._transactions = transactions
        self._settings = settings
        self._activity = agent_activity
        self._mutation_lock = RLock()
        self._agent_repository = PostgresAgentRepository(transactions)
        self._games = PostgresGameRepository()
        self._actions_repository = PostgresActionRepository()
        self._players = PostgresPlayerRepository()
        keyring = (
            GameStateKeyring.from_settings(settings)
            if settings.game_state_keyring_file and settings.game_state_active_key_id
            else GameStateKeyring.legacy_plaintext()
        )
        users = PostgresUserRepository(database_url)
        common = {"transactions": transactions, "keyring": keyring}
        self._redis = Redis.from_url(
            settings.redis_url, socket_connect_timeout=0.25, socket_timeout=0.25,
            decode_responses=True,
        )
        # 같은 로컬 Redis를 쓰는 QA·공유 DB의 기록을 섞지 않는다. 자격 증명은
        # namespace 입력에도 넣지 않고 접속 대상의 host·port·database만 구분한다.
        address = urlsplit(database_url)
        namespace = sha256(
            f"{address.hostname}:{address.port or 5432}{address.path}".encode()
        ).hexdigest()[:16]
        self._conversation_history = RedisConversationHistory(self._redis, namespace=namespace)
        self._create = PostgresGameCreationService(**common, users=users)
        self._feedback = PostgresFeedbackService(
            transactions=transactions,
            users=users,
            games=self._games,
            feedback=PostgresFeedbackRepository(),
        )
        self._read = PostgresGameReadService(**common, conversation_history=self._conversation_history)
        self._begin = PostgresBeginGameService(**common)
        self._save = PostgresGameSaveService(**common)
        self._resume = PostgresGameResumeService(**common)
        self._discussion = PostgresDiscussionCommandService(**common)
        self._agent_discussion = PostgresAgentDiscussionService(**common)
        self._actions = PostgresActionCommandService(**common)
        self._ai_worker = AiProgressWorker(self)
        self.configure_speech_analysis(None)

    def configure_speech_analysis(self, repository: Any | None) -> None:
        """실제로 시작된 분석 worker의 저장소만 연결하여 초기화 실패 시 대기를 남기지 않는다."""

        self._speech_analysis_repository = repository
        self._discussion.wait_for_speech_analysis = repository is not None
        self._agent_discussion.wait_for_speech_analysis = repository is not None

    def expire_discussions(self) -> None:
        """토론 마감 뒤 분석이 끝난 게임만 투표 창을 열고 새 제한 시간을 부여한다."""
        from backend.app.services.game.discussion_transaction import expire_discussion
        with self._transactions.transaction() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                rows = self._actions_repository.expired_discussions(cursor, now=datetime.now(UTC))
        for row in rows:
            repository = self._speech_analysis_repository
            voting_next = row["phase"] == "FINAL_DISCUSSION" or (
                row["phase"] == "DAY_DISCUSSION" and row["day_number"] >= 2
            )
            analysis_state = "DISABLED" if repository is None else "NOT_REQUIRED"
            if repository is not None and voting_next:
                try:
                    # 모델 호출과 분석 선점은 독립 worker가 맡는다. 게임 잠금과 runtime의
                    # mutation lock을 잡지 않아 다른 게임·저장 요청이 함께 대기하지 않는다.
                    settings = self._settings
                    ready = repository.prepare_for_vote(
                        game_id=row["id"],
                        analysis_version=settings.effective_speech_analysis_version,
                        embedding_model=settings.speech_analysis_embedding_model,
                        dimensions=settings.speech_analysis_dimensions,
                        claims_model=settings.speech_analysis_claims_model,
                        max_attempts=settings.speech_analysis_max_attempts,
                    )
                    if not ready:
                        continue
                    analysis_state = "READY"
                except Exception as error:
                    # 분석 저장소 장애는 게임 원장을 영구 정지시키지 않는다. 예외 원문을
                    # 기록하지 않고 이번 투표는 확보된 부분 결과로 진행한다.
                    analysis_state = "FAILED"
                    reason = (
                        "DB_LOCK_TIMEOUT" if isinstance(error, LockNotAvailable)
                        else "DB_QUERY_CANCELED" if isinstance(error, QueryCanceled)
                        else "DEPENDENCY_TIMEOUT" if isinstance(error, TimeoutError)
                        else "PREPARE_ERROR"
                    )
                    logging.getLogger(__name__).warning(
                        "SPEECH_ANALYSIS_PRE_VOTE_FAILED game_id=%s window_id=%s "
                        "pid=%s reason_code=%s",
                        row["id"], row["window_id"], os.getpid(), reason,
                    )
            try:
                result = self._mutation(row["owner_user_id"], row["id"], lambda: expire_discussion(
                    self._discussion, row["owner_user_id"], row["id"],
                    expected_window_id=row["window_id"],
                ))
                # 다른 프로세스가 먼저 전환하거나 창이 교체된 경우에는 성공 로그를
                # 남기지 않는다. 실제 전환을 확정한 프로세스와 분석 우회 여부를 구분한다.
                if result is not None:
                    logging.getLogger(__name__).info(
                        "DISCUSSION_TRANSITION_APPLIED game_id=%s window_id=%s "
                        "pid=%s analysis=%s",
                        row["id"], row["window_id"], os.getpid(), analysis_state,
                    )
            except Exception:
                # 한 게임의 원장 오류가 다른 게임의 완료된 분석과 투표 전환을 막지 않는다.
                logging.getLogger(__name__).warning("DISCUSSION_TRANSITION_FAILED")

    def list_ai_speech_turns(self) -> list[dict[str, Any]]:
        """열린 AI 발언 차례를 조회해 중앙 worker에 전달한다.

        worker가 transaction과 Repository를 직접 소유하면 실행 조합 경계가
        분산되므로, PostgreSQL runtime이 조회 transaction을 관리한다. 이 메서드는
        읽기만 수행하며 실제 AI command 변경 transaction은 agent_pass가 소유한다.
        """

        with self._transactions.transaction() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                return self._actions_repository.list_ai_speech_turns(cursor)

    def list_ai_night_turns(self) -> list[dict[str, Any]]:
        """모든 required 밤 역할이 AI인 게임의 actor를 조회한다."""

        with self._transactions.transaction() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                return self._actions_repository.list_ai_night_turns(cursor)

    def list_expired_night_windows(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        """deadline이 지난 밤 window를 조회해 자동 해소 worker에 전달한다."""

        current_time = now or datetime.now(UTC)
        with self._transactions.transaction() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                return self._actions_repository.list_expired_night_windows(
                    cursor, now=current_time
                )

    def auto_resolve_expired_night(
        self, owner_user_id: UUID, game_id: UUID, *, now: datetime | None = None
    ) -> dict[str, Any] | None:
        """인간 포함 무응답 밤 행동을 deadline 기준으로 결정적으로 해소한다."""

        return self._mutation(owner_user_id, game_id, lambda: self._actions.auto_resolve_expired_night(
            owner_user_id, game_id, now=now
        ))

    def list_ai_vote_turns(self) -> list[dict[str, Any]]:
        """열린 투표 window에서 아직 처리되지 않은 AI actor를 조회한다."""

        with self._transactions.transaction() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                return self._actions_repository.list_ai_vote_turns(cursor)

    def list_expired_vote_windows(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        """일반·재투표·최종 투표의 무응답 window를 같은 원장 기준으로 조회한다."""

        with self._transactions.transaction() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                return self._actions_repository.list_expired_vote_windows(cursor, now=now or datetime.now(UTC))

    def auto_resolve_expired_vote(self, owner_user_id: UUID, game_id: UUID, *, now: datetime | None = None) -> dict[str, Any] | None:
        """투표 deadline 해소 성공 뒤에만 게임 진행 로그를 남긴다."""

        return self._mutation(owner_user_id, game_id, lambda: self._actions.auto_resolve_expired_vote(owner_user_id, game_id, now=now))

    async def run_agent_night_turn(self, owner_user_id: UUID, game_id: UUID, turns: list[dict[str, Any]]) -> tuple[dict[str, Any], bool]:
        """밤 actor별 선택을 모아 기존 단일 batch transaction으로 저장한다."""

        return await self._run_agent_batch(owner_user_id, game_id, turns, job_kind="NIGHT_ACTION")

    async def run_agent_vote_turn(self, owner_user_id: UUID, game_id: UUID, turns: list[dict[str, Any]]) -> tuple[dict[str, Any], bool]:
        """모든 AI 판단을 동시에 시작하고 완료된 표부터 독립 transaction으로 저장한다."""

        if not turns:
            return {"status": "DEFERRED"}, True
        version = int(turns[0]["state_version"])
        window_id = UUID(str(turns[0]["window_id"]))
        phase = str(turns[0]["phase"])
        if any(int(turn["state_version"]) != version
               or UUID(str(turn["window_id"])) != window_id or str(turn["phase"]) != phase
               for turn in turns):
            return {"status": "DEFERRED"}, True

        async def decide_and_submit(turn: dict[str, Any]) -> tuple[dict[str, Any], bool] | None:
            """한 actor의 실패·취소는 그 actor만 정리하고 다른 완료 표를 보존한다."""

            player_id = UUID(str(turn["player_id"]))
            decision = None
            applied = False
            try:
                decision = await self._run_orchestrated_proposal(
                    owner_user_id, game_id, player_id, window_id, version,
                    job_kind="VOTE", phase=phase,
                )
                if decision.status not in {"SUCCEEDED", "FALLBACK"} or decision.reservation is None:
                    return None
                proposal = decision.proposal
                if proposal is None or proposal.type != "VOTE" or proposal.target_player_id is None:
                    return None
                result, replayed = await asyncio.to_thread(
                    self._mutation, owner_user_id, game_id,
                    lambda: self._actions.submit_agent_votes(
                        owner_user_id, game_id,
                        [{"player_id": player_id, "target_player_id": proposal.target_player_id}],
                        expected_state_version=version, window_id=window_id,
                        idempotency_key=uuid4(), reservation=decision.reservation,
                    ),
                )
                applied = True
                self._record_agent(owner_user_id, game_id, player_id, phase, version,
                                   "SKIPPED" if replayed else "APPLIED")
                return result, replayed
            except Exception:
                self._record_agent(owner_user_id, game_id, player_id, phase, version, "FAILED")
                return None
            finally:
                if decision is not None and not applied:
                    await asyncio.to_thread(self._release_unapplied_results, [decision])

        completed = await asyncio.gather(*(decide_and_submit(turn) for turn in turns), return_exceptions=True)
        committed = [item for item in completed if isinstance(item, tuple) and not item[1]]
        if committed:
            return max(committed, key=lambda item: item[0]["result_state_version"])
        return {"status": "DEFERRED"}, True

    async def _run_agent_batch(self, owner_user_id: UUID, game_id: UUID, turns: list[dict[str, Any]], *, job_kind: str) -> tuple[dict[str, Any], bool]:
        """중복·지난 proposal은 현재 window에 새 행동으로 바꾸지 않고 폐기한다."""

        if not turns:
            return {"status": "DEFERRED"}, True
        expected_version = int(turns[0]["state_version"])
        window_id = UUID(str(turns[0]["window_id"]))
        phase = str(turns[0].get("phase", "NIGHT_ACTION" if job_kind == "NIGHT_ACTION" else "DAY_VOTE"))
        actions = []
        results = []
        applied = False
        try:
            for turn in turns:
                if int(turn["state_version"]) != expected_version or UUID(str(turn["window_id"])) != window_id:
                    return {"status": "DEFERRED"}, True
                player_id = UUID(str(turn["player_id"]))
                result = await self._run_orchestrated_proposal(owner_user_id, game_id, player_id, window_id, expected_version, job_kind=job_kind, phase=phase)
                results.append(result)
                if result.status in {"DUPLICATE", "STALE"}:
                    for previous in actions:
                        self._record_agent(owner_user_id, game_id, previous["player_id"], phase, expected_version, "SKIPPED")
                    return {"status": "DEFERRED"}, True
                proposal = result.proposal
                if proposal is None or proposal.type != job_kind or proposal.target_player_id is None:
                    proposal = self._fallback_target_proposal(owner_user_id, game_id, player_id, expected_type=job_kind,
                                                              state_version=expected_version, window_id=window_id, phase=phase)
                    self._record_agent(owner_user_id, game_id, player_id, phase, expected_version, "FALLBACK")
                if proposal is None:
                    raise ValueError("허용된 AI 대상이 없습니다.")
                actions.append({"player_id": player_id, "target_player_id": proposal.target_player_id})
            submit = self._actions.submit_agent_night_actions if job_kind == "NIGHT_ACTION" else self._actions.submit_agent_votes
            result, replayed = self._mutation(owner_user_id, game_id, lambda: submit(owner_user_id, game_id, actions,
                expected_state_version=expected_version, window_id=window_id, idempotency_key=uuid4()))
            applied = True
            for action in actions:
                self._record_agent(owner_user_id, game_id, action["player_id"], phase, expected_version, "SKIPPED" if replayed else "APPLIED")
            return result, replayed
        except Exception:
            for turn in turns:
                self._record_agent(owner_user_id, game_id, UUID(str(turn["player_id"])), phase, expected_version, "FAILED")
            raise
        finally:
            if not applied:
                self._release_unapplied_results(results)

    async def _run_orchestrated_proposal(
        self,
        owner_user_id: UUID,
        game_id: UUID,
        player_id: UUID,
        window_id: UUID,
        state_version: int,
        *,
        job_kind: str,
        phase: str,
    ) -> AgentRunResult:
        """하나의 AI proposal을 reservation·capability 경계 안에서 생성한다."""

        context = FastMcpGameContextClient(self._settings.mcp_server_url, user_id=owner_user_id, game_id=game_id,
                                           player_id=player_id, phase=phase, state_version=state_version, window_id=window_id,
                                           allow_vote_submission_version=job_kind == "VOTE")
        try:
            orchestrator = AgentOrchestrator(
                repository=self._agent_repository,
                provider=get_llm_provider(self._settings),
                context_client=context, activity=self._activity, owner_user_id=owner_user_id,
                max_output_tokens=self._settings.llm_max_output_tokens,
                timeout_seconds=self._settings.llm_timeout_seconds,
            )
            result = await orchestrator.run(AgentJobSpec(
                game_id=game_id, player_id=player_id, window_id=window_id,
                job_kind=job_kind, phase=phase, state_version=state_version,
            ))
            return result
        finally:
            await context.close()

    def start_background_worker(self) -> None:
        """PostgreSQL runtime에 중앙 AI 진행 task를 연결한다."""

        self._ai_worker.start()

    def cleanup_stale_games(self) -> int:
        """15분간 사용자 command가 없는 진행 게임과 공개 cache를 정리한다.

        PostgreSQL 삭제가 권위 결과다. Redis 장애나 이미 만료된 cache miss는 DB
        transaction을 되돌리지 않으며 cache TTL도 후속 안전망으로 유지한다.
        """

        with self._transactions.transaction() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                game_ids = self._games.delete_stale_in_progress(cursor, limit=100)
        for game_id in game_ids:
            self._conversation_history.delete(str(game_id))
        return len(game_ids)

    def _fallback_target_proposal(self, owner_user_id: UUID, game_id: UUID, player_id: UUID, *,
                                  expected_type: str, state_version: int, window_id: UUID, phase: str) -> NormalizedAgentProposal | None:
        """인간 snapshot 대신 소유권·AI 권한을 검증한 현재 actor turn에서만 고른다."""

        context = read_actor_context(self._read, owner_user_id=owner_user_id, game_id=game_id,
                                     player_id=player_id, scope="turn", agents=self._agent_repository)
        if context["state_version"] != state_version or context["window_id"] != str(window_id) or context["phase"] != phase:
            return None
        targets = context["data"]["valid_targets"]
        if not targets:
            return None
        return AgentOrchestrator._fallback_proposal(
            AgentJobSpec(game_id, player_id, window_id, expected_type, phase, state_version),
            {"turn": context},
        )

    async def stop_background_worker(self) -> None:
        """앱 종료 시 중앙 AI 진행 task를 정리한다."""

        await self._ai_worker.stop()
        self._redis.close()

    async def run_agent_turn(self, owner_user_id: UUID, game_id: UUID, player_id: UUID) -> dict[str, Any]:
        """speech는 검증된 MCP Tool 성공을 확인하고 장애 fallback은 원래 window로 제한한다."""

        snapshot = self.snapshot(owner_user_id, game_id)
        window = snapshot.get("action_window") or {}
        phase = snapshot["game"]["phase"]
        version = snapshot["game"]["state_version"]
        if phase not in {"DAY_DISCUSSION", "FINAL_DISCUSSION"} or window.get("turn_player_id") != str(player_id):
            self._record_agent(owner_user_id, game_id, player_id, phase, version, "SKIPPED")
            return {"status": "DEFERRED"}
        window_id = UUID(window["window_id"])
        spec = AgentJobSpec(game_id, player_id, window_id, "SPEECH", phase, version,
                            day_number=snapshot["game"]["day_number"])
        fallback_proposal = AgentOrchestrator._fallback_proposal(spec, {})

        def submit_bound_proposal(proposal):
            """모든 대체·복구 발언을 최초 관찰한 window와 버전에서만 제출한다."""

            if proposal.type == "SPEAK":
                return self.agent_speak(owner_user_id, game_id, player_id, proposal.message,
                    expected_state_version=version, window_id=window_id)
            return self.agent_pass(owner_user_id, game_id, player_id,
                expected_state_version=version, window_id=window_id)

        context = FastMcpGameContextClient(self._settings.mcp_server_url, user_id=owner_user_id, game_id=game_id,
                                           player_id=player_id, phase=phase, state_version=version, window_id=window_id)
        result = None
        applied = False
        try:
            orchestrator = AgentOrchestrator(repository=self._agent_repository, provider=get_llm_provider(self._settings),
                context_client=context, activity=self._activity, owner_user_id=owner_user_id, close_context=False,
                max_output_tokens=self._settings.llm_max_output_tokens,
                timeout_seconds=self._settings.llm_timeout_seconds)
            result = await orchestrator.run(spec)
            if result.status in {"STALE", "DUPLICATE"}:
                return {"status": "DEFERRED"}
            proposal = result.proposal
            if proposal is None or proposal.type not in {"PASS", "SPEAK"}:
                proposal = fallback_proposal
                self._record_agent(owner_user_id, game_id, player_id, phase, version, "FALLBACK", proposal.type)
            if result.recovered or result.status == "FALLBACK":
                # MCP 조회가 실패하면 불완전한 Tool binding을 재구성하지 않고 같은
                # service에 제출한다. 첫날의 기본 SPEAK도 다시 PASS로 바꾸지 않는다.
                receipt, replayed = submit_bound_proposal(proposal)
            else:
                try:
                    accepted = await context.submit_action(game_id=game_id, player_id=player_id,
                                                            action=proposal.model_dump(mode="json"))
                    receipt, replayed = accepted["result"], accepted["replayed"]
                except Exception:
                    # 제출 경로 장애만으로 검증된 발언을 기본 대사로 바꾸지 않는다.
                    # 이미 commit된 응답이 유실돼도 최초 window/version 검증을 유지해
                    # 같은 원문이 새 차례에 중복 적용되는 것을 막는다.
                    self._record_agent(owner_user_id, game_id, player_id, phase, version, "FALLBACK", proposal.type,
                                       reason_code="MCP_SUBMISSION_FAILED")
                    receipt, replayed = submit_bound_proposal(proposal)
            applied = True
            self._record_agent(owner_user_id, game_id, player_id, phase, version,
                               "SKIPPED" if replayed else "APPLIED", proposal.type)
            return receipt
        except Exception:
            # 실패 뒤 현재 차례를 재조회해 새 version으로 행동을 덧붙이지 않는다.
            self._record_agent(owner_user_id, game_id, player_id, phase, version, "FAILED")
            raise
        finally:
            if result is not None and not applied:
                self._release_unapplied_results([result])
            await context.close()

    def _release_unapplied_results(self, results: list[AgentRunResult]) -> None:
        """rollback·중단된 적용 시도의 해당 token만 반환하고 원래 오류를 보존한다."""

        for result in results:
            if result.reservation is None or result.status not in {"SUCCEEDED", "FALLBACK"}:
                continue
            try:
                self._agent_repository.release_unapplied_job(result.reservation)
            except Exception:
                # 반환 자체가 실패하면 고정 lease 만료 후 같은 미제출 확인으로 복구한다.
                # DB 예외 원문과 저장 proposal은 로그에 남기지 않는다.
                pass

    def _record_agent(self, owner_user_id: UUID, game_id: UUID, player_id: UUID, phase: str,
                      version: int, stage: str, action: str | None = None, *, reason_code: str | None = None) -> None:
        """행동 대상·발언 원문 없이 AI 처리 상태만 중앙 collector에 기록한다."""

        self._activity.record(owner_user_id=owner_user_id, game_id=game_id, player_id=player_id,
                              phase=phase, state_version=version, stage=stage, action=action,
                              reason_code=reason_code)

    def _observed_game(self, owner_user_id: UUID, game_id: UUID) -> dict[str, Any]:
        """로그 보조 조회가 실패해도 mutation의 원래 성공·실패 결과를 유지한다."""

        try:
            return self._read.snapshot(owner_user_id, game_id)["game"]
        except Exception:
            return {}

    def fast_forward_enabled(self, owner_user_id: UUID, game_id: UUID) -> bool:
        """빠른 진행 선택은 소유권 검증된 저장 상태에서만 읽는다."""

        return self._observed_game(owner_user_id, game_id).get("fast_forward_enabled") is True

    def _mutation(self, owner_user_id: UUID, game_id: UUID, call, *, event: str = "COMMAND_APPLIED"):
        """동일 runtime의 commit 반환·로그를 직렬화하고 rollback에는 성공을 남기지 않는다."""

        with self._mutation_lock:
            before = self._observed_game(owner_user_id, game_id)
            output = call()
            if output is None:
                return output
            result, replayed = output if isinstance(output, tuple) else (output, False)
            version = result.get("result_state_version", result.get("state_version"))
            after = self._observed_game(owner_user_id, game_id) if not replayed else {}
            phase = after.get("phase") if after.get("state_version") == version else before.get("phase")
            self._activity.record(game_id=game_id, phase=phase, state_version=version,
                                  stage="SKIPPED" if replayed else event)
            if not replayed and after.get("state_version") == version:
                if before.get("phase") != after.get("phase"):
                    self._activity.record(game_id=game_id, phase=phase, state_version=version, stage="PHASE_CHANGED")
                if after.get("status") == "COMPLETED" and before.get("status") != "COMPLETED":
                    self._activity.record(game_id=game_id, phase=phase, state_version=version, stage="COMPLETED")
        if not replayed and not after:
            try:
                # 정상 after snapshot은 이미 공개 이력을 갱신한다. 비공개 결과 등으로
                # snapshot 복원이 실패한 경우에만 공개 원장을 별도로 복구하며, 실패가
                # 이미 성공한 command를 실패 응답으로 바꾸면 안 된다.
                self._read.refresh_public_history(owner_user_id, game_id)
            except Exception:
                logging.getLogger(__name__).warning("공개 대화 cache 갱신을 다음 조회에서 재시도합니다.")
        if not replayed:
            self._ai_worker.wake_votes()
        return output

    def create(
        self,
        owner_user_id: UUID,
        payload: CreateGameRequest,
        idempotency_key: UUID,
    ) -> tuple[dict[str, Any], bool]:
        """게임 생성 업무를 PostgreSQL transaction으로 실행한다."""

        with self._mutation_lock:
            result, replayed = self._create.create(owner_user_id, payload, idempotency_key)
            game_id = UUID(result["game_id"])
            self._activity.record(game_id=game_id, phase="ROLE_REVEAL", state_version=result.get("state_version", 1),
                                  stage="SKIPPED" if replayed else "CREATED")
            return result, replayed

    def list_games(
        self,
        owner_user_id: UUID,
        *,
        status: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        """소유자 게임 목록을 PostgreSQL에서 읽는다."""

        return self._read.list_games(owner_user_id, status=status, limit=limit)

    def snapshot(self, owner_user_id: UUID, game_id: UUID) -> dict[str, Any]:
        """현재 PostgreSQL read adapter가 지원하는 snapshot을 읽는다."""

        snapshot = self._read.snapshot(owner_user_id, game_id)
        return {**snapshot, "agent_activity": self._activity.recent(owner_user_id, game_id)}

    def special_roles(self, owner_user_id: UUID, game_id: UUID) -> dict[str, Any]:
        """공개 조회도 내부 MCP와 동일한 읽기 검증·최소 projection만 사용한다."""

        from backend.app.services.game.game_read_service import read_special_roles

        return read_special_roles(self._read, owner_user_id=owner_user_id, game_id=game_id)

    def delete_game(
        self, owner_user_id: UUID, game_id: UUID, *, expected_state_version: int,
    ) -> dict[str, Any]:
        """수동 삭제의 DB 확정 뒤 공개 cache를 정리하며 Redis 장애는 성공을 취소하지 않는다."""

        from backend.app.services.game.lifecycle_service import delete_game

        result = delete_game(self, owner_user_id, game_id, expected_state_version=expected_state_version)
        try:
            self._conversation_history.delete(str(game_id))
        except Exception:
            logging.getLogger(__name__).warning("삭제된 게임의 공개 대화 cache 정리를 완료하지 못했습니다.")
        return result

    def command(
        self,
        owner_user_id: UUID,
        game_id: UUID,
        payload: GameCommandRequest,
        idempotency_key: UUID,
    ) -> tuple[dict[str, Any], bool]:
        """구현된 command Service만 선택하고 미구현 command는 실패시킨다."""

        if payload.type == "BEGIN_GAME":
            return self._mutation(owner_user_id, game_id, lambda: self._begin.begin(owner_user_id, game_id, payload, idempotency_key), event="BEGIN_GAME")
        if payload.type in {"SPEAK", "PASS"}:
            return self._mutation(owner_user_id, game_id, lambda: self._discussion.submit(owner_user_id, game_id, payload, idempotency_key), event="COMMAND_APPLIED")
        if payload.type in {"SUBMIT_NIGHT_ACTION", "SUBMIT_VOTE"}:
            return self._mutation(owner_user_id, game_id, lambda: self._actions.submit(owner_user_id, game_id, payload, idempotency_key), event="COMMAND_APPLIED")
        if payload.type == "FAST_FORWARD":
            return self._mutation(owner_user_id, game_id, lambda: self._actions.fast_forward(owner_user_id, game_id, payload, idempotency_key), event="COMMAND_APPLIED")
        if payload.type == "SAVE_AND_EXIT":
            return self._mutation(owner_user_id, game_id, lambda: self._save.save(owner_user_id, game_id, payload, idempotency_key), event="SAVE_AND_EXIT")
        if payload.type == "RESUME":
            return self._mutation(owner_user_id, game_id, lambda: self._resume.resume(owner_user_id, game_id, payload, idempotency_key), event="RESUME")
        raise ApiError(
            status_code=501,
            code="GAME_COMMAND_NOT_IMPLEMENTED",
            message="해당 게임 command는 PostgreSQL 업무 계층에 아직 연결되지 않았습니다.",
        )

    def agent_pass(
        self,
        owner_user_id: UUID,
        game_id: UUID,
        player_id: UUID,
        *,
        expected_state_version: int,
        window_id: UUID,
    ) -> tuple[dict[str, Any], bool]:
        """운영 Agent Manager 없이 deterministic AI PASS를 저장한다."""

        return self._mutation(owner_user_id, game_id, lambda: self._agent_discussion.submit_pass(
            owner_user_id,
            game_id,
            player_id,
            expected_state_version=expected_state_version,
            window_id=window_id,
        ))

    def agent_speak(
        self,
        owner_user_id: UUID,
        game_id: UUID,
        player_id: UUID,
        message: str,
        *,
        expected_state_version: int,
        window_id: UUID,
    ) -> tuple[dict[str, Any], bool]:
        """LLM이 만든 발언을 AI player 원장으로 저장한다."""

        return self._mutation(owner_user_id, game_id, lambda: self._agent_discussion.submit_speak(
            owner_user_id, game_id, player_id, message,
            expected_state_version=expected_state_version, window_id=window_id,
        ))

    def agent_action(
        self,
        owner_user_id: UUID,
        game_id: UUID,
        player_id: UUID,
        payload: GameCommandRequest,
        idempotency_key: UUID,
    ) -> tuple[dict[str, Any], bool]:
        """AI night·vote proposal을 공통 action transaction으로 전달한다."""

        return self._mutation(owner_user_id, game_id, lambda: self._actions.submit(
            owner_user_id,
            game_id,
            payload,
            idempotency_key,
            actor=ActorContext.agent(owner_user_id=owner_user_id, player_id=player_id),
        ))

    def sync(self, owner_user_id: UUID, game_id: UUID, **_: int) -> dict[str, Any]:
        """PostgreSQL game_events를 기준으로 polling sync를 반환한다."""

        return self._read.sync(owner_user_id, game_id, **_)

    def feedback(
        self,
        owner_user_id: UUID,
        payload: FeedbackRequest,
        idempotency_key: UUID,
    ) -> tuple[dict[str, Any], bool]:
        """feedback 요청을 PostgreSQL 업무 서비스로 전달한다."""

        return self._feedback.submit(owner_user_id, payload, idempotency_key)
