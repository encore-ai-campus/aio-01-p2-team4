"""사람·AI의 확정 공개 발언 분석을 게임 진행 transaction과 분리해 저장한다."""

from __future__ import annotations

from contextlib import contextmanager
import math
import re
from typing import Any
from uuid import UUID, uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from backend.app.infrastructure.transaction import TransactionManager


# 탐색과 투표 준비 판정이 같은 원본 경계를 사용해야 미등록 발언을 놓치지 않는다.
_PUBLIC_SPEECH_SOURCE_SQL = """
                FROM public.game_events e
                JOIN public.games g ON g.id = e.game_id
                JOIN public.game_players p ON p.game_id = e.game_id
                    AND p.id::text = e.payload->>'player_id' AND p.kind IN ('HUMAN', 'AI')
                JOIN LATERAL (
                    SELECT se.payload FROM public.game_events se
                    WHERE se.game_id = e.game_id AND se.sequence < e.sequence
                      AND se.audience = 'PUBLIC' AND se.operation_type = 'SET_ACTION_WINDOW'
                    ORDER BY se.sequence DESC LIMIT 1
                ) s ON true
                JOIN public.action_windows w ON w.game_id = e.game_id
                    AND w.id::text = s.payload->>'window_id' AND w.window_kind = 'SPEECH'
                WHERE e.audience = 'PUBLIC' AND e.event_type = 'PLAYER_SPOKE'
                  AND e.audience_player_id IS NULL AND e.schema_version = 1
                  AND e.operation_type = 'APPEND_PUBLIC_EVENT'
                  AND jsonb_typeof(e.payload->'message') = 'string'
                  AND btrim(e.payload->>'message') <> ''
                  AND length(e.payload->>'message') BETWEEN 1 AND 200
                  AND w.phase IN ('DAY_DISCUSSION', 'FINAL_DISCUSSION')
"""


