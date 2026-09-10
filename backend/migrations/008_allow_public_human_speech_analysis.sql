-- 006 적용 이후 공개 사람 발언도 허용하되 기존 원문·근거·벡터 검증은 보존한다.
-- 함수만 교체하므로 재실행해도 게임 원장·기존 결과·버전 활성 시각을 변경하지 않는다.
BEGIN;
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
      ON p.game_id = e.game_id AND p.id = NEW.player_id AND p.kind IN ('HUMAN', 'AI')
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
COMMIT;
