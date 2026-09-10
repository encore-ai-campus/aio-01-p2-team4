"""승인된 운영 자료를 관리자 RAG 검색 테이블에 색인하는 수동 명령."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

import psycopg
from psycopg.rows import dict_row

from backend.app.core.config import get_settings
from backend.app.services.admin_knowledge import (
    local_embedding,
    sanitize_knowledge_text,
    split_knowledge_chunks,
)


@dataclass(frozen=True, slots=True)
class KnowledgeDocument:
    """정제 후 색인할 승인 자료의 최소 공개 모델."""

    source_type: str
    source_id: str
    title: str
    document_version: str
    content: str
    approved_at: datetime
    feedback_rating: int | None = None


APPROVED_OPERATION_DOCUMENTS = (
    KnowledgeDocument(
        source_type="OPERATIONS_DOC",
        source_id="admin-api-v1",
        title="관리자 API 운영 계약",
        document_version="2026-09-07",
        content=(
            "관리자 API는 UUID allowlist를 통과한 read-only 조회만 허용한다. "
            "운영 지표, 직업별 승률, 페르소나별 승률, 사용자 피드백, 감사 로그를 제공한다. "
            "역할·개인 사실·개별 행동·투표·seed·private context는 응답하지 않는다."
        ),
        approved_at=datetime(2026, 9, 7, tzinfo=UTC),
    ),
    KnowledgeDocument(
        source_type="OPERATIONS_DOC",
        source_id="admin-screen-flow-v1",
        title="관리자 화면 흐름",
        document_version="2026-09-07",
        content=(
            "관리자 센터는 운영 분석, 사용자 피드백, 관리자 로그, 운영 에이전트 계획으로 구성한다. "
            "운영 분석에는 KPI와 진영별 승률 및 페르소나 승률을 표시한다. "
            "피드백과 로그는 별도 화면에서 필터와 페이지로 확인한다."
        ),
        approved_at=datetime(2026, 9, 7, tzinfo=UTC),
    ),
    KnowledgeDocument(
        source_type="OPERATIONS_DOC",
        source_id="admin-agent-plan-v1",
        title="관리자 운영 에이전트 계획",
        document_version="2026-09-07",
        content=(
            "운영 에이전트는 승인된 피드백, 공개 게임 요약, 운영 문서를 검색한다. "
            "키워드 검색과 pgvector 유사도 검색을 함께 사용하고 답변·근거·신뢰도를 반환한다. "
            "모든 질문을 감사 로그에 남기며 데이터 변경·삭제·강제 종료 자동 조치는 차단한다."
        ),
        approved_at=datetime(2026, 9, 7, tzinfo=UTC),
    ),
)


def _document_hash(content: str) -> str:
    """정제된 문서 내용의 변경 감지용 SHA-256을 계산한다."""

    return sha256(content.encode("utf-8")).hexdigest()


def _load_database_documents(connection: Any) -> list[KnowledgeDocument]:
    """현재 DB에서 공개 피드백과 종료 게임의 요약만 읽어 색인 대상으로 만든다."""

    documents = list(APPROVED_OPERATION_DOCUMENTS)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, feedback_type, rating, comment, created_at
            FROM public.feedback
            WHERE comment IS NOT NULL AND btrim(comment) <> ''
            ORDER BY created_at, id
            """
        )
        for row in cursor.fetchall():
            content = sanitize_knowledge_text(
                f"사용자 피드백 유형 {row['feedback_type']}, 평점 {row['rating']}점: {row['comment']}"
            )
            if content:
                documents.append(KnowledgeDocument(
                    source_type="FEEDBACK",
                    source_id=f"feedback:{row['id']}",
                    title="사용자 피드백",
                    document_version="feedback-v1",
                    content=content,
                    approved_at=row["created_at"],
                    feedback_rating=int(row["rating"]),
                ))
        cursor.execute(
            """
            SELECT id, scenario_id, winner, round, finished_at, created_at
            FROM public.games
            WHERE status = 'COMPLETED'
            ORDER BY created_at, id
            """
        )
        for row in cursor.fetchall():
            content = sanitize_knowledge_text(
                "종료 게임 공개 요약: "
                f"시나리오 {row['scenario_id']}, 결과 {row['winner']}, {row['round']}라운드."
            )
            documents.append(KnowledgeDocument(
                source_type="GAME_SUMMARY",
                source_id=f"game:{row['id']}",
                title="종료 게임 공개 요약",
                document_version="game-summary-v1",
                content=content,
                approved_at=row["finished_at"] or row["created_at"],
            ))
    return documents


def _upsert_document(connection: Any, document: KnowledgeDocument) -> int:
    """문서와 청크를 버전별로 재생성해 오래된 색인이 남지 않게 한다."""

    content = sanitize_knowledge_text(document.content)
    content_hash = _document_hash(content)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO public.admin_knowledge_documents (
                source_type, source_id, title, document_version, visibility,
                feedback_rating, content_hash, approved_at
            ) VALUES (%s, %s, %s, %s, 'ADMIN_APPROVED', %s, %s, %s)
            ON CONFLICT (source_type, source_id, document_version) DO UPDATE SET
                title = EXCLUDED.title,
                visibility = EXCLUDED.visibility,
                feedback_rating = EXCLUDED.feedback_rating,
                content_hash = EXCLUDED.content_hash,
                approved_at = EXCLUDED.approved_at,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id
            """,
            [document.source_type, document.source_id, document.title,
             document.document_version, document.feedback_rating, content_hash,
             document.approved_at],
        )
        document_id = cursor.fetchone()["id"]
        cursor.execute(
            "DELETE FROM public.admin_knowledge_chunks WHERE document_id = %s",
            [document_id],
        )
        chunks = split_knowledge_chunks(content)
        for index, chunk in enumerate(chunks):
            cursor.execute(
                """
                INSERT INTO public.admin_knowledge_chunks (document_id, chunk_index, content, embedding)
                VALUES (%s, %s, %s, %s::vector)
                """,
                [document_id, index, chunk, local_embedding(chunk)],
            )
    return len(chunks)


def main() -> None:
    """환경의 PostgreSQL에 승인 자료를 색인하고 처리 건수를 출력한다."""

    settings = get_settings()
    with psycopg.connect(settings.effective_database_url, row_factory=dict_row) as connection:
        documents = _load_database_documents(connection)
        chunk_count = sum(_upsert_document(connection, document) for document in documents)
    print(f"Indexed admin knowledge documents={len(documents)} chunks={chunk_count}")


if __name__ == "__main__":
    main()
