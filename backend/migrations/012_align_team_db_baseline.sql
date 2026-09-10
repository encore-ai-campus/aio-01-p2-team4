-- 현재 team DB의 최종 baseline과 새 DB에서 순서대로 migration을 실행한 결과를
-- 일치시킨다. 001·002·005는 과거에 별도로 사용하던 객체를 만드는 파일이므로
-- 기존 migration 파일은 수정하지 않고, 마지막 순방향 migration에서 현재 baseline에
-- 남기지 않는 빈 legacy·선택 확장 객체만 정리한다.
--
-- 다른 환경에 실제 데이터가 남아 있으면 삭제하지 않고 migration 전체를 중단한다.
-- 따라서 이 파일은 데이터 보존 검토가 끝난 빈 객체 또는 처음부터 실행한 새 DB에서만
-- 정리되며, 현재 team DB처럼 대상 객체가 없는 환경에서는 안전한 no-op이 된다.
BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '15s';

DO $migration$
DECLARE
    object_name text;
    relation_kind "char";
    row_count bigint;
BEGIN
    FOREACH object_name IN ARRAY ARRAY[
        'admin_knowledge_chunks',
        'admin_knowledge_documents',
        'scaffold_events',
        'scaffold_operations',
        'scaffold_games'
    ] LOOP
        SELECT c.relkind
        INTO relation_kind
        FROM pg_class AS c
        JOIN pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relname = object_name;

        IF relation_kind IS NULL THEN
            CONTINUE;
        END IF;

        -- 같은 이름의 view·sequence 등을 migration이 오인해 삭제하지 않도록
        -- 대상이 일반 테이블인지 먼저 확인한다.
        IF relation_kind <> 'r' THEN
            RAISE EXCEPTION 'public.% is not a regular table', object_name;
        END IF;

        EXECUTE format('SELECT count(*) FROM public.%I', object_name)
        INTO row_count;
        IF row_count > 0 THEN
            RAISE EXCEPTION
                'public.% contains % row(s); empty-data review is required before cleanup',
                object_name, row_count;
        END IF;
    END LOOP;
END;
$migration$;

-- 자식 테이블을 먼저 제거해 FK 의존성을 보존한다. 데이터가 있는 경우에는
-- 위 검사가 먼저 예외를 발생시켜 이 구문까지 도달하지 않는다.
DROP TABLE IF EXISTS public.admin_knowledge_chunks;
DROP TABLE IF EXISTS public.admin_knowledge_documents;
DROP TABLE IF EXISTS public.scaffold_events;
DROP TABLE IF EXISTS public.scaffold_operations;
DROP TABLE IF EXISTS public.scaffold_games;

-- 현재 team DB에만 존재하는 BALANCED_OBSERVER를 고정 seed로 승격한다. id를
-- conflict key로 사용해 재실행해도 같은 persona 한 건만 남기며, content_hash는
-- 004·009와 같은 필드 연결 규칙으로 계산해 원문과 수치가 바뀌면 함께 드러낸다.
WITH persona_seed (
    id,
    version,
    display_name,
    speech_style,
    backstory,
    parameters
) AS (
    VALUES
        (
            'BALANCED_OBSERVER',
            'mystery-v1',
            '차분한 관찰자',
            '공개된 사실을 짧게 정리하고 단정하지 않는 말투를 사용한다.',
            '대화 중 드러난 작은 차이를 기록하고 다른 사람의 설명을 차분히 비교한다.',
            '{"deception": 0.5, "suspicion": 0.5, "verbosity": 0.5, "sociability": 0.5, "emotionality": 0.5, "assertiveness": 0.5, "memory_recall": 0.5, "risk_tolerance": 0.5, "cooperativeness": 0.5, "reasoning_skill": 0.70}'::jsonb
        )
)
INSERT INTO public.agent_personas (
    id,
    version,
    display_name,
    speech_style,
    backstory,
    parameters,
    active,
    content_hash
)
SELECT
    id,
    version,
    display_name,
    speech_style,
    backstory,
    parameters,
    TRUE,
    encode(
        digest(
            concat_ws('|', id, version, display_name, speech_style, backstory, parameters::text),
            'sha256'
        ),
        'hex'
    )
FROM persona_seed
ON CONFLICT (id) DO UPDATE
SET version = EXCLUDED.version,
    display_name = EXCLUDED.display_name,
    speech_style = EXCLUDED.speech_style,
    backstory = EXCLUDED.backstory,
    parameters = EXCLUDED.parameters,
    active = EXCLUDED.active,
    content_hash = EXCLUDED.content_hash;

DO $validation$
BEGIN
    -- upsert 이후에도 target DB가 팀 baseline과 같은 persona 원문·수치·hash를
    -- 가지는지 확인한다. 검증이 실패하면 앞선 객체 정리와 seed도 함께 rollback된다.
    IF NOT EXISTS (
        SELECT 1
        FROM public.agent_personas AS persona
        WHERE persona.id = 'BALANCED_OBSERVER'
          AND persona.version = 'mystery-v1'
          AND persona.display_name = '차분한 관찰자'
          AND persona.speech_style = '공개된 사실을 짧게 정리하고 단정하지 않는 말투를 사용한다.'
          AND persona.backstory = '대화 중 드러난 작은 차이를 기록하고 다른 사람의 설명을 차분히 비교한다.'
          AND persona.parameters = '{"deception": 0.5, "suspicion": 0.5, "verbosity": 0.5, "sociability": 0.5, "emotionality": 0.5, "assertiveness": 0.5, "memory_recall": 0.5, "risk_tolerance": 0.5, "cooperativeness": 0.5, "reasoning_skill": 0.70}'::jsonb
          AND persona.active
          AND persona.content_hash = encode(
              digest(
                  concat_ws('|', persona.id, persona.version, persona.display_name,
                      persona.speech_style, persona.backstory, persona.parameters::text),
                  'sha256'
              ),
              'hex'
          )
    ) THEN
        RAISE EXCEPTION 'BALANCED_OBSERVER seed does not match team DB baseline';
    END IF;
END;
$validation$;

COMMIT;
