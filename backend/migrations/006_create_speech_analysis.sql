-- 005와 pgvector 없이 공개 발언 원장에 연결된 보조 분석만 추가한다.
BEGIN;
CREATE UNIQUE INDEX IF NOT EXISTS uq_game_events_analysis_source
    ON public.game_events (game_id, id, sequence);

-- 발언이 아직 없어도 버전 활성화 시각을 보존하여 종료 경쟁과 재시작 누락을 막는다.
CREATE TABLE IF NOT EXISTS public.speech_analysis_versions (
    analysis_version text PRIMARY KEY CHECK (length(btrim(analysis_version)) BETWEEN 1 AND 256),
    embedding_model text NOT NULL CHECK (length(btrim(embedding_model)) BETWEEN 1 AND 128),
    dimensions integer NOT NULL CHECK (dimensions BETWEEN 1 AND 4096),
    claims_model text NOT NULL CHECK (length(btrim(claims_model)) BETWEEN 1 AND 128),
    activated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS public.speech_analysis (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id uuid NOT NULL,
    event_id uuid NOT NULL,
    player_id uuid NOT NULL,
    source_sequence bigint NOT NULL,
    discussion_segment text NOT NULL,
    round smallint NOT NULL CHECK (round BETWEEN 0 AND 5),
    content_hash char(64) NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    analysis_version text NOT NULL CHECK (length(btrim(analysis_version)) BETWEEN 1 AND 256),
    embedding_model text NOT NULL CHECK (length(btrim(embedding_model)) BETWEEN 1 AND 128),
    dimensions integer NOT NULL CHECK (dimensions BETWEEN 1 AND 4096),
    claims_model text NOT NULL CHECK (length(btrim(claims_model)) BETWEEN 1 AND 128),
    embedding double precision[],
    claims jsonb,
    embedding_status text NOT NULL DEFAULT 'PENDING' CHECK (embedding_status IN ('PENDING','READY','FAILED')),
    claims_status text NOT NULL DEFAULT 'PENDING' CHECK (claims_status IN ('PENDING','READY','FAILED')),
    embedding_attempts integer NOT NULL DEFAULT 0 CHECK (embedding_attempts >= 0),
    claims_attempts integer NOT NULL DEFAULT 0 CHECK (claims_attempts >= 0),
    embedding_retry_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    claims_retry_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    embedding_failure_code text CHECK (embedding_failure_code ~ '^[A-Z][A-Z0-9_]{0,63}$'),
    claims_failure_code text CHECK (claims_failure_code ~ '^[A-Z][A-Z0-9_]{0,63}$'),
    lease_token uuid,
    lease_expires_at timestamptz,
    lease_stage text CHECK (lease_stage IN ('EMBEDDING','CLAIMS')),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (event_id, analysis_version),
    FOREIGN KEY (game_id, event_id, source_sequence)
        REFERENCES public.game_events (game_id, id, sequence) ON DELETE CASCADE,
    FOREIGN KEY (game_id, player_id)
        REFERENCES public.game_players (game_id, id) ON DELETE CASCADE,
    CHECK (discussion_segment IN ('DAY_DISCUSSION:' || round::text, 'FINAL_DISCUSSION:' || round::text)),
    CHECK ((embedding_status = 'READY') = (embedding IS NOT NULL)),
    CHECK ((claims_status = 'READY') = (claims IS NOT NULL)),
    CHECK ((lease_token IS NULL AND lease_expires_at IS NULL AND lease_stage IS NULL)
        OR (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL AND lease_stage IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_speech_analysis_game_source
    ON public.speech_analysis (game_id, analysis_version, source_sequence);
CREATE INDEX IF NOT EXISTS idx_speech_analysis_pending
    ON public.speech_analysis (analysis_version, lease_expires_at, created_at)
    WHERE embedding_status <> 'READY' OR claims_status <> 'READY';

-- 미적용 006을 격리 환경에서 재실행해도 기존 버전의 최초 추적 시각은 유지한다.
INSERT INTO public.speech_analysis_versions
    (analysis_version, embedding_model, dimensions, claims_model, activated_at)
SELECT DISTINCT ON (analysis_version)
    analysis_version, embedding_model, dimensions, claims_model, created_at
FROM public.speech_analysis ORDER BY analysis_version, created_at, id
ON CONFLICT (analysis_version) DO NOTHING;

-- repository 이외의 쓰기도 같은 공개 원문·벡터·근거 경계를 지키도록 강제한다.
CREATE OR REPLACE FUNCTION public.validate_speech_analysis() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE
    source_message text;
    source_phase text;
    source_round smallint;
    item jsonb;
    start_offset integer;
    end_offset integer;
BEGIN
    IF TG_OP = 'UPDATE' AND
       ROW(NEW.game_id, NEW.event_id, NEW.player_id, NEW.source_sequence,
           NEW.discussion_segment, NEW.round, NEW.content_hash, NEW.analysis_version,
           NEW.embedding_model, NEW.dimensions, NEW.claims_model)
       IS DISTINCT FROM
       ROW(OLD.game_id, OLD.event_id, OLD.player_id, OLD.source_sequence,
           OLD.discussion_segment, OLD.round, OLD.content_hash, OLD.analysis_version,
           OLD.embedding_model, OLD.dimensions, OLD.claims_model) THEN
        RAISE EXCEPTION 'speech_analysis source binding is immutable' USING ERRCODE = '23514';
    END IF;
    SELECT e.payload->>'message', w.phase, w.round
    INTO source_message, source_phase, source_round
    FROM public.game_events e JOIN public.game_players p
      ON p.game_id = e.game_id AND p.id = NEW.player_id AND p.kind = 'AI'
    JOIN LATERAL (
        SELECT se.payload FROM public.game_events se
        WHERE se.game_id = e.game_id AND se.sequence < e.sequence
          AND se.audience = 'PUBLIC' AND se.operation_type = 'SET_ACTION_WINDOW'
        ORDER BY se.sequence DESC LIMIT 1
    ) s ON true
    JOIN public.action_windows w ON w.game_id = e.game_id
      AND w.id::text = s.payload->>'window_id' AND w.window_kind = 'SPEECH'
    WHERE e.game_id = NEW.game_id AND e.id = NEW.event_id AND e.sequence = NEW.source_sequence
      AND e.audience = 'PUBLIC' AND e.event_type = 'PLAYER_SPOKE'
      AND e.audience_player_id IS NULL AND e.schema_version = 1
      AND e.operation_type = 'APPEND_PUBLIC_EVENT'
      AND e.payload->>'player_id' = NEW.player_id::text
      AND jsonb_typeof(e.payload->'message') = 'string';
    IF source_message IS NULL OR btrim(source_message) = ''
       OR length(source_message) NOT BETWEEN 1 AND 200
       OR source_phase NOT IN ('DAY_DISCUSSION', 'FINAL_DISCUSSION')
       OR NEW.round IS DISTINCT FROM source_round
       OR NEW.discussion_segment IS DISTINCT FROM (source_phase || ':' || source_round::text) OR
       NEW.content_hash <> encode(public.digest(convert_to(source_message, 'UTF8'), 'sha256'), 'hex') THEN
        RAISE EXCEPTION 'invalid public AI speech source' USING ERRCODE = '23514';
    END IF;
    IF NEW.embedding IS NOT NULL AND (
        array_ndims(NEW.embedding) IS DISTINCT FROM 1 OR array_lower(NEW.embedding, 1) <> 1
        OR cardinality(NEW.embedding) <> NEW.dimensions
        OR EXISTS (SELECT 1 FROM unnest(NEW.embedding) v WHERE v IS NULL
            OR v IN ('Infinity'::float8, '-Infinity'::float8, 'NaN'::float8))
        OR NOT EXISTS (SELECT 1 FROM unnest(NEW.embedding) v WHERE v <> 0)
    ) THEN
        RAISE EXCEPTION 'invalid speech embedding' USING ERRCODE = '23514';
    END IF;
    IF NEW.claims IS NOT NULL THEN
        IF jsonb_typeof(NEW.claims) <> 'array' THEN
            RAISE EXCEPTION 'claims must be an array' USING ERRCODE = '23514';
        END IF;
        IF jsonb_array_length(NEW.claims) > 32 THEN
            RAISE EXCEPTION 'too many claims' USING ERRCODE = '23514';
        END IF;
        FOR item IN SELECT value FROM jsonb_array_elements(NEW.claims) LOOP
            IF jsonb_typeof(item) <> 'object' THEN
                RAISE EXCEPTION 'invalid claim object' USING ERRCODE = '23514';
            END IF;
            IF NOT (item ?& ARRAY['target_player_id','stance','proposition','evidence_start','evidence_end','quote'])
                OR (item - ARRAY['target_player_id','stance','proposition','evidence_start','evidence_end','quote']) <> '{}'::jsonb
                OR jsonb_typeof(item->'target_player_id') NOT IN ('string','null')
                OR jsonb_typeof(item->'stance') <> 'string'
                OR item->>'stance' NOT IN ('SUSPICION','DEFENSE','QUESTION','NEUTRAL')
                OR jsonb_typeof(item->'proposition') <> 'string'
                OR length(btrim(item->>'proposition')) NOT BETWEEN 1 AND 500
                OR jsonb_typeof(item->'quote') <> 'string'
                OR jsonb_typeof(item->'evidence_start') <> 'number'
                OR jsonb_typeof(item->'evidence_end') <> 'number'
                OR (item->>'evidence_start') !~ '^[0-9]{1,6}$'
                OR (item->>'evidence_end') !~ '^[0-9]{1,6}$' THEN
                RAISE EXCEPTION 'invalid claim shape' USING ERRCODE = '23514';
            END IF;
            start_offset := (item->>'evidence_start')::integer;
            end_offset := (item->>'evidence_end')::integer;
            IF start_offset >= end_offset OR end_offset > length(source_message)
               OR item->>'quote' <> substring(source_message FROM start_offset + 1 FOR end_offset - start_offset)
               OR (item->>'target_player_id' IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.game_players p
                   WHERE p.game_id = NEW.game_id AND p.id::text = item->>'target_player_id')) THEN
                RAISE EXCEPTION 'invalid claim evidence or target' USING ERRCODE = '23514';
            END IF;
        END LOOP;
    END IF;
    RETURN NEW;
END;
$$;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid = 'public.speech_analysis'::regclass
                   AND tgname = 'speech_analysis_validate') THEN
        CREATE TRIGGER speech_analysis_validate BEFORE INSERT OR UPDATE ON public.speech_analysis
            FOR EACH ROW EXECUTE FUNCTION public.validate_speech_analysis();
    END IF;
END $$;
COMMIT;
