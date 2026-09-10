-- 관리자 화면 확인용 합성 데이터 30게임을 추가한다.
--
-- 이 파일은 migration에 포함하지 않는 수동 seed다. 기존 운영 데이터를 삭제하거나
-- 수정하지 않고, 고정된 합성 UUID에만 INSERT하므로 같은 파일을 다시 실행해도
-- 중복되지 않는다. seed 데이터에는 실제 비밀번호·토큰·개인정보를 넣지 않는다.
-- 관리자 감사 로그는 실제 조회 이력을 의미하므로 가짜 행을 만들지 않는다.

BEGIN;

-- 1. 게임 소유자 30명을 만든다. display_name은 화면 검증용 합성 값이다.
WITH demo_users AS (
    SELECT
        i,
        md5('ai-mafia-admin-demo:user:' || i::text)::uuid AS user_id,
        TIMESTAMPTZ '2026-08-01 00:00:00+00' + (i - 1) * INTERVAL '1 day' AS created_at
    FROM generate_series(1, 30) AS series(i)
)
INSERT INTO public.users (
    id, email, display_name, avatar_url, is_active, last_login_at,
    created_at, updated_at, last_seen_at
)
SELECT
    user_id,
    NULL,
    '관리자 데모 사용자 ' || lpad(i::text, 2, '0'),
    NULL,
    TRUE,
    created_at,
    created_at,
    created_at,
    created_at
FROM demo_users
ON CONFLICT (id) DO NOTHING;

-- 2. 완료·저장·진행·실패 상태를 섞어 운영 KPI가 실제 화면에서 보이게 한다.
--    시나리오 해시는 현재 활성 catalog에서 읽어 FK·콘텐츠 무결성을 유지한다.
WITH demo_games AS (
    SELECT
        i,
        md5('ai-mafia-admin-demo:game:' || i::text)::uuid AS game_id,
        md5('ai-mafia-admin-demo:user:' || i::text)::uuid AS owner_user_id,
        CASE
            WHEN i <= 22 THEN 'COMPLETED'
            WHEN i <= 26 THEN 'SAVED'
            WHEN i <= 29 THEN 'IN_PROGRESS'
            ELSE 'FAILED'
        END AS status,
        CASE
            WHEN i <= 22 THEN 'ENDED'
            WHEN i <= 26 THEN 'DAY_DISCUSSION'
            WHEN i <= 29 THEN 'ROLE_REVEAL'
            ELSE 'ENDED'
        END AS phase,
        TIMESTAMPTZ '2026-08-01 00:00:00+00:00' + (i - 1) * INTERVAL '1 day' AS created_at,
        CASE (i % 5)
            WHEN 0 THEN 'BLACKOUT_STUDIO'
            WHEN 1 THEN 'SNOWBOUND_LODGE'
            WHEN 2 THEN 'CLOSING_MUSEUM'
            WHEN 3 THEN 'LAST_BANQUET_GUEST'
            ELSE 'STOPPED_NIGHT_TRAIN'
        END AS scenario_id,
        CASE WHEN i <= 22 AND i % 3 = 0 THEN 'MAFIA' ELSE 'CITIZEN' END AS winner,
        CASE WHEN i <= 22 AND i % 3 = 0
             THEN 'MAFIA_PARITY' ELSE 'ALL_MAFIA_ELIMINATED' END AS win_reason
    FROM generate_series(1, 30) AS series(i)
)
INSERT INTO public.games (
    id, owner_user_id, status, phase, round, day_number, state_version,
    next_event_sequence, next_front_sequence, player_count, mafia_count,
    ruleset_version, scenario_version, scenario_id, scenario_content_hash,
    seed_ciphertext, seed_nonce, seed_key_id, agent_config_version,
    fast_forward_enabled, winner, win_reason, saved_at, finished_at,
    created_at, updated_at
)
SELECT
    games.game_id,
    games.owner_user_id,
    games.status,
    games.phase,
    CASE WHEN games.status = 'COMPLETED' THEN 1 + (games.i % 5) ELSE 0 END,
    CASE WHEN games.status = 'COMPLETED' THEN 1 + (games.i % 4) ELSE 1 END,
    CASE WHEN games.status = 'COMPLETED' THEN 8 + games.i ELSE 1 END,
    CASE WHEN games.status = 'COMPLETED' THEN 20 + games.i ELSE 1 END,
    CASE WHEN games.status = 'COMPLETED' THEN 15 + games.i ELSE 1 END,
    7,
    2,
    'mystery-v1',
    'scenario-v1',
    games.scenario_id,
    scenario.content_hash,
    decode(md5('ai-mafia-admin-demo:cipher:' || games.i::text), 'hex'),
    decode(md5('ai-mafia-admin-demo:nonce:' || games.i::text), 'hex'),
    'admin-demo-seed-v1',
    'agent-config-v1',
    TRUE,
    CASE WHEN games.status = 'COMPLETED' THEN games.winner ELSE NULL END,
    CASE WHEN games.status = 'COMPLETED' THEN games.win_reason ELSE NULL END,
    CASE WHEN games.status = 'SAVED' THEN games.created_at + INTERVAL '2 hours' ELSE NULL END,
    CASE WHEN games.status = 'COMPLETED' THEN games.created_at + INTERVAL '45 minutes' ELSE NULL END,
    games.created_at,
    games.created_at