class PostgresSpeechAnalysisRepository:
    """단계별 짧은 transaction과 만료 시각 검증으로 늦은 Provider 결과를 차단한다."""

    def __init__(self, transactions: TransactionManager) -> None:
        self._transactions = transactions

    @contextmanager
    def _cursor(self):
        """연결을 메서드 안에서 닫아 외부 모델 호출 동안 잠금이 남지 않게 한다."""
        with self._transactions.transaction() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                yield cursor

    def discover(self, *, analysis_version: str, embedding_model: str, dimensions: int,
                 claims_model: str, game_id: UUID | None = None, limit: int = 500) -> int:
        """미등록 발언을 찾고 추적 중 종료한 게임의 마지막 발언도 빠짐없이 등록한다.

        버전 활성화 이후 변경된 게임은 첫 분석 전에 종료해도 원문 전체를 찾는다.
        활성화 이전 미추적 종료 게임은 game_id를 명시할 때만 역채움한다.
        """
        for value, maximum in ((analysis_version, 256), (embedding_model, 128), (claims_model, 128)):
            if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum:
                raise ValueError("분석 모델과 버전이 올바르지 않습니다.")
        if type(dimensions) is not int or not 1 <= dimensions <= 4096:
            raise ValueError("임베딩 차원이 올바르지 않습니다.")
        if type(limit) is not int or not 1 <= limit <= 5000:
            raise ValueError("탐색 크기가 올바르지 않습니다.")
        with self._cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (analysis_version,))
            cursor.execute("""
                INSERT INTO public.speech_analysis_versions
                    (analysis_version, embedding_model, dimensions, claims_model)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (analysis_version) DO NOTHING
            """, (analysis_version, embedding_model, dimensions, claims_model))
            # 같은 버전의 차원·모델 혼합은 조회와 재시작의 의미를 바꾸므로 거부한다.
            cursor.execute("""
                SELECT 1 FROM public.speech_analysis_versions
                WHERE analysis_version = %s AND
                    (embedding_model <> %s OR dimensions <> %s OR claims_model <> %s)
                LIMIT 1
            """, (analysis_version, embedding_model, dimensions, claims_model))
            if cursor.fetchone() is not None:
                raise ValueError("기존 분석 버전의 모델 계약과 일치하지 않습니다.")
            cursor.execute(f"""
                INSERT INTO public.speech_analysis (
                    game_id, event_id, player_id, source_sequence, discussion_segment,
                    round, content_hash, analysis_version, embedding_model, dimensions, claims_model
                )
                SELECT e.game_id, e.id, p.id, e.sequence,
                       w.phase || ':' || w.round::text, w.round,
                       encode(public.digest(convert_to(e.payload->>'message', 'UTF8'), 'sha256'), 'hex'),
                       %s, %s, %s, %s
                {_PUBLIC_SPEECH_SOURCE_SQL}
                  AND ((%s::uuid IS NULL AND (g.status IN ('IN_PROGRESS','SAVED')
                       OR EXISTS (SELECT 1 FROM public.speech_analysis tracked
                                  WHERE tracked.game_id = g.id AND tracked.analysis_version = %s)
                       OR EXISTS (SELECT 1 FROM public.speech_analysis_versions v
                                  WHERE v.analysis_version = %s AND
                                    (g.updated_at >= v.activated_at OR EXISTS (
                                        SELECT 1 FROM public.game_events recent
                                        WHERE recent.game_id = g.id AND recent.audience = 'PUBLIC'
                                          AND recent.event_type = 'PLAYER_SPOKE'
                                          AND recent.operation_type = 'APPEND_PUBLIC_EVENT'
                                          AND recent.schema_version = 1
                                          AND recent.created_at >= v.activated_at)))))
                       OR g.id = %s)
                  AND NOT EXISTS (SELECT 1 FROM public.speech_analysis a
                                  WHERE a.event_id = e.id AND a.analysis_version = %s)
                ORDER BY e.created_at, e.game_id, e.sequence
                LIMIT %s ON CONFLICT (event_id, analysis_version) DO NOTHING
                RETURNING id
            """, (analysis_version, embedding_model, dimensions, claims_model,
                  game_id, analysis_version, analysis_version, game_id, analysis_version, limit))
            return len(cursor.fetchall())

    @staticmethod
    def _recover_expired(cursor: Any, *, analysis_version: str, max_attempts: int) -> None:
        """모델 호출 없이 만료된 선점을 회수하고 소진된 단계의 실패를 확정한다."""
        # 마지막 허용 선점이 crash로 끝나도 미완료 상태가 영구 PENDING으로 남지 않게 한다.
        # 잠근 소량의 만료 행만 회수하고 현재 token을 다시 비교하여 새 worker를 보호한다.
        cursor.execute("""
            WITH expired AS (
                SELECT id, lease_token, lease_stage FROM public.speech_analysis
                WHERE analysis_version = %s AND lease_token IS NOT NULL
                  AND lease_expires_at <= clock_timestamp()
                ORDER BY lease_expires_at, id FOR UPDATE SKIP LOCKED LIMIT 100
            )
            UPDATE public.speech_analysis a SET
                embedding_status = CASE WHEN a.lease_stage = 'EMBEDDING'
                    AND a.embedding_status <> 'READY' AND a.embedding_attempts >= %s
                    THEN 'FAILED' ELSE a.embedding_status END,
                embedding_failure_code = CASE WHEN a.lease_stage = 'EMBEDDING'
                    AND a.embedding_status <> 'READY' AND a.embedding_attempts >= %s
                    THEN 'LEASE_EXPIRED' ELSE a.embedding_failure_code END,
                claims_status = CASE WHEN a.lease_stage = 'CLAIMS'
                    AND a.claims_status <> 'READY' AND a.claims_attempts >= %s
                    THEN 'FAILED' ELSE a.claims_status END,
                claims_failure_code = CASE WHEN a.lease_stage = 'CLAIMS'
                    AND a.claims_status <> 'READY' AND a.claims_attempts >= %s
                    THEN 'LEASE_EXPIRED' ELSE a.claims_failure_code END,
                lease_token = NULL, lease_expires_at = NULL, lease_stage = NULL,
                updated_at = clock_timestamp()
            FROM expired x WHERE a.id = x.id AND a.lease_token = x.lease_token
              AND a.lease_stage = x.lease_stage AND a.analysis_version = %s
              AND a.lease_expires_at <= clock_timestamp()
        """, (analysis_version, max_attempts, max_attempts, max_attempts, max_attempts,
              analysis_version))

    def claim_next(self, *, analysis_version: str, lease_seconds: int = 60,
                   max_attempts: int = 3, game_id: UUID | None = None) -> dict[str, Any] | None:
        """진행 게임의 확정 발언을 현재 행동 창과 무관하게 한 단계씩 선점한다.

        원문의 토론 소속은 등록 시 검증하므로 밤·투표로 넘어가도 누적 작업을 처리한다.
        저장·종료 상태에서는 새 선점을 멈추되 이미 선점한 결과의 저장은 유효 lease로
        판정한다. 게임 행을 잠그거나 원장을 쓰지 않고 Provider에는 공개 입력만 준다.
        """
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 600:
            raise ValueError("선점 시간이 올바르지 않습니다.")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 20:
            raise ValueError("재시도 상한이 올바르지 않습니다.")
        with self._cursor() as cursor:
            self._recover_expired(cursor, analysis_version=analysis_version, max_attempts=max_attempts)
            cursor.execute("""
                WITH candidate AS (
                    SELECT id, CASE WHEN embedding_status <> 'READY' AND embedding_attempts < %s
                                      AND embedding_retry_at <= clock_timestamp() THEN 'EMBEDDING'
                                    ELSE 'CLAIMS' END AS stage
                    FROM public.speech_analysis
                    WHERE analysis_version = %s
                      AND (%s::uuid IS NULL OR game_id = %s)
                      AND EXISTS (
                          SELECT 1 FROM public.games g
                          WHERE g.id = speech_analysis.game_id AND g.status = 'IN_PROGRESS'
                      )
                      AND lease_token IS NULL
                      AND ((embedding_status <> 'READY' AND embedding_attempts < %s
                            AND embedding_retry_at <= clock_timestamp())
                           OR (claims_status <> 'READY'
                               AND claims_attempts < %s AND claims_retry_at <= clock_timestamp()))
                    ORDER BY created_at, id FOR UPDATE SKIP LOCKED LIMIT 1
                )
                UPDATE public.speech_analysis a SET
                    lease_token = %s, lease_expires_at = clock_timestamp() + %s * interval '1 second',
                    lease_stage = c.stage,
                    embedding_attempts = embedding_attempts + CASE WHEN c.stage = 'EMBEDDING' THEN 1 ELSE 0 END,
                    claims_attempts = claims_attempts + CASE WHEN c.stage = 'CLAIMS' THEN 1 ELSE 0 END,
                    updated_at = clock_timestamp()
                FROM candidate c WHERE a.id = c.id
                RETURNING a.id AS job_id, a.lease_token, a.lease_stage AS stage, a.game_id, a.event_id
            """, (max_attempts, analysis_version, game_id, game_id, max_attempts, max_attempts, uuid4(), lease_seconds))
            row = cursor.fetchone()
            if row is None:
                return None
            cursor.execute("""
                SELECT payload->>'message' AS message FROM public.game_events
                WHERE game_id = %s AND id = %s AND audience = 'PUBLIC' AND event_type = 'PLAYER_SPOKE'
                  AND audience_player_id IS NULL AND schema_version = 1
                  AND operation_type = 'APPEND_PUBLIC_EVENT'
            """, (row['game_id'], row['event_id']))
            source = cursor.fetchone()
            if source is None:
                raise ValueError("공개 발언 원본이 없습니다.")
            cursor.execute("""
                SELECT id AS player_id, display_name, seat, kind FROM public.game_players
                WHERE game_id = %s ORDER BY seat
            """, (row['game_id'],))
            return {"job_id": row['job_id'], "lease_token": row['lease_token'], "stage": row['stage'],
                    "message": source['message'], "players": [dict(p) for p in cursor.fetchall()]}

    def prepare_for_vote(self, *, game_id: UUID, analysis_version: str,
                         embedding_model: str, dimensions: int, claims_model: str,
                         max_attempts: int) -> bool:
        """누적 발언의 양 단계가 완료 또는 재시도 소진일 때만 투표 준비를 허용한다.

        탐색과 판정은 각각 짧은 transaction으로 끝낸다. 게임 원장을 잠그거나 쓰지
        않으며, 호출자는 마감된 토론을 확인하고 실제 투표 전환 때 다시 검증해야 한다.
        탐색 상한에 도달해도 남은 원문을 직접 조회하므로 일부 등록을 완료로 오인하지 않는다.
        """
        if game_id is None:
            raise ValueError("투표 준비 대상 게임이 필요합니다.")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 20:
            raise ValueError("재시도 상한이 올바르지 않습니다.")
        self.discover(game_id=game_id, analysis_version=analysis_version,
                      embedding_model=embedding_model, dimensions=dimensions,
                      claims_model=claims_model, limit=5000)
        with self._cursor() as cursor:
            self._recover_expired(cursor, analysis_version=analysis_version, max_attempts=max_attempts)
            cursor.execute(f"""
                SELECT NOT EXISTS (
                    SELECT 1 {_PUBLIC_SPEECH_SOURCE_SQL}
                      AND e.game_id = %s
                      AND NOT EXISTS (
                          SELECT 1 FROM public.speech_analysis a
                          WHERE a.event_id = e.id AND a.analysis_version = %s)
                ) AND NOT EXISTS (
                    SELECT 1 FROM public.speech_analysis a
                    WHERE a.game_id = %s AND a.analysis_version = %s
                      AND (
                          (a.lease_token IS NOT NULL AND a.lease_expires_at > clock_timestamp())
                          OR NOT (a.embedding_status = 'READY' OR
                              (a.embedding_status = 'FAILED' AND a.embedding_attempts >= %s))
                          OR NOT (a.claims_status = 'READY' OR
                              (a.claims_status = 'FAILED' AND a.claims_attempts >= %s))
                      )
                ) AS ready
            """, (game_id, analysis_version, game_id, analysis_version, max_attempts, max_attempts))
            return bool(cursor.fetchone()['ready'])

    @staticmethod
    def _vector(embedding: Any, dimensions: int) -> list[float]:
        """잘못된 외부 수치가 DB 또는 cosine 계산에 진입하기 전에 거부한다."""
        if not isinstance(embedding, (list, tuple)) or len(embedding) != dimensions:
            raise ValueError("임베딩 차원이 일치하지 않습니다.")
        if any(type(v) not in (float, int) for v in embedding):
            raise ValueError("임베딩 원소는 유한수여야 합니다.")
        try:
            vector = [float(v) for v in embedding]
        except (OverflowError, ValueError) as exc:
            raise ValueError("임베딩 원소는 유한수여야 합니다.") from exc
        if not all(math.isfinite(v) for v in vector) or not any(v != 0 for v in vector):
            raise ValueError("유한한 비영벡터만 저장할 수 있습니다.")
        return vector

    def _binding(self, cursor: Any, job_id: UUID, lease_token: UUID, stage: str):
        """행 잠금 뒤에도 완료 UPDATE에서 실제 현재 시각을 다시 검사한다."""
        cursor.execute("""
            SELECT a.dimensions, a.game_id, e.payload->>'message' AS message
            FROM public.speech_analysis a JOIN public.game_events e
              ON e.game_id = a.game_id AND e.id = a.event_id
            WHERE a.id = %s AND a.lease_token = %s AND a.lease_stage = %s
              AND a.lease_expires_at > clock_timestamp()
            FOR UPDATE OF a
        """, (job_id, lease_token, stage))
        return cursor.fetchone()

    def complete_embedding(self, *, job_id: UUID, lease_token: UUID, embedding: Any) -> bool:
        """유효한 현재 선점만 완료하며 claims 단계는 별도 선점으로 처리한다."""
        with self._cursor() as cursor:
            row = self._binding(cursor, job_id, lease_token, 'EMBEDDING')
            if row is None:
                return False
            vector = self._vector(embedding, row['dimensions'])
            cursor.execute("""
                UPDATE public.speech_analysis SET embedding = %s, embedding_status = 'READY',
                    embedding_failure_code = NULL, lease_token = NULL, lease_expires_at = NULL,
                    lease_stage = NULL, updated_at = clock_timestamp()
                WHERE id = %s AND lease_token = %s AND lease_stage = 'EMBEDDING'
                  AND lease_expires_at > clock_timestamp() AND embedding_status <> 'READY'
                RETURNING id
            """, (vector, job_id, lease_token))
            return cursor.fetchone() is not None

    @staticmethod
    def _claims(claims: Any, message: str, player_ids: set[str]) -> list[dict[str, Any]]:
        """폐쇄형 구조와 같은 게임 대상·Unicode 원문 근거를 검사한다."""
        fields = {'target_player_id', 'stance', 'proposition', 'evidence_start', 'evidence_end', 'quote'}
        if not isinstance(claims, list) or len(claims) > 32:
            raise ValueError("주장 배열이 올바르지 않습니다.")
        for item in claims:
            if not isinstance(item, dict) or set(item) != fields:
                raise ValueError("주장 필드가 올바르지 않습니다.")
            if item['target_player_id'] is not None and (not isinstance(item['target_player_id'], str) or item['target_player_id'] not in player_ids):
                raise ValueError("주장 대상은 같은 게임 player여야 합니다.")
            if not isinstance(item['stance'], str) or item['stance'] not in {'SUSPICION', 'DEFENSE', 'QUESTION', 'NEUTRAL'}:
                raise ValueError("주장 입장이 올바르지 않습니다.")
            if not isinstance(item['proposition'], str) or not 1 <= len(item['proposition'].strip()) <= 500:
                raise ValueError("주장 문장이 올바르지 않습니다.")
            start, end = item['evidence_start'], item['evidence_end']
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(message):
                raise ValueError("주장 근거 범위가 올바르지 않습니다.")
            if not isinstance(item['quote'], str) or item['quote'] != message[start:end]:
                raise ValueError("주장 인용이 원문과 일치하지 않습니다.")
        return claims

    def complete_claims(self, *, job_id: UUID, lease_token: UUID, claims: Any) -> bool:
        """주장 검증 실패가 이미 완료한 임베딩을 지우지 않도록 별도 저장한다."""
        with self._cursor() as cursor:
            row = self._binding(cursor, job_id, lease_token, 'CLAIMS')
            if row is None:
                return False
            cursor.execute('SELECT id FROM public.game_players WHERE game_id = %s', (row['game_id'],))
            validated = self._claims(claims, row['message'], {str(p['id']) for p in cursor.fetchall()})
            cursor.execute("""
                UPDATE public.speech_analysis SET claims = %s, claims_status = 'READY',
                    claims_failure_code = NULL, lease_token = NULL, lease_expires_at = NULL,
                    lease_stage = NULL, updated_at = clock_timestamp()
                WHERE id = %s AND lease_token = %s AND lease_stage = 'CLAIMS'
                  AND lease_expires_at > clock_timestamp()
                  AND claims_status <> 'READY' RETURNING id
            """, (Jsonb(validated), job_id, lease_token))
            return cursor.fetchone() is not None

    def fail(self, *, job_id: UUID, lease_token: UUID, stage: str,
             failure_code: str, retry_seconds: int = 30) -> bool:
        """외부 오류 원문 대신 제한된 코드만 저장하며 해당 단계만 재시도한다."""
        if stage not in ('EMBEDDING', 'CLAIMS'):
            raise ValueError("분석 단계가 올바르지 않습니다.")
        if not isinstance(failure_code, str) or re.fullmatch(r'[A-Z][A-Z0-9_]{0,63}', failure_code) is None:
            raise ValueError("실패 코드가 올바르지 않습니다.")
        if type(retry_seconds) is not int or not 0 <= retry_seconds <= 86400:
            raise ValueError("재시도 대기 시간이 올바르지 않습니다.")
        prefix = stage.lower()
        with self._cursor() as cursor:
            # 동적 식별자는 위 폐쇄형 단계 검사만 통과한 상수에서 만든다.
            cursor.execute(f"""
                UPDATE public.speech_analysis SET {prefix}_status = 'FAILED',
                    {prefix}_failure_code = %s,
                    {prefix}_retry_at = clock_timestamp() + %s * interval '1 second',
                    lease_token = NULL, lease_expires_at = NULL, lease_stage = NULL,
                    updated_at = clock_timestamp()
                WHERE id = %s AND lease_token = %s AND lease_stage = %s
                  AND lease_expires_at > clock_timestamp() AND {prefix}_status <> 'READY'
                RETURNING id
            """, (failure_code, retry_seconds, job_id, lease_token, stage))
            return cursor.fetchone() is not None
