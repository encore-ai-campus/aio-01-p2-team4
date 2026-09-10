"""agent_jobs와 agent_capabilities의 PostgreSQL Repository."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from backend.app.infrastructure.transaction import TransactionManager
from backend.app.repositories.action_repository import PostgresActionRepository

try:
    from psycopg.types.json import Jsonb
except ImportError:  # 테스트 환경에서 psycopg가 없어도 모듈 구조를 읽을 수 있게 한다.
    def Jsonb(value):  # type: ignore[misc]
        """psycopg가 없을 때 fake cursor에 원본 값을 전달한다."""

        return value


@dataclass(frozen=True, slots=True)
class AgentReservation:
    """DB에 RESERVED로 기록된 job과 fencing token이다."""

    job_id: UUID
    game_id: UUID
    player_id: UUID | None
    window_id: UUID
    job_kind: str
    state_version: int
    lease_token: UUID
    lease_expires_at: datetime
    recovered_proposal: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class CapabilityGrant:
    """raw capability는 실행 중 메모리에만 두고 hash는 DB 저장용으로 쓴다."""

    raw_token: str
    token_hash: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class CapabilityRecord:
    """내부 API가 다시 확인해야 하는 capability·job의 공개 메타데이터다."""

    token_hash: str
    job_id: UUID | None
    game_id: UUID
    subject_type: str
    subject_player_id: UUID | None
    phase: str
    state_version: int
    window_id: UUID | None
    allowed_resources: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    expires_at: datetime
    revoked_at: datetime | None
    job_status: str | None
    job_lease_expires_at: datetime | None


class PostgresAgentRepository:
    """Agent 예약·capability의 SQL만 담당한다. 외부 호출은 orchestrator가 한다."""

    # 기본 모델 상한 30초에 MCP 조회·완료·제출 여유를 더하되 실제 창 마감은 넘지 않는다.
    MAX_LEASE_SECONDS = 40
    MAX_CAPABILITY_SECONDS = 120

    def __init__(self, transaction_manager: TransactionManager | None = None) -> None:
        """짧은 Repository transaction을 열 연결 관리자를 받는다."""

        self.transaction_manager = transaction_manager

    def list_active_personas(
        self,
        cursor: Any,
        *,
        version: str,
    ) -> list[Mapping[str, Any]]:
        """게임 생성 시 AI에게 배정할 활성 persona 목록을 ID 순서로 읽는다.

        페르소나는 말투·행동·추론 성향 데이터이며 모델이나 정보 권한을 바꾸지 않는다.
        선택은 service의 seed 기반 RNG가 맡고 이 저장소는 승인된 후보만 반환한다.
        """

        cursor.execute(
            """
            SELECT id, version, display_name, speech_style, backstory,
                   parameters, content_hash
            FROM public.agent_personas
            WHERE version = %s
              AND active = TRUE
            ORDER BY id
            """,
            (version,),
        )
        return list(cursor.fetchall())

    def _connection_cursor(self):
        """공개 Repository 메서드가 사용할 짧은 DB transaction을 연다."""

        if self.transaction_manager is None:
            raise RuntimeError("TransactionManager is required for PostgresAgentRepository")
        connection_context = self.transaction_manager.transaction()
        connection = connection_context.__enter__()
        cursor_context = connection.cursor()
        cursor = (
            cursor_context.__enter__()
            if hasattr(cursor_context, "__enter__")
            else cursor_context
        )
        return connection_context, cursor_context, cursor

    @staticmethod
    def _close_connection_cursor(
        contexts: tuple[Any, Any, Any], error: BaseException | None = None
    ) -> None:
        """수동으로 연 cursor와 connection context를 예외 여부에 맞게 닫는다."""

        connection_context, cursor_context, _ = contexts
        if hasattr(cursor_context, "__exit__"):
            cursor_context.__exit__(type(error), error, error.__traceback__ if error else None)
        if error is None:
            connection_context.__exit__(None, None, None)
        else:
            connection_context.__exit__(type(error), error, error.__traceback__)

    def _run_transaction(self, operation: Callable[[Any], Any]) -> Any:
        """성공·실패와 무관하게 cursor와 connection을 반드시 닫는다.

        ``return``이 ``try`` 안에 있으면 Python의 ``else``가 실행되지 않아
        성공 transaction이 닫히지 않는 실수가 생길 수 있다. B7 내부 API가
        capability를 조회할 때도 같은 연결 생명주기를 사용하므로 결과를 변수에
        담은 뒤 정상 종료하는 형태로 고정한다.
        """

        contexts = self._connection_cursor()
        try:
            result = operation(contexts[2])
        except BaseException as error:
            self._close_connection_cursor(contexts, error)
            raise
        self._close_connection_cursor(contexts)
        return result

    def reserve_job(
        self,
        *,
        game_id: UUID,
        player_id: UUID | None,
        window_id: UUID,
        job_kind: str,
        state_version: int,
        window_deadline: datetime | None = None,
        now: datetime | None = None,
    ) -> AgentReservation | None:
        """현재 미제출 job만 예약하고 미적용 terminal 결과는 같은 binding에서 복구한다."""

        return self._run_transaction(
            lambda cursor: self._reserve_job(
                cursor,
                game_id=game_id,
                player_id=player_id,
                window_id=window_id,
                job_kind=job_kind,
                state_version=state_version,
                window_deadline=window_deadline,
                now=now,
            )
        )

    def _reserve_job(
        self,
        cursor: Any,
        *,
        game_id: UUID,
        player_id: UUID | None,
        window_id: UUID,
        job_kind: str,
        state_version: int,
        window_deadline: datetime | None,
        now: datetime | None,
    ) -> AgentReservation | None:
        """게임→window→job 잠금 순서로 하나의 worker에게만 복구 권한을 준다.

        실제 행동은 별도 transaction에서 저장되므로 SUCCEEDED도 적용 완료의 증거가
        아니다. 원래 버전의 열린 window에 제출 원장이 없고 이전 lease가 반환되거나
        만료됐을 때만 저장 proposal을 인수한다. 새 RESERVED 행에는 결과를 두지 않는다.
        """

        current = now or datetime.now(UTC)
        binding = self._lock_action_binding(cursor, game_id=game_id, player_id=player_id,
                                            window_id=window_id, job_kind=job_kind,
                                            state_version=state_version, now=current)
        if binding is None:
            return None
        lease_expires = current + timedelta(seconds=self.MAX_LEASE_SECONDS)
        if binding[0] is not None:
            lease_expires = min(lease_expires, binding[0])
        if window_deadline is not None:
            lease_expires = min(lease_expires, window_deadline)
        if lease_expires <= current:
            return None
        job_id, lease_token = uuid4(), uuid4()
        cursor.execute(
            """
            SELECT id, reserved_state_version, status, lease_expires_at, normalized_proposal
            FROM agent_jobs
            WHERE game_id = %s AND window_id = %s AND player_id IS NOT DISTINCT FROM %s
              AND job_kind = %s
            FOR UPDATE
            """,
            (game_id, window_id, player_id, job_kind),
        )
        row = cursor.fetchone()
        if row is not None:
            old_id, old_version, old_status, old_expires, saved = row
            if old_status not in {"RESERVED", "SUCCEEDED", "FALLBACK", "STALE", "FAILED"}:
                return None
            if old_status in {"RESERVED", "SUCCEEDED", "FALLBACK"} and old_expires > current:
                return None
            if old_version != state_version:
                if job_kind not in {"SPEECH", "VOTE"}:
                    return None
                # 저장·재개로 버전이 바뀐 발언·투표는 현재 binding과 lease 회수
                # 조건을 통과했어도 과거 판단 결과를 재사용하지 않는다. 새 token과
                # 현재 버전으로 예약해 이전 worker의 늦은 완료를 계속 거부한다.
                cursor.execute(
                    """
                    UPDATE agent_jobs SET reserved_state_version = %s, status = 'RESERVED',
                        lease_token = %s, lease_expires_at = %s, normalized_proposal = NULL,
                        failure_code = NULL, completed_at = NULL
                    WHERE id = %s
                    """, (state_version, lease_token, lease_expires, old_id),
                )
                return AgentReservation(
                    job_id=old_id, game_id=game_id, player_id=player_id, window_id=window_id,
                    job_kind=job_kind, state_version=state_version, lease_token=lease_token,
                    lease_expires_at=lease_expires,
                )
            # GM narration은 action_submissions로 적용 여부를 증명할 수 없으므로
            # 기존 성공 GM 결과를 player 행동처럼 복구하지 않는다.
            if player_id is None and old_status == "SUCCEEDED":
                return None
            if old_status == "SUCCEEDED" and saved is None:
                return None
            recovered = saved if old_status in {"SUCCEEDED", "FALLBACK"} else None
            cursor.execute(
                """
                UPDATE agent_jobs
                SET status = 'RESERVED', lease_token = %s, lease_expires_at = %s,
                    normalized_proposal = NULL, failure_code = NULL, completed_at = NULL
                WHERE id = %s
                """,
                (lease_token, lease_expires, old_id),
            )
            return AgentReservation(
                job_id=old_id, game_id=game_id, player_id=player_id, window_id=window_id,
                job_kind=job_kind, state_version=state_version, lease_token=lease_token,
                lease_expires_at=lease_expires, recovered_proposal=recovered,
            )
        cursor.execute(
            """
            INSERT INTO agent_jobs (
                id, game_id, player_id, window_id, job_kind,
                reserved_state_version, status, lease_token, lease_expires_at
            ) VALUES (%s, %s, %s, %s, %s, %s, 'RESERVED', %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING id, game_id, player_id, window_id, job_kind,
                      reserved_state_version, lease_token, lease_expires_at
            """,
            (
                job_id,
                game_id,
                player_id,
                window_id,
                job_kind,
                state_version,
                lease_token,
                lease_expires,
            ),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return AgentReservation(
            job_id=row[0], game_id=row[1], player_id=row[2], window_id=row[3],
            job_kind=row[4], state_version=row[5], lease_token=row[6], lease_expires_at=row[7],
        )

    @staticmethod
    def _lock_action_binding(cursor: Any, *, game_id: UUID, player_id: UUID | None,
                             window_id: UUID, job_kind: str, state_version: int,
                             now: datetime) -> tuple | None:
        """현재 AI 차례·버전·미제출을 확인하고 command와 같은 게임 잠금을 먼저 잡는다."""

        cursor.execute(
            """
            SELECT g.state_version FROM public.games AS g
            WHERE g.id = %s AND g.status = 'IN_PROGRESS'
            FOR UPDATE
            """, (game_id,),
        )
        game = cursor.fetchone()
        if game is None:
            return None
        if job_kind == "VOTE":
            if not PostgresActionRepository.vote_version_is_current(
                cursor, game_id=game_id, window_id=window_id, expected=state_version, current=game[0],
            ):
                return None
        elif game[0] != state_version:
            return None
        cursor.execute(
            """
            SELECT w.deadline_at
            FROM public.action_windows AS w
            JOIN public.games AS g ON g.id = w.game_id AND g.phase = w.phase
            WHERE w.game_id = %s AND w.id = %s AND w.status = 'OPEN'
              AND (w.window_kind = 'SPEECH' OR w.deadline_at > %s)
              AND ((%s = 'SPEECH' AND w.window_kind = 'SPEECH' AND w.turn_player_id = %s)
                OR (%s = 'NIGHT_ACTION' AND w.window_kind = 'NIGHT')
                OR (%s = 'VOTE' AND w.window_kind IN ('VOTE', 'REVOTE', 'FINAL_VOTE'))
                OR (%s = 'GM_NARRATION' AND %s::uuid IS NULL))
              AND (%s::uuid IS NULL OR EXISTS (
                  SELECT 1 FROM public.game_players AS p
                  WHERE p.game_id = w.game_id AND p.id = %s AND p.kind = 'AI' AND p.alive = TRUE))
              AND NOT EXISTS (
                  SELECT 1 FROM public.action_submissions AS s
                  WHERE s.game_id = w.game_id AND s.window_id = w.id AND s.actor_player_id = %s)
            FOR UPDATE OF w
            """,
            (game_id, window_id, now, job_kind, player_id, job_kind, job_kind, job_kind,
             player_id, player_id, player_id, player_id),
        )
        return cursor.fetchone()

    def release_unapplied_job(self, reservation: AgentReservation, *, now: datetime | None = None) -> bool:
        """실패한 적용 시도만 현재 token으로 반환하며 저장 proposal과 terminal 의미는 보존한다.

        반환 도중 DB가 끊겨도 원래 lease 만료가 같은 복구 경로를 연다. 이미 저장된
        행동이나 새 worker의 token은 건드리지 않고 다음 예약에서 binding을 다시 검증한다.
        """

        def release(cursor: Any) -> bool:
            cursor.execute(
                """
                UPDATE agent_jobs AS j SET lease_expires_at = LEAST(j.lease_expires_at, %s)
                WHERE j.id = %s AND j.lease_token = %s AND j.game_id = %s
                  AND j.window_id = %s AND j.reserved_state_version = %s
                  AND j.status IN ('SUCCEEDED', 'FALLBACK')
                  AND NOT EXISTS (
                    SELECT 1 FROM public.action_submissions AS s
                    WHERE s.game_id = j.game_id AND s.window_id = j.window_id
                      AND s.actor_player_id = j.player_id)
                RETURNING j.id
                """,
                (now or datetime.now(UTC), reservation.job_id, reservation.lease_token,
                 reservation.game_id, reservation.window_id, reservation.state_version),
            )
            return cursor.fetchone() is not None

        return self._run_transaction(release)

    def issue_capability(
        self,
        reservation: AgentReservation,
        *,
        subject_type: str,
        phase: str,
        allowed_resources: list[str],
        allowed_tools: list[str],
        now: datetime | None = None,
    ) -> CapabilityGrant:
        """32-byte opaque token을 발급하고 token hash만 DB에 저장한다."""

        return self._run_transaction(
            lambda cursor: self._issue_capability(
                cursor,
                reservation,
                subject_type=subject_type,
                phase=phase,
                allowed_resources=allowed_resources,
                allowed_tools=allowed_tools,
                now=now,
            )
        )

    def _issue_capability(
        self,
        cursor: Any,
        reservation: AgentReservation,
        *,
        subject_type: str,
        phase: str,
        allowed_resources: list[str],
        allowed_tools: list[str],
        now: datetime | None,
    ) -> CapabilityGrant:
        """capability INSERT를 실행하는 내부 cursor 버전이다."""

        current = now or datetime.now(UTC)
        raw = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw.encode("ascii")).hexdigest()
        expires = min(
            current + timedelta(seconds=self.MAX_CAPABILITY_SECONDS),
            reservation.lease_expires_at,
        )
        cursor.execute(
            """
            INSERT INTO agent_capabilities (
                token_hash, game_id, subject_type, subject_player_id, phase,
                state_version, window_id, allowed_resources, allowed_tools,
                expires_at, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                token_hash, reservation.game_id, subject_type, reservation.player_id,
                phase, reservation.state_version, reservation.window_id,
                Jsonb(allowed_resources), Jsonb(allowed_tools), expires, current,
            ),
        )
        return CapabilityGrant(raw_token=raw, token_hash=token_hash, expires_at=expires)

    def complete_job(
        self,
        reservation: AgentReservation,
        *,
        status: str,
        normalized_proposal: dict[str, Any] | None,
        failure_code: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        """lease token과 만료 시각을 함께 검사해 늦은 결과를 차단한다."""

        return self._run_transaction(
            lambda cursor: self._complete_job(
                cursor,
                reservation,
                status=status,
                normalized_proposal=normalized_proposal,
                failure_code=failure_code,
                now=now,
            )
        )

    def _complete_job(
        self,
        cursor: Any,
        reservation: AgentReservation,
        *,
        status: str,
        normalized_proposal: dict[str, Any] | None,
        failure_code: str | None,
        now: datetime | None,
    ) -> bool:
        """job UPDATE를 실행하는 내부 cursor 버전이다."""

        completed_at = now or datetime.now(UTC)
        if self._lock_action_binding(cursor, game_id=reservation.game_id, player_id=reservation.player_id,
                                     window_id=reservation.window_id, job_kind=reservation.job_kind,
                                     state_version=reservation.state_version, now=completed_at) is None:
            return False
        cursor.execute(
            """
            UPDATE agent_jobs
            SET status = %s, normalized_proposal = %s, failure_code = %s,
                completed_at = %s
            WHERE id = %s AND lease_token = %s AND status = 'RESERVED'
              AND lease_expires_at > %s
              AND game_id = %s AND window_id = %s AND reserved_state_version = %s
              AND player_id IS NOT DISTINCT FROM %s AND job_kind = %s
            RETURNING id
            """,
            (
                status, Jsonb(normalized_proposal) if normalized_proposal is not None else None,
                failure_code,
                completed_at,
                reservation.job_id,
                reservation.lease_token,
                completed_at,
                reservation.game_id,
                reservation.window_id,
                reservation.state_version,
                reservation.player_id,
                reservation.job_kind,
            ),
        )
        return cursor.fetchone() is not None

    def revoke_capability(self, token_hash: str, *, now: datetime | None = None) -> None:
        """job 종료 시 capability를 폐기한다. raw token은 SQL에 전달하지 않는다."""

        self._run_transaction(
            lambda cursor: self._revoke_capability(cursor, token_hash, now=now)
        )

    def _revoke_capability(
        self, cursor: Any, token_hash: str, *, now: datetime | None = None
    ) -> None:
        """capability UPDATE를 실행하는 내부 cursor 버전이다."""

        cursor.execute(
            """
            UPDATE agent_capabilities
            SET revoked_at = %s
            WHERE token_hash = %s AND revoked_at IS NULL
            """,
            (now or datetime.now(UTC), token_hash),
        )

    def find_capability(self, token_hash: str) -> CapabilityRecord | None:
        """token hash에 연결된 capability와 RESERVED job 메타데이터를 조회한다.

        현재 저장소 migration에는 capability의 job FK가 없으므로 game·window·
        subject·예약 version을 함께 맞춰 가장 최근 job을 연결한다. 향후 정본
        schema에 agent_job_id가 추가되면 이 조회의 join을 직접 FK로 좁힌다.
        """

        return self._run_transaction(lambda cursor: self._find_capability(cursor, token_hash))

    def _find_capability(self, cursor: Any, token_hash: str) -> CapabilityRecord | None:
        """capability 조회 SQL과 tuple row 변환을 담당한다."""

        cursor.execute(
            """
            SELECT c.token_hash, j.id, c.game_id, c.subject_type,
                   c.subject_player_id, c.phase, c.state_version, c.window_id,
                   c.allowed_resources, c.allowed_tools, c.expires_at, c.revoked_at,
                   j.status, j.lease_expires_at
            FROM public.agent_capabilities AS c
            LEFT JOIN public.agent_jobs AS j
              ON j.game_id = c.game_id
             AND j.window_id = c.window_id
             AND j.reserved_state_version = c.state_version
             AND (
                   (c.subject_type = 'AI_PLAYER' AND j.player_id = c.subject_player_id)
                   OR (c.subject_type = 'GM' AND j.player_id IS NULL)
                 )
            WHERE c.token_hash = %s
            ORDER BY j.created_at DESC NULLS LAST
            LIMIT 1
            """,
            (token_hash,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return CapabilityRecord(
            token_hash=row[0],
            job_id=row[1],
            game_id=row[2],
            subject_type=row[3],
            subject_player_id=row[4],
            phase=row[5],
            state_version=int(row[6]),
            window_id=row[7],
            allowed_resources=tuple(row[8]),
            allowed_tools=tuple(row[9]),
            expires_at=row[10],
            revoked_at=row[11],
            job_status=row[12],
            job_lease_expires_at=row[13],
        )
