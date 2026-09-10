-- scenario-v1 정적 시나리오와 AI 페르소나의 최초 seed 데이터다.
--
-- 이 파일은 Backend가 작성하고 MCP/Data 담당자가 실제 DB에 실행한다.
-- 001~003 migration은 수정하지 않으며, 아래의 안정적인 ID와 UNIQUE key를
-- 사용해 같은 파일을 다시 실행해도 같은 데이터만 남도록 한다.
BEGIN;

-- 시나리오 ID는 Master Plan에 고정된 5개만 사용한다. content_hash는 화면에
-- 보여주기 위한 값이 아니라, 나중에 원문이 바뀌었는지 확인하는 지문이다.
WITH scenario_seed (
    id,
    version,
    title,
    background,
    victim,
    locations,
    approved_at
) AS (
    VALUES
        (
            'BLACKOUT_STUDIO',
            'scenario-v1',
            '정전된 방송국',
            '생방송 준비 중 정전된 방송국에서 PD가 사망했다.',
            '생방송 PD',
            '["스튜디오", "조정실", "분장실", "대기실", "장비실"]'::jsonb,
            TIMESTAMPTZ '2026-01-01 00:00:00+00'
        ),
        (
            'SNOWBOUND_LODGE',
            'scenario-v1',
            '눈 내리는 산장',
            '폭설로 고립된 산장에서 관리인이 약병 사건으로 사망했다.',
            '산장 관리인',
            '["거실", "주방", "복도", "관리인 방", "창고"]'::jsonb,
            TIMESTAMPTZ '2026-01-01 00:00:00+00'
        ),
        (
            'CLOSING_MUSEUM',
            'scenario-v1',
            '폐관 직전의 박물관',
            '폐관 직전 박물관에서 전시 담당자가 사망했다.',
            '전시 담당자',
            '["중앙 전시장", "보안실", "안내 데스크", "복원실", "직원 휴게실"]'::jsonb,
            TIMESTAMPTZ '2026-01-01 00:00:00+00'
        ),
        (
            'LAST_BANQUET_GUEST',
            'scenario-v1',
            '호텔 만찬의 마지막 손님',
            '비공개 호텔 만찬 도중 주최자가 사망했다.',
            '만찬 주최자',
            '["연회장", "주방", "로비", "복도", "VIP룸"]'::jsonb,
            TIMESTAMPTZ '2026-01-01 00:00:00+00'
        ),
        (
            'STOPPED_NIGHT_TRAIN',
            'scenario-v1',
            '멈춰 선 야간열차',
            '열차가 터널에 멈춘 사이 승무원이 사망했다.',
            '열차 승무원',
            '["승무원실", "객차", "식당칸", "연결 통로", "화물칸"]'::jsonb,
            TIMESTAMPTZ '2026-01-01 00:00:00+00'
        )
)
INSERT INTO public.scenario_catalog (
    id,
    version,
    title,
    background,
    victim,
    locations,
    active,
    content_hash,
    approved_at
)
SELECT
    id,
    version,
    title,
    background,
    victim,
    locations,
    TRUE,
    encode(
        digest(
            concat_ws('|', id, version, title, background, victim, locations::text),
            'sha256'
        ),
        'hex'
    ),
    approved_at
FROM scenario_seed
ON CONFLICT (version, id) DO UPDATE
SET title = EXCLUDED.title,
    background = EXCLUDED.background,
    victim = EXCLUDED.victim,
    locations = EXCLUDED.locations,
    active = EXCLUDED.active,
    content_hash = EXCLUDED.content_hash,
    approved_at = EXCLUDED.approved_at;

