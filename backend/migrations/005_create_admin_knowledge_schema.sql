-- 관리자 운영 에이전트가 조회할 승인 자료와 검색용 청크를 저장한다.
-- 질문 API는 이 테이블을 읽기만 하며, 색인 입력은 별도 운영 명령으로 수행한다.
-- 개인정보·비밀값·private game 정보는 애플리케이션 정제기를 통과한 값만
-- 삽입해야 한다. migration 자체는 자료 원문이나 실제 자격증명을 넣지 않는다.
BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS public.admin_knowledge_documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type varchar(32) NOT NULL,
    source_id varchar(160) NOT NULL,
    title varchar(240) NOT NULL,
    document_version varchar(64) NOT NULL,
    visibility varchar(32) NOT NULL DEFAULT 'ADMIN_APPROVED',
    feedback_rating smallint,
    content_hash char(64) NOT NULL,
    approved_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT admin_knowledge_documents_source_type_check CHECK (
        source_type IN ('FEEDBACK', 'GAME_SUMMARY', 'OPERATIONS_DOC')
    ),
    CONSTRAINT admin_knowledge_documents_source_id_not_blank CHECK (btrim(source_id) <> ''),
    CONSTRAINT admin_knowledge_documents_title_not_blank CHECK (btrim(title) <> ''),
    CONSTRAINT admin_knowledge_documents_visibility_check CHECK (
        visibility IN ('ADMIN_APPROVED', 'REVOKED')
    ),
    CONSTRAINT admin_knowledge_documents_rating_check CHECK (
        feedback_rating IS NULL OR feedback_rating BETWEEN 1 AND 5
    ),
    CONSTRAINT admin_knowledge_documents_hash_check CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT admin_knowledge_documents_approved_source_check CHECK (
        (source_type = 'FEEDBACK' AND feedback_rating IS NOT NULL)
        OR (source_type <> 'FEEDBACK' AND feedback_rating IS NULL)
    ),
    CONSTRAINT admin_knowledge_documents_unique_version
        UNIQUE (source_type, source_id, document_version)
);

CREATE TABLE IF NOT EXISTS public.admin_knowledge_chunks (
    id bigserial PRIMARY KEY,
    document_id uuid NOT NULL
        REFERENCES public.admin_knowledge_documents (id) ON DELETE CASCADE,
    chunk_index integer NOT NULL,
    content text NOT NULL,
    content_tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED,
    embedding vector(64) NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT admin_knowledge_chunks_index_check CHECK (chunk_index >= 0),
    CONSTRAINT admin_knowledge_chunks_content_check CHECK (
        char_length(btrim(content)) BETWEEN 1 AND 500
    ),
    CONSTRAINT admin_knowledge_chunks_metadata_object CHECK (
        jsonb_typeof(metadata) = 'object'
    ),
    CONSTRAINT admin_knowledge_chunks_unique_index UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_admin_knowledge_documents_visible
    ON public.admin_knowledge_documents (visibility, source_type, approved_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_knowledge_documents_rating
    ON public.admin_knowledge_documents (feedback_rating, approved_at DESC)
    WHERE source_type = 'FEEDBACK';
CREATE INDEX IF NOT EXISTS idx_admin_knowledge_chunks_tsv
    ON public.admin_knowledge_chunks USING gin (content_tsv);
CREATE INDEX IF NOT EXISTS idx_admin_knowledge_chunks_embedding
    ON public.admin_knowledge_chunks USING hnsw (embedding vector_cosine_ops);

COMMIT;
