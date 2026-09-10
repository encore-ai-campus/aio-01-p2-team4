-- 기존 seed와 team DB의 다른 성향을 보존하며 승인된 추론 수치만 갱신한다.
-- 먼저 Backend의 전원 0.5 제한을 해제해야 기존 게임의 persona 조회가 계속 성공한다.
-- ID와 version을 함께 제한해 이후 별도 버전으로 등록된 preset은 덮어쓰지 않는다.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '15s';

WITH targets (id, version, reasoning_skill) AS (
    VALUES
        ('CAUTIOUS_ANALYST', 'agent-config-v1', 0.80::numeric),
        ('OBSERVANT_NOTEKEEPER', 'agent-config-v1', 0.80::numeric),
        ('ACTIVE_DEBATER', 'agent-config-v1', 0.75::numeric),
        ('COOPERATIVE_MEDIATOR', 'agent-config-v1', 0.70::numeric),
        ('BALANCED_OBSERVER', 'mystery-v1', 0.70::numeric),
        ('EMOTIONAL_REACTOR', 'agent-config-v1', 0.60::numeric)
)
UPDATE public.agent_personas AS persona
SET parameters = jsonb_set(
        persona.parameters, '{reasoning_skill}', to_jsonb(targets.reasoning_skill)
    ),
    content_hash = encode(digest(concat_ws(
        '|', persona.id, persona.version, persona.display_name,
        persona.speech_style, persona.backstory,
        jsonb_set(persona.parameters, '{reasoning_skill}', to_jsonb(targets.reasoning_skill))::text
    ), 'sha256'), 'hex')
FROM targets
WHERE persona.id = targets.id
  AND persona.version = targets.version
  AND persona.parameters->'reasoning_skill' IS DISTINCT FROM to_jsonb(targets.reasoning_skill);

COMMIT;