-- 한 문장에는 좌석 placeholder를 넣어 게임 생성 시 실제 좌석 정보로
-- 치환할 수 있게 한다. 역할이나 진영은 seed 문장에 저장하지 않는다.
WITH template_seed (scenario_id, alibi_templates, observation_templates) AS (
    VALUES
        (
            'BLACKOUT_STUDIO',
            ARRAY[
                '좌석 {{seat}}은 정전 전 스튜디오의 방송 준비물을 확인했다.',
                '좌석 {{seat}}은 정전이 시작되기 전 대기실에서 방송 순서를 정리했다.',
                '좌석 {{seat}}은 조정실 화면의 상태를 확인한 뒤 자리로 돌아왔다.',
                '좌석 {{seat}}은 분장실에서 필요한 소품을 찾고 있었다.',
                '좌석 {{seat}}은 장비실 앞에서 케이블 상태를 살펴봤다고 말했다.',
                '좌석 {{seat}}은 정전 직전 다른 사람들과 스튜디오 입구에 있었다.',
                '좌석 {{seat}}은 생방송 자료를 들고 대기실 쪽으로 이동했다.',
                '좌석 {{seat}}은 정전 뒤에도 자신의 자리를 떠나지 않았다고 말했다.',
                '좌석 {{seat}}은 방송 준비 메모를 확인하며 주변 상황을 기록했다.'
            ],
            ARRAY[
                '좌석 {{seat}}은 정전 직전 장비실 방향을 바라보고 있었다.',
                '좌석 {{seat}}은 조정실 근처에서 케이블을 확인하는 사람을 봤다.',
                '좌석 {{seat}}은 대기실 쪽에서 급히 움직이는 발소리를 들었다.',
                '좌석 {{seat}}은 분장실 문이 열렸다 닫히는 모습을 보았다.',
                '좌석 {{seat}}은 스튜디오 입구에서 누군가 자료를 떨어뜨리는 장면을 봤다.',
                '좌석 {{seat}}은 정전 중 장비실 쪽에서 작은 소리가 났다고 말했다.',
                '좌석 {{seat}}은 조정실 앞에서 서로 다른 두 사람이 대화하는 모습을 봤다.',
                '좌석 {{seat}}은 복도에 놓인 방송 장비의 위치가 달라진 것을 알아챘다.',
                '좌석 {{seat}}은 정전 직후 스튜디오 안쪽에서 움직이는 그림자를 봤다.'
            ]
        ),
        (
            'SNOWBOUND_LODGE',
            ARRAY[
                '좌석 {{seat}}은 폭설이 시작되기 전 거실에서 모두와 이야기를 나눴다.',
                '좌석 {{seat}}은 주방에서 따뜻한 음료를 준비하고 있었다.',
                '좌석 {{seat}}은 복도에서 창문 밖의 눈 상태를 확인했다.',
                '좌석 {{seat}}은 창고에서 난방용품을 찾았다고 말했다.',
                '좌석 {{seat}}은 관리인 방 근처에서 약병을 보지 못했다고 말했다.',
                '좌석 {{seat}}은 거실의 보드게임을 정리하며 시간을 보냈다.',
                '좌석 {{seat}}은 주방의 식재료 목록을 확인했다.',
                '좌석 {{seat}}은 복도 끝에서 외투를 정리하고 다시 거실로 돌아왔다.',
                '좌석 {{seat}}은 산장 안의 조용한 분위기를 확인하며 다른 사람을 기다렸다.'
            ],
            ARRAY[
                '좌석 {{seat}}은 관리인 방에서 나오는 사람을 보았다.',
                '좌석 {{seat}}은 주방에서 약병과 비슷한 작은 물건을 본 사람이 있다고 말했다.',
                '좌석 {{seat}}은 복도에서 문이 닫히는 소리를 들었다.',
                '좌석 {{seat}}은 창고 쪽에서 눈을 털어내는 발소리를 들었다.',
                '좌석 {{seat}}은 거실에 있던 사람이 잠시 자리를 비운 것을 알아챘다.',
                '좌석 {{seat}}은 관리인 방 앞에서 낮은 목소리의 대화를 들었다.',
                '좌석 {{seat}}은 주방 선반의 물건 위치가 달라진 것을 보았다.',
                '좌석 {{seat}}은 복도 창가에서 누군가 밖을 살피는 모습을 봤다.',
                '좌석 {{seat}}은 폭설 소리 사이로 산장 안쪽에서 움직임을 느꼈다고 말했다.'
            ]
        ),
        (
            'CLOSING_MUSEUM',
            ARRAY[
                '좌석 {{seat}}은 폐관 안내 전 중앙 전시장의 작품을 살펴봤다.',
                '좌석 {{seat}}은 안내 데스크에서 관람객 동선을 정리했다.',
                '좌석 {{seat}}은 복원실 앞에서 작품 목록을 확인했다.',
                '좌석 {{seat}}은 보안실 근처에서 폐관 준비를 도왔다.',
                '좌석 {{seat}}은 직원 휴게실에서 물을 마시며 쉬었다.',
                '좌석 {{seat}}은 중앙 전시장 주변의 조명을 확인했다.',
                '좌석 {{seat}}은 안내 방송 내용을 메모했다고 말했다.',
                '좌석 {{seat}}은 복원 도구가 정리된 상태인지 살펴봤다.',
                '좌석 {{seat}}은 폐관 전 동료에게 확인할 내용을 전달했다.'
            ],
            ARRAY[
                '좌석 {{seat}}은 보안실 근처의 다툼을 들었다.',
                '좌석 {{seat}}은 안내 데스크 앞을 빠르게 지나가는 사람을 봤다.',
                '좌석 {{seat}}은 복원실 문이 열려 있는 것을 발견했다.',
                '좌석 {{seat}}은 중앙 전시장 조명이 잠시 흔들리는 모습을 봤다.',
                '좌석 {{seat}}은 직원 휴게실에서 급하게 나오는 사람을 보았다.',
                '좌석 {{seat}}은 보안실 방향에서 무언가 떨어지는 소리를 들었다.',
                '좌석 {{seat}}은 전시 안내 자료가 바닥에 놓인 것을 알아챘다.',
                '좌석 {{seat}}은 복도에서 두 사람이 전시장 쪽을 바라보는 모습을 봤다.',
                '좌석 {{seat}}은 폐관 안내 뒤에도 한 구역의 문이 열려 있었다고 말했다.'
            ]
        ),
        (
            'LAST_BANQUET_GUEST',
            ARRAY[
                '좌석 {{seat}}은 연회장에서 식사를 하며 주변 대화를 들었다.',
                '좌석 {{seat}}은 주방에 음식이 준비되는 과정을 확인했다.',
                '좌석 {{seat}}은 로비에서 도착한 손님을 안내했다.',
                '좌석 {{seat}}은 복도에서 자리를 찾은 뒤 연회장으로 돌아왔다.',
                '좌석 {{seat}}은 VIP룸 근처에서 초대 명단을 확인했다.',
                '좌석 {{seat}}은 연회장의 테이블 배치를 살펴봤다고 말했다.',
                '좌석 {{seat}}은 주방에 필요한 접시를 전달했다.',
                '좌석 {{seat}}은 로비에서 외투를 정리하고 손님을 기다렸다.',
                '좌석 {{seat}}은 만찬 자료를 읽으며 조용히 자리에 앉아 있었다.'
            ],
            ARRAY[
                '좌석 {{seat}}은 주최자와 대화한 뒤 급히 나가는 사람을 봤다.',
                '좌석 {{seat}}은 주방 입구에서 누군가 손을 씻는 모습을 보았다.',
                '좌석 {{seat}}은 로비에서 낯선 발걸음이 복도로 향하는 것을 봤다.',
                '좌석 {{seat}}은 VIP룸 쪽에서 문이 닫히는 소리를 들었다.',
                '좌석 {{seat}}은 연회장 한쪽에서 접시가 부딪히는 소리를 들었다.',
                '좌석 {{seat}}은 복도에 놓인 외투의 위치가 바뀐 것을 알아챘다.',
                '좌석 {{seat}}은 주방과 연회장 사이를 오가는 사람을 보았다.',
                '좌석 {{seat}}은 로비에서 주최자를 찾는 사람의 목소리를 들었다.',
                '좌석 {{seat}}은 VIP룸 앞에서 잠시 멈춰 선 사람을 봤다고 말했다.'
            ]
        ),
        (
            'STOPPED_NIGHT_TRAIN',
            ARRAY[
                '좌석 {{seat}}은 열차가 멈추기 전 객차에서 책을 읽고 있었다.',
                '좌석 {{seat}}은 식당칸에서 음료를 마시며 창밖을 바라봤다.',
                '좌석 {{seat}}은 연결 통로의 안내 표지를 확인했다.',
                '좌석 {{seat}}은 승무원실에 문의할 내용을 메모했다.',
                '좌석 {{seat}}은 화물칸 근처를 지나 좌석으로 돌아왔다.',
                '좌석 {{seat}}은 정차 뒤 객차 안에서 다른 사람들의 반응을 살폈다.',
                '좌석 {{seat}}은 식당칸의 빈자리를 정리했다고 말했다.',
                '좌석 {{seat}}은 연결 통로에서 열차의 흔들림을 확인했다.',
                '좌석 {{seat}}은 안내 방송을 들으며 현재 위치를 확인했다.'
            ],
            ARRAY[
                '좌석 {{seat}}은 연결 통로에서 승무원실로 이동하는 사람을 봤다.',
                '좌석 {{seat}}은 식당칸에서 급하게 자리에서 일어나는 사람을 보았다.',
                '좌석 {{seat}}은 승무원실 근처에서 문을 여는 소리를 들었다.',
                '좌석 {{seat}}은 화물칸 방향에서 금속이 부딪히는 소리를 들었다.',
                '좌석 {{seat}}은 객차 사이를 오가는 그림자를 봤다고 말했다.',
                '좌석 {{seat}}은 연결 통로 바닥의 작은 물건을 발견했다.',
                '좌석 {{seat}}은 식당칸 창가에서 승무원을 찾는 목소리를 들었다.',
                '좌석 {{seat}}은 승무원실 앞에 잠시 서 있던 사람을 보았다.',
                '좌석 {{seat}}은 열차가 멈춘 뒤 화물칸 쪽에서 움직임을 느꼈다.'
            ]
        )
)
INSERT INTO public.scenario_templates (
    scenario_id,
    template_kind,
    template_key,
    text_template,
    subject_mode,
    active
)
SELECT
    scenario_id,
    'ALIBI',
    'ALIBI_' || lpad(alibi.ordinality::text, 2, '0'),
    alibi.text_template,
    'SEAT',
    TRUE