FROM demo_games AS games
JOIN public.scenario_catalog AS scenario
  ON scenario.id = games.scenario_id
 AND scenario.version = 'scenario-v1'
ON CONFLICT (id) DO NOTHING;

-- 3. 게임마다 사람 1명과 AI 6명을 연결한다. 개인 역할은 관리자 API가
--    반환하지 않지만, 집계 API가 정상 계산되도록 정본 제약을 만족시킨다.
WITH demo_games AS (
    SELECT
        i,
        md5('ai-mafia-admin-demo:game:' || i::text)::uuid AS game_id,
        md5('ai-mafia-admin-demo:user:' || i::text)::uuid AS owner_user_id,
        TIMESTAMPTZ '2026-08-01 00:00:00+00:00' + (i - 1) * INTERVAL '1 day' AS created_at
    FROM generate_series(1, 30) AS series(i)
), demo_seats AS (
    SELECT *
    FROM (VALUES
        (1, 'HUMAN', 'CITIZEN', 'CITIZEN', NULL::text),
        (2, 'AI', 'MAFIA', 'MAFIA', 'CAUTIOUS_ANALYST'),
        (3, 'AI', 'MAFIA', 'MAFIA', 'ACTIVE_DEBATER'),
        (4, 'AI', 'DETECTIVE', 'CITIZEN', 'OBSERVANT_NOTEKEEPER'),
        (5, 'AI', 'DOCTOR', 'CITIZEN', 'EMOTIONAL_REACTOR'),
        (6, 'AI', 'CITIZEN', 'CITIZEN', 'COOPERATIVE_MEDIATOR'),
        (7, 'AI', 'CITIZEN', 'CITIZEN', 'BALANCED_OBSERVER')
    ) AS seats(seat, kind, role, faction, persona_id)
)
INSERT INTO public.game_players (
    id, game_id, user_id, kind, seat, display_name, role, faction,
    alive, persona_id, eliminated_phase, eliminated_round, created_at, updated_at
)
SELECT
    md5('ai-mafia-admin-demo:player:' || games.i::text || ':' || seats.seat::text)::uuid,
    games.game_id,
    CASE WHEN seats.kind = 'HUMAN' THEN games.owner_user_id ELSE NULL END,
    seats.kind,
    seats.seat,
    CASE WHEN seats.kind = 'HUMAN'
         THEN '데모 참가자 ' || lpad(games.i::text, 2, '0')
         ELSE 'AI 좌석 ' || seats.seat::text END,
    seats.role,
    seats.faction,
    TRUE,
    seats.persona_id,
    NULL,
    NULL,
    games.created_at,
    games.created_at
FROM demo_games AS games
CROSS JOIN demo_seats AS seats
ON CONFLICT (id) DO NOTHING;

-- 4. 완료 게임에는 게임별 의견을, 나머지 사용자에는 일반 의견을 넣는다.
--    관리자 피드백 화면이 종류·평점 필터를 모두 확인할 수 있도록 구성한다.
WITH demo_feedback AS (
    SELECT
        i,
        md5('ai-mafia-admin-demo:feedback:' || i::text)::uuid AS feedback_id,
        md5('ai-mafia-admin-demo:user:' || i::text)::uuid AS user_id,
        CASE WHEN i <= 22 THEN 'GAME' ELSE 'GENERAL' END AS feedback_type,
        CASE WHEN i <= 22
             THEN md5('ai-mafia-admin-demo:game:' || i::text)::uuid ELSE NULL END AS game_id,
        3 + (i % 3) AS rating,
        TIMESTAMPTZ '2026-08-01 00:00:00+00:00' + (i - 1) * INTERVAL '1 day' AS created_at
    FROM generate_series(1, 30) AS series(i)
)
INSERT INTO public.feedback (
    id, user_id, feedback_type, game_id, rating, comment, tags, created_at
)
SELECT
    feedback_id,
    user_id,
    feedback_type,
    game_id,
    rating,
    '가상 관리자 데이터 ' || lpad(i::text, 2, '0')
        || ': 사건 설명과 토론 흐름을 확인하기 쉬웠습니다.',
    '["synthetic", "admin-demo"]'::jsonb,
    created_at
FROM demo_feedback
ON CONFLICT (id) DO NOTHING;

COMMIT;