FROM template_seed
CROSS JOIN LATERAL unnest(alibi_templates) WITH ORDINALITY AS alibi(text_template, ordinality)
UNION ALL
SELECT
    scenario_id,
    'OBSERVATION',
    'OBSERVATION_' || lpad(observation.ordinality::text, 2, '0'),
    observation.text_template,
    'SEAT',
    TRUE
FROM template_seed
CROSS JOIN LATERAL unnest(observation_templates) WITH ORDINALITY AS observation(text_template, ordinality)
ON CONFLICT (scenario_id, template_kind, template_key) DO UPDATE
SET text_template = EXCLUDED.text_template,
    subject_mode = EXCLUDED.subject_mode,
    active = EXCLUDED.active;

-- 페르소나는 말투·발언량·감정·협력 성향만 바꾼다. reasoning_skill은 모든
-- preset에서 0.5로 고정해 특정 AI가 규칙상 더 유리해지지 않게 한다.
-- 2026-09-07 대화 복기에 따라 기억 활용·결론 제시·협력을 보강하되, 반복 질문을
-- 늘릴 수 있는 의심·감정·발언 길이는 유지한다. 변경 시 아래 content_hash도 함께 계산한다.
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
            'CAUTIOUS_ANALYST',
            'agent-config-v1',
            '신중한 분석가',
            '근거를 먼저 확인하고 단정하지 않는 차분한 말투',
            '발언을 정리한 뒤 확실한 부분과 추측을 구분한다.',
            '{"sociability":0.6,"assertiveness":0.65,"suspicion":0.75,"deception":0.35,"risk_tolerance":0.55,"memory_recall":0.95,"reasoning_skill":0.5,"emotionality":0.25,"cooperativeness":0.75,"verbosity":0.55}'::jsonb
        ),
        (
            'ACTIVE_DEBATER',
            'agent-config-v1',
            '적극적 토론가',
            '생각을 빠르게 말하고 질문과 반론을 자주 하는 말투',
            '대화의 빈틈을 찾으면 바로 질문하며 토론을 이끈다.',
            '{"sociability":0.9,"assertiveness":0.9,"suspicion":0.65,"deception":0.45,"risk_tolerance":0.7,"memory_recall":0.9,"reasoning_skill":0.5,"emotionality":0.45,"cooperativeness":0.65,"verbosity":0.9}'::jsonb
        ),
        (
            'OBSERVANT_NOTEKEEPER',
            'agent-config-v1',
            '관찰형 기록자',
            '짧은 문장으로 이전 발언과 현재 상황을 비교하는 말투',
            '사람들의 말과 행동에서 반복되는 부분을 기억해 정리한다.',
            '{"sociability":0.65,"assertiveness":0.7,"suspicion":0.8,"deception":0.3,"risk_tolerance":0.55,"memory_recall":0.98,"reasoning_skill":0.5,"emotionality":0.2,"cooperativeness":0.75,"verbosity":0.5}'::jsonb
        ),
        (
            'EMOTIONAL_REACTOR',
            'agent-config-v1',
            '감정적인 반응가',
            '놀람과 의심을 솔직하게 표현하는 생생한 말투',
            '상황 변화에 빠르게 반응하고 자신의 느낌을 숨기지 않는다.',
            '{"sociability":0.7,"assertiveness":0.75,"suspicion":0.6,"deception":0.5,"risk_tolerance":0.65,"memory_recall":0.9,"reasoning_skill":0.5,"emotionality":0.95,"cooperativeness":0.7,"verbosity":0.7}'::jsonb
        ),
        (
            'COOPERATIVE_MEDIATOR',
            'agent-config-v1',
            '협력형 조정자',
            '서로 다른 의견을 요약하고 부드럽게 연결하는 말투',
            '논쟁이 길어지면 각자의 근거를 정리해 다음 질문을 제안한다.',
            '{"sociability":0.8,"assertiveness":0.7,"suspicion":0.55,"deception":0.4,"risk_tolerance":0.6,"memory_recall":0.95,"reasoning_skill":0.5,"emotionality":0.35,"cooperativeness":0.95,"verbosity":0.65}'::jsonb
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

-- seed가 일부만 들어간 채 성공으로 끝나지 않도록 실행 마지막에 정적 콘텐츠
-- 검수를 다시 한다. 이 검사는 게임 실행 전에 잘못된 시나리오를 차단한다.
DO $validation$
DECLARE
    invalid_scenario_count integer;
    invalid_persona_count integer;
    template_shortage_count integer;
    reasoning_value_count integer;
BEGIN
    -- 정상 조건을 만족하지 못한 시나리오의 개수를 직접 세어, 다섯 건이 모두
    -- 정상인 경우 0이 되도록 한다. 기존 식처럼 5에서 실패 행 수를 빼면
    -- 정상 데이터가 모두 존재할 때 오히려 5가 되어 재실행이 항상 실패한다.
    SELECT count(*) FILTER (
        WHERE NOT active
           OR approved_at IS NULL
           OR content_hash !~ '^[0-9a-f]{64}$'
    )
    INTO invalid_scenario_count
    FROM public.scenario_catalog
    WHERE version = 'scenario-v1'
      AND id IN (
          'BLACKOUT_STUDIO',
          'SNOWBOUND_LODGE',
          'CLOSING_MUSEUM',
          'LAST_BANQUET_GUEST',
          'STOPPED_NIGHT_TRAIN'
      );

    IF invalid_scenario_count > 0 THEN
        RAISE EXCEPTION 'scenario-v1 seed approval or hash validation failed';
    END IF;

    SELECT count(*)
    INTO template_shortage_count
    FROM (
        SELECT scenarios.scenario_id
        FROM (
            VALUES
                ('BLACKOUT_STUDIO'),
                ('SNOWBOUND_LODGE'),
                ('CLOSING_MUSEUM'),
                ('LAST_BANQUET_GUEST'),
                ('STOPPED_NIGHT_TRAIN')
        ) AS scenarios(scenario_id)
        LEFT JOIN public.scenario_templates AS templates
            ON templates.scenario_id = scenarios.scenario_id
           AND templates.active
        GROUP BY scenarios.scenario_id
        HAVING count(*) FILTER (WHERE template_kind = 'ALIBI') < 9
            OR count(*) FILTER (WHERE template_kind = 'OBSERVATION') < 9
    ) AS shortages;

    IF template_shortage_count > 0 THEN
        RAISE EXCEPTION 'scenario-v1 requires at least 9 alibi and observation templates per scenario';
    END IF;

    SELECT 5 - count(*)
    INTO invalid_persona_count
    FROM public.agent_personas
    WHERE id IN (
        'CAUTIOUS_ANALYST',
        'ACTIVE_DEBATER',
        'OBSERVANT_NOTEKEEPER',
        'EMOTIONAL_REACTOR',
        'COOPERATIVE_MEDIATOR'
    )
      AND active
      AND parameters ?& ARRAY[
          'sociability', 'assertiveness', 'suspicion', 'deception',
          'risk_tolerance', 'memory_recall', 'reasoning_skill', 'emotionality',
          'cooperativeness', 'verbosity'
      ]
      AND NOT EXISTS (
          SELECT 1
          FROM jsonb_each_text(parameters) AS parameter(key, value)
          WHERE parameter.key IN (
              'sociability', 'assertiveness', 'suspicion', 'deception',
              'risk_tolerance', 'memory_recall', 'reasoning_skill', 'emotionality',
              'cooperativeness', 'verbosity'
          )
          AND parameter.value::numeric NOT BETWEEN 0.0 AND 1.0
      );

    IF invalid_persona_count <> 0 THEN
        RAISE EXCEPTION 'agent persona seed is missing or contains an out-of-range parameter';
    END IF;

    SELECT count(DISTINCT (parameters->>'reasoning_skill')::numeric)
    INTO reasoning_value_count
    FROM public.agent_personas
    WHERE id IN (
        'CAUTIOUS_ANALYST',
        'ACTIVE_DEBATER',
        'OBSERVANT_NOTEKEEPER',
        'EMOTIONAL_REACTOR',
        'COOPERATIVE_MEDIATOR'
    );

    IF reasoning_value_count <> 1
       OR EXISTS (
           SELECT 1
           FROM public.agent_personas
           WHERE id IN (
               'CAUTIOUS_ANALYST',
               'ACTIVE_DEBATER',
               'OBSERVANT_NOTEKEEPER',
               'COOPERATIVE_MEDIATOR',
               'EMOTIONAL_REACTOR'
           )
           AND (parameters->>'reasoning_skill')::numeric <> 0.5
       ) THEN
        RAISE EXCEPTION 'all mystery-v1 persona reasoning_skill values must be 0.5';
    END IF;
END;
$validation$;

COMMIT;
