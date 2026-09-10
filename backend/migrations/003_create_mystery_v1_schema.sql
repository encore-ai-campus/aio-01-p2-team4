-- AI 마피아 mystery-v1의 PostgreSQL 원본 스키마를 생성한다.
-- 기존 001·002 migration에서 만든 legacy identity와 scaffold 객체는 실제 데이터
-- 보존 검토 전까지 삭제하지 않는다. 이 파일은 canonical 테이블을 순방향으로
-- 추가하고 legacy users 테이블에 UUID-only 흐름에 필요한 컬럼만 보강한다.
--
-- 모든 DDL은 하나의 명시적 트랜잭션에서 실행한다. CREATE TABLE/INDEX의
-- IF NOT EXISTS와 조건부 constraint·trigger 생성으로 동일 migration을 재실행해도
-- 기존 객체나 seed 데이터를 중복 생성하지 않는다.
BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 001의 legacy users 행을 보존하면서 canonical 사용자 모델에 필요한 최근 활동
-- 시각을 추가한다. 기존 identity route가 제거되기 전까지는 해당 코드가 UUID와
-- last_seen_at을 직접 넣지 않으므로, 전환 기간에만 기존 UUID default와 새 시각
-- default를 유지해 현재 로그인 경로를 깨뜨리지 않는다.
ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS last_seen_at timestamptz DEFAULT CURRENT_TIMESTAMP;

UPDATE public.users
SET last_seen_at = GREATEST(
    created_at,
    COALESCE(last_login_at, updated_at, created_at, CURRENT_TIMESTAMP)
)
WHERE last_seen_at IS NULL;

ALTER TABLE public.users
    ALTER COLUMN last_seen_at SET NOT NULL;

DO $migration$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'users_last_seen_at_not_before_created_at'
          AND conrelid = 'public.users'::regclass
    ) THEN
        ALTER TABLE public.users
            ADD CONSTRAINT users_last_seen_at_not_before_created_at
            CHECK (last_seen_at >= created_at);
    END IF;
END;
$migration$;

-- 승인된 사건 카탈로그와 개인 문장 template은 게임 생성 뒤 원본이 바뀌더라도
-- 이미 생성된 게임의 snapshot과 hash를 재현할 수 있도록 version과 hash를 가진다.
CREATE TABLE IF NOT EXISTS public.scenario_catalog (
    id varchar(64) PRIMARY KEY,
    version varchar(32) NOT NULL,
    title varchar(120) NOT NULL,
    background text NOT NULL,
    victim varchar(120) NOT NULL,
    locations jsonb NOT NULL,
    active boolean NOT NULL DEFAULT false,
    content_hash char(64) NOT NULL,
    approved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT scenario_catalog_version_id_key UNIQUE (version, id),
    CONSTRAINT scenario_catalog_title_not_blank CHECK (btrim(title) <> ''),
    CONSTRAINT scenario_catalog_background_not_blank CHECK (btrim(background) <> ''),
    CONSTRAINT scenario_catalog_victim_not_blank CHECK (btrim(victim) <> ''),
    CONSTRAINT scenario_catalog_locations_shape CHECK (
        jsonb_typeof(locations) = 'array'
        AND jsonb_array_length(locations) BETWEEN 4 AND 5
    ),
    CONSTRAINT scenario_catalog_content_hash_format CHECK (
        content_hash ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT scenario_catalog_active_requires_approval CHECK (
        NOT active OR approved_at IS NOT NULL
    )
);

CREATE TABLE IF NOT EXISTS public.scenario_templates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario_id varchar(64) NOT NULL,
    template_kind varchar(16) NOT NULL,
    template_key varchar(64) NOT NULL,
    text_template varchar(240) NOT NULL,
    subject_mode varchar(16) NOT NULL,
    active boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT scenario_templates_scenario_id_fkey
        FOREIGN KEY (scenario_id)
        REFERENCES public.scenario_catalog (id)
        ON DELETE RESTRICT,
    CONSTRAINT scenario_templates_scenario_kind_key
        UNIQUE (scenario_id, template_kind, template_key),
    CONSTRAINT scenario_templates_kind_check
        CHECK (template_kind IN ('ALIBI', 'OBSERVATION')),
    CONSTRAINT scenario_templates_subject_mode_check
        CHECK (subject_mode IN ('NONE', 'SEAT', 'ANONYMOUS')),
    CONSTRAINT scenario_templates_key_not_blank CHECK (btrim(template_key) <> ''),
    CONSTRAINT scenario_templates_text_not_blank CHECK (btrim(text_template) <> '')
);

CREATE TABLE IF NOT EXISTS public.agent_personas (
    id varchar(64) PRIMARY KEY,
    version varchar(32) NOT NULL,
    display_name varchar(40) NOT NULL,
    speech_style varchar(240) NOT NULL,
    backstory varchar(500) NOT NULL,
    parameters jsonb NOT NULL,
    active boolean NOT NULL DEFAULT false,
    content_hash char(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT agent_personas_id_not_blank CHECK (btrim(id) <> ''),
    CONSTRAINT agent_personas_version_not_blank CHECK (btrim(version) <> ''),
    CONSTRAINT agent_personas_display_name_not_blank CHECK (btrim(display_name) <> ''),
    CONSTRAINT agent_personas_speech_style_not_blank CHECK (btrim(speech_style) <> ''),
    CONSTRAINT agent_personas_backstory_not_blank CHECK (btrim(backstory) <> ''),
    CONSTRAINT agent_personas_parameters_object CHECK (jsonb_typeof(parameters) = 'object'),
    CONSTRAINT agent_personas_content_hash_format CHECK (
        content_hash ~ '^[0-9a-f]{64}$'
    )
);

-- games는 상태 버전, 내부 event 순서와 Front-visible batch 순서의 단일 원본이다.
-- 승패·종료 시각 조합은 DB에서도 검증해 부분 종료 상태가 commit되지 않게 한다.
CREATE TABLE IF NOT EXISTS public.games (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id uuid NOT NULL,
    status varchar(16) NOT NULL,
    phase varchar(32) NOT NULL,
    round smallint NOT NULL DEFAULT 0,
    day_number smallint NOT NULL DEFAULT 1,
    state_version bigint NOT NULL DEFAULT 1,
    next_event_sequence bigint NOT NULL DEFAULT 1,
    next_front_sequence bigint NOT NULL DEFAULT 1,
    player_count smallint NOT NULL,
    mafia_count smallint NOT NULL,
    ruleset_version varchar(32) NOT NULL DEFAULT 'mystery-v1',
    scenario_version varchar(32) NOT NULL DEFAULT 'scenario-v1',
    scenario_id varchar(64) NOT NULL,
    scenario_content_hash char(64) NOT NULL,
    seed_ciphertext bytea NOT NULL,
    seed_nonce bytea NOT NULL,
    seed_key_id varchar(64) NOT NULL,
    agent_config_version varchar(64) NOT NULL,
    fast_forward_enabled boolean NOT NULL DEFAULT false,
    winner varchar(16),
    win_reason varchar(32),
    saved_at timestamptz,
    finished_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT games_owner_user_id_fkey
        FOREIGN KEY (owner_user_id)
        REFERENCES public.users (id)
        ON DELETE RESTRICT,
    CONSTRAINT games_scenario_version_id_fkey
        FOREIGN KEY (scenario_version, scenario_id)
        REFERENCES public.scenario_catalog (version, id)
        ON DELETE RESTRICT,
    CONSTRAINT games_status_check
        CHECK (status IN ('IN_PROGRESS', 'SAVED', 'COMPLETED', 'FAILED')),
    CONSTRAINT games_phase_check CHECK (
        phase IN (
            'ROLE_REVEAL', 'DAY_DISCUSSION', 'NIGHT_ACTION', 'DAY_VOTE',
            'REVOTE', 'FINAL_DISCUSSION', 'FINAL_ACCUSATION', 'ENDED'
        )
    ),
    CONSTRAINT games_round_check CHECK (round BETWEEN 0 AND 5),
    CONSTRAINT games_day_number_check CHECK (day_number BETWEEN 1 AND 6),
    CONSTRAINT games_state_version_check CHECK (state_version > 0),
    CONSTRAINT games_next_event_sequence_check CHECK (next_event_sequence > 0),
    CONSTRAINT games_next_front_sequence_check CHECK (next_front_sequence > 0),
    CONSTRAINT games_player_count_check CHECK (player_count BETWEEN 6 AND 9),
    CONSTRAINT games_mafia_count_check CHECK (
        mafia_count > 0 AND mafia_count < player_count
    ),
    CONSTRAINT games_ruleset_version_check CHECK (ruleset_version = 'mystery-v1'),
    CONSTRAINT games_scenario_version_check CHECK (scenario_version = 'scenario-v1'),
    CONSTRAINT games_scenario_content_hash_format CHECK (
        scenario_content_hash ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT games_seed_material_not_empty CHECK (
        octet_length(seed_ciphertext) > 0 AND octet_length(seed_nonce) > 0
    ),
    CONSTRAINT games_seed_key_id_not_blank CHECK (btrim(seed_key_id) <> ''),
    CONSTRAINT games_agent_config_version_not_blank
        CHECK (btrim(agent_config_version) <> ''),
    CONSTRAINT games_winner_check CHECK (winner IS NULL OR winner IN ('CITIZEN', 'MAFIA')),
    CONSTRAINT games_win_reason_check CHECK (
        win_reason IS NULL OR win_reason IN (
            'ALL_MAFIA_ELIMINATED', 'MAFIA_PARITY',
            'FINAL_MAFIA_SELECTED', 'FINAL_NON_MAFIA_SELECTED'
        )
    ),
    CONSTRAINT games_winner_reason_pair CHECK (
        (winner IS NULL AND win_reason IS NULL)
        OR (winner IS NOT NULL AND win_reason IS NOT NULL)
    ),
    CONSTRAINT games_completed_state_check CHECK (
        status <> 'COMPLETED'
        OR (
            phase = 'ENDED'
            AND winner IS NOT NULL
            AND win_reason IS NOT NULL
            AND finished_at IS NOT NULL
        )
    ),
    CONSTRAINT games_in_progress_not_finished CHECK (
        status <> 'IN_PROGRESS' OR finished_at IS NULL
    ),
    CONSTRAINT games_saved_at_check CHECK (
        status <> 'SAVED' OR saved_at IS NOT NULL
    ),
    CONSTRAINT games_updated_at_not_before_created_at CHECK (updated_at >= created_at)
);

CREATE INDEX IF NOT EXISTS idx_games_owner_updated
    ON public.games (owner_user_id, updated_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_games_status_updated
    ON public.games (status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_games_scenario_version_id
    ON public.games (scenario_version, scenario_id);

CREATE TABLE IF NOT EXISTS public.game_players (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id uuid NOT NULL,
    user_id uuid,
    kind varchar(8) NOT NULL,
    seat smallint NOT NULL,
    display_name varchar(40) NOT NULL,
    role varchar(16) NOT NULL,
    faction varchar(16) NOT NULL,
    alive boolean NOT NULL DEFAULT true,
    persona_id varchar(64),
    eliminated_phase varchar(32),
    eliminated_round smallint,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT game_players_game_id_fkey
        FOREIGN KEY (game_id)
        REFERENCES public.games (id)
        ON DELETE CASCADE,
    CONSTRAINT game_players_user_id_fkey
        FOREIGN KEY (user_id)
        REFERENCES public.users (id)
        ON DELETE RESTRICT,
    CONSTRAINT game_players_persona_id_fkey
        FOREIGN KEY (persona_id)
        REFERENCES public.agent_personas (id)
        ON DELETE RESTRICT,
    CONSTRAINT game_players_game_id_id_key UNIQUE (game_id, id),
    CONSTRAINT game_players_game_id_seat_key UNIQUE (game_id, seat),
    CONSTRAINT game_players_kind_check CHECK (kind IN ('HUMAN', 'AI')),
    CONSTRAINT game_players_seat_check CHECK (seat BETWEEN 1 AND 9),
    CONSTRAINT game_players_display_name_not_blank CHECK (btrim(display_name) <> ''),
    CONSTRAINT game_players_role_check
        CHECK (role IN ('MAFIA', 'DETECTIVE', 'DOCTOR', 'CITIZEN')),
    CONSTRAINT game_players_faction_check CHECK (faction IN ('MAFIA', 'CITIZEN')),
    CONSTRAINT game_players_role_faction_check CHECK (
        (role = 'MAFIA' AND faction = 'MAFIA')
        OR (role IN ('DETECTIVE', 'DOCTOR', 'CITIZEN') AND faction = 'CITIZEN')
    ),
    CONSTRAINT game_players_identity_kind_check CHECK (
        (kind = 'HUMAN' AND user_id IS NOT NULL AND persona_id IS NULL)
        OR (kind = 'AI' AND user_id IS NULL AND persona_id IS NOT NULL)
    ),
    CONSTRAINT game_players_elimination_check CHECK (
        (alive AND eliminated_phase IS NULL AND eliminated_round IS NULL)
        OR (
            NOT alive
            AND eliminated_phase IS NOT NULL
            AND eliminated_round IS NOT NULL
            AND eliminated_phase IN (
                'DAY_DISCUSSION', 'NIGHT_ACTION', 'DAY_VOTE', 'REVOTE',
                'FINAL_DISCUSSION', 'FINAL_ACCUSATION'
            )
            AND eliminated_round BETWEEN 1 AND 5
        )
    ),
    CONSTRAINT game_players_updated_at_not_before_created_at CHECK (updated_at >= created_at)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_game_players_game_user
    ON public.game_players (game_id, user_id)
    WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_game_players_user
    ON public.game_players (user_id)
    WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_game_players_persona
    ON public.game_players (persona_id)
    WHERE persona_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.player_scenario_facts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id uuid NOT NULL,
    player_id uuid NOT NULL,
    fact_kind varchar(16) NOT NULL,
    template_id uuid NOT NULL,
    rendered_text varchar(240) NOT NULL,
    subject_player_id uuid,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT player_scenario_facts_game_id_fkey
        FOREIGN KEY (game_id)
        REFERENCES public.games (id)
        ON DELETE CASCADE,
    CONSTRAINT player_scenario_facts_player_fkey
        FOREIGN KEY (game_id, player_id)
        REFERENCES public.game_players (game_id, id)
        ON DELETE CASCADE,
    CONSTRAINT player_scenario_facts_subject_player_fkey
        FOREIGN KEY (game_id, subject_player_id)
        REFERENCES public.game_players (game_id, id)
        ON DELETE CASCADE,
    CONSTRAINT player_scenario_facts_template_id_fkey
        FOREIGN KEY (template_id)
        REFERENCES public.scenario_templates (id)
        ON DELETE RESTRICT,
    CONSTRAINT player_scenario_facts_player_kind_key
        UNIQUE (game_id, player_id, fact_kind),
    CONSTRAINT player_scenario_facts_kind_check
        CHECK (fact_kind IN ('ALIBI', 'OBSERVATION')),
    CONSTRAINT player_scenario_facts_rendered_text_not_blank
        CHECK (btrim(rendered_text) <> '')
);

CREATE INDEX IF NOT EXISTS idx_player_scenario_facts_template
    ON public.player_scenario_facts (template_id);
CREATE INDEX IF NOT EXISTS idx_player_scenario_facts_subject
    ON public.player_scenario_facts (game_id, subject_player_id)
    WHERE subject_player_id IS NOT NULL;

-- action window가 OPEN·PAUSED·RESOLVING 중 하나인 동안에는 게임별 한 행만
-- 존재하도록 부분 unique index로 동시 진행을 차단한다.
CREATE TABLE IF NOT EXISTS public.action_windows (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id uuid NOT NULL,
    window_kind varchar(24) NOT NULL,
    phase varchar(32) NOT NULL,
    round smallint NOT NULL,
    cycle smallint NOT NULL DEFAULT 1,
    turn_player_id uuid,
    opened_state_version bigint NOT NULL,
    status varchar(16) NOT NULL,
    opened_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deadline_at timestamptz,
    remaining_ms_on_save integer,
    resolved_at timestamptz,
    CONSTRAINT action_windows_game_id_fkey
        FOREIGN KEY (game_id)
        REFERENCES public.games (id)
        ON DELETE CASCADE,
    CONSTRAINT action_windows_turn_player_fkey
        FOREIGN KEY (game_id, turn_player_id)
        REFERENCES public.game_players (game_id, id)
        ON DELETE CASCADE,
    CONSTRAINT action_windows_game_id_id_key UNIQUE (game_id, id),
    CONSTRAINT action_windows_kind_check CHECK (
        window_kind IN ('SPEECH', 'NIGHT', 'VOTE', 'REVOTE', 'FINAL_VOTE')
    ),
    CONSTRAINT action_windows_phase_check CHECK (
        phase IN (
            'DAY_DISCUSSION', 'NIGHT_ACTION', 'DAY_VOTE', 'REVOTE',
            'FINAL_DISCUSSION', 'FINAL_ACCUSATION'
        )
    ),
    CONSTRAINT action_windows_round_check CHECK (round BETWEEN 0 AND 5),
    CONSTRAINT action_windows_cycle_check CHECK (cycle > 0),
    CONSTRAINT action_windows_opened_state_version_check CHECK (opened_state_version > 0),
    CONSTRAINT action_windows_status_check
        CHECK (status IN ('OPEN', 'PAUSED', 'RESOLVING', 'RESOLVED', 'CANCELLED')),
    CONSTRAINT action_windows_turn_player_check CHECK (
        (window_kind = 'SPEECH' AND turn_player_id IS NOT NULL)
        OR (window_kind <> 'SPEECH' AND turn_player_id IS NULL)
    ),
    CONSTRAINT action_windows_remaining_ms_check CHECK (
        remaining_ms_on_save IS NULL OR remaining_ms_on_save >= 0
    ),
    CONSTRAINT action_windows_saved_deadline_check CHECK (
        status <> 'PAUSED' OR deadline_at IS NULL
    ),
    CONSTRAINT action_windows_timed_deadline_check CHECK (
        status <> 'OPEN'
        OR window_kind = 'SPEECH'
        OR deadline_at IS NOT NULL
    ),
    CONSTRAINT action_windows_resolved_at_check CHECK (
        status NOT IN ('RESOLVED', 'CANCELLED') OR resolved_at IS NOT NULL
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_action_windows_game_active
    ON public.action_windows (game_id)
    WHERE status IN ('OPEN', 'PAUSED', 'RESOLVING');
CREATE INDEX IF NOT EXISTS idx_action_windows_turn_player
    ON public.action_windows (game_id, turn_player_id)
    WHERE turn_player_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.action_submissions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id uuid NOT NULL,
    window_id uuid NOT NULL,
    actor_player_id uuid NOT NULL,
    action_type varchar(24) NOT NULL,
    target_player_id uuid,
    message varchar(200),
    source varchar(16) NOT NULL,
    observed_state_version bigint NOT NULL,
    submitted_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT action_submissions_game_id_fkey
        FOREIGN KEY (game_id)
        REFERENCES public.games (id)
        ON DELETE CASCADE,
    CONSTRAINT action_submissions_window_fkey
        FOREIGN KEY (game_id, window_id)
        REFERENCES public.action_windows (game_id, id)
        ON DELETE CASCADE,
    CONSTRAINT action_submissions_actor_fkey
        FOREIGN KEY (game_id, actor_player_id)
        REFERENCES public.game_players (game_id, id)
        ON DELETE CASCADE,
    CONSTRAINT action_submissions_target_fkey
        FOREIGN KEY (game_id, target_player_id)
        REFERENCES public.game_players (game_id, id)
        ON DELETE CASCADE,
    CONSTRAINT action_submissions_window_actor_key UNIQUE (window_id, actor_player_id),
    CONSTRAINT action_submissions_type_check CHECK (
        action_type IN ('SPEAK', 'PASS', 'ATTACK', 'INVESTIGATE', 'PROTECT', 'VOTE')
    ),
    CONSTRAINT action_submissions_source_check CHECK (source IN ('HUMAN', 'AGENT', 'AUTO')),
    CONSTRAINT action_submissions_observed_version_check CHECK (observed_state_version > 0),
    CONSTRAINT action_submissions_payload_check CHECK (
        (
            action_type = 'SPEAK'
            AND target_player_id IS NULL
            AND message IS NOT NULL
            AND btrim(message) <> ''
        )
        OR (action_type = 'PASS' AND target_player_id IS NULL AND message IS NULL)
        OR (
            action_type IN ('ATTACK', 'INVESTIGATE', 'PROTECT', 'VOTE')
            AND target_player_id IS NOT NULL
            AND message IS NULL
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_action_submissions_game
    ON public.action_submissions (game_id);
CREATE INDEX IF NOT EXISTS idx_action_submissions_target
    ON public.action_submissions (game_id, target_player_id)
    WHERE target_player_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.action_window_resolutions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id uuid NOT NULL,
    window_id uuid NOT NULL,
    resolution_type varchar(24) NOT NULL,
    resolution_source varchar(24) NOT NULL,
    resolved_target_player_id uuid,
    result_payload jsonb NOT NULL,
    rng_proof_hash char(64),
    resolved_state_version bigint NOT NULL,
    resolved_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT action_window_resolutions_game_id_fkey
        FOREIGN KEY (game_id)
        REFERENCES public.games (id)
        ON DELETE CASCADE,
    CONSTRAINT action_window_resolutions_window_fkey
        FOREIGN KEY (game_id, window_id)
        REFERENCES public.action_windows (game_id, id)
        ON DELETE CASCADE,
    CONSTRAINT action_window_resolutions_target_fkey
        FOREIGN KEY (game_id, resolved_target_player_id)
        REFERENCES public.game_players (game_id, id)
        ON DELETE CASCADE,
    CONSTRAINT action_window_resolutions_window_id_key UNIQUE (window_id),
    CONSTRAINT action_window_resolutions_type_check
        CHECK (resolution_type IN ('NIGHT', 'VOTE', 'REVOTE', 'FINAL_VOTE')),
    CONSTRAINT action_window_resolutions_source_not_blank
        CHECK (btrim(resolution_source) <> ''),
    CONSTRAINT action_window_resolutions_payload_object
        CHECK (jsonb_typeof(result_payload) = 'object'),
    CONSTRAINT action_window_resolutions_rng_hash_format CHECK (
        rng_proof_hash IS NULL OR rng_proof_hash ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT action_window_resolutions_state_version_check
        CHECK (resolved_state_version > 0)
);

CREATE INDEX IF NOT EXISTS idx_action_window_resolutions_game
    ON public.action_window_resolutions (game_id);
CREATE INDEX IF NOT EXISTS idx_action_window_resolutions_target
    ON public.action_window_resolutions (game_id, resolved_target_player_id)
    WHERE resolved_target_player_id IS NOT NULL;

-- Front에는 내부 sequence를 노출하지 않고 front_sequence와 operation_index로
-- transaction 단위의 원자적인 operation batch만 제공한다.
CREATE TABLE IF NOT EXISTS public.game_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id uuid NOT NULL,
    sequence bigint NOT NULL,
    front_sequence bigint,
    operation_index smallint,
    state_version bigint NOT NULL,
    event_type varchar(64) NOT NULL,
    audience varchar(16) NOT NULL,
    audience_player_id uuid,
    schema_version smallint NOT NULL DEFAULT 1,
    operation_type varchar(32),
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT game_events_game_id_fkey
        FOREIGN KEY (game_id)
        REFERENCES public.games (id)
        ON DELETE CASCADE,
    CONSTRAINT game_events_audience_player_fkey
        FOREIGN KEY (game_id, audience_player_id)
        REFERENCES public.game_players (game_id, id)
        ON DELETE CASCADE,
    CONSTRAINT game_events_game_sequence_key UNIQUE (game_id, sequence),
    CONSTRAINT game_events_sequence_check CHECK (sequence > 0),
    CONSTRAINT game_events_front_sequence_check
        CHECK (front_sequence IS NULL OR front_sequence > 0),
    CONSTRAINT game_events_operation_index_check
        CHECK (operation_index IS NULL OR operation_index >= 0),
    CONSTRAINT game_events_state_version_check CHECK (state_version > 0),
    CONSTRAINT game_events_event_type_not_blank CHECK (btrim(event_type) <> ''),
    CONSTRAINT game_events_audience_check CHECK (audience IN ('PUBLIC', 'PLAYER', 'ADMIN')),
    CONSTRAINT game_events_audience_player_check CHECK (
        (audience = 'PLAYER' AND audience_player_id IS NOT NULL)
        OR (audience <> 'PLAYER' AND audience_player_id IS NULL)
    ),
    CONSTRAINT game_events_schema_version_check CHECK (schema_version > 0),
    CONSTRAINT game_events_front_operation_check CHECK (
        (
            front_sequence IS NOT NULL
            AND operation_index IS NOT NULL
            AND operation_type IS NOT NULL
        )
        OR (
            front_sequence IS NULL
            AND operation_index IS NULL
            AND operation_type IS NULL
        )
    ),
    CONSTRAINT game_events_operation_type_not_blank CHECK (
        operation_type IS NULL OR btrim(operation_type) <> ''
    ),
    CONSTRAINT game_events_payload_object CHECK (jsonb_typeof(payload) = 'object')
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_game_events_front_operation
    ON public.game_events (game_id, front_sequence, operation_index)
    WHERE front_sequence IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_game_events_sync
    ON public.game_events (game_id, front_sequence, operation_index)
    WHERE front_sequence IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_game_events_audience_player
    ON public.game_events (game_id, audience_player_id)
    WHERE audience_player_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.command_receipts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    principal_type varchar(16) NOT NULL,
    principal_id uuid NOT NULL,
    idempotency_key uuid NOT NULL,
    route_scope varchar(120) NOT NULL,
    game_id uuid,
    request_hash char(64) NOT NULL,
    result_state_version bigint,
    http_status smallint NOT NULL,
    result_body jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT command_receipts_game_id_fkey
        FOREIGN KEY (game_id)
        REFERENCES public.games (id)
        ON DELETE CASCADE,
    CONSTRAINT command_receipts_principal_key
        UNIQUE (principal_type, principal_id, idempotency_key),
    CONSTRAINT command_receipts_principal_type_check
        CHECK (principal_type IN ('USER', 'AGENT')),
    CONSTRAINT command_receipts_route_scope_not_blank CHECK (btrim(route_scope) <> ''),
    CONSTRAINT command_receipts_request_hash_format CHECK (
        request_hash ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT command_receipts_result_state_version_check CHECK (
        result_state_version IS NULL OR result_state_version > 0
    ),
    CONSTRAINT command_receipts_http_status_check CHECK (http_status BETWEEN 100 AND 599),
    CONSTRAINT command_receipts_result_body_object
        CHECK (jsonb_typeof(result_body) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_command_receipts_game
    ON public.command_receipts (game_id)
    WHERE game_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.game_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id uuid NOT NULL,
    state_version bigint NOT NULL,
    last_front_sequence bigint NOT NULL,
    schema_version smallint NOT NULL,
    state_ciphertext bytea NOT NULL,
    nonce bytea NOT NULL,
    key_id varchar(64) NOT NULL,
    checksum char(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT game_snapshots_game_id_fkey
        FOREIGN KEY (game_id)
        REFERENCES public.games (id)
        ON DELETE CASCADE,
    CONSTRAINT game_snapshots_game_state_key UNIQUE (game_id, state_version),
    CONSTRAINT game_snapshots_state_version_check CHECK (state_version > 0),
    CONSTRAINT game_snapshots_front_sequence_check CHECK (last_front_sequence >= 0),
    CONSTRAINT game_snapshots_schema_version_check CHECK (schema_version > 0),
    CONSTRAINT game_snapshots_cipher_material_not_empty CHECK (
        octet_length(state_ciphertext) > 0 AND octet_length(nonce) > 0
    ),
    CONSTRAINT game_snapshots_key_id_not_blank CHECK (btrim(key_id) <> ''),
    CONSTRAINT game_snapshots_checksum_format CHECK (checksum ~ '^[0-9a-f]{64}$')
);

-- Agent job reservation은 외부 호출 전에 영구 저장되며 lease token이 늦게 도착한
-- worker의 결과를 차단한다. GM과 player job은 서로 다른 부분 unique index를 쓴다.
CREATE TABLE IF NOT EXISTS public.agent_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id uuid NOT NULL,
    player_id uuid,
    window_id uuid NOT NULL,
    job_kind varchar(24) NOT NULL,
    reserved_state_version bigint NOT NULL,
    status varchar(16) NOT NULL,
    lease_token uuid NOT NULL,
    lease_expires_at timestamptz NOT NULL,
    normalized_proposal jsonb,
    failure_code varchar(64),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at timestamptz,
    CONSTRAINT agent_jobs_game_id_fkey
        FOREIGN KEY (game_id)
        REFERENCES public.games (id)
        ON DELETE CASCADE,
    CONSTRAINT agent_jobs_player_fkey
        FOREIGN KEY (game_id, player_id)
        REFERENCES public.game_players (game_id, id)
        ON DELETE CASCADE,
    CONSTRAINT agent_jobs_window_fkey
        FOREIGN KEY (game_id, window_id)
        REFERENCES public.action_windows (game_id, id)
        ON DELETE CASCADE,
    CONSTRAINT agent_jobs_kind_check
        CHECK (job_kind IN ('SPEECH', 'NIGHT_ACTION', 'VOTE', 'GM_NARRATION')),
    CONSTRAINT agent_jobs_subject_check CHECK (
        (job_kind = 'GM_NARRATION' AND player_id IS NULL)
        OR (job_kind <> 'GM_NARRATION' AND player_id IS NOT NULL)
    ),
    CONSTRAINT agent_jobs_reserved_version_check CHECK (reserved_state_version > 0),
    CONSTRAINT agent_jobs_status_check
        CHECK (status IN ('RESERVED', 'SUCCEEDED', 'FALLBACK', 'STALE', 'FAILED')),
    CONSTRAINT agent_jobs_proposal_object CHECK (
        normalized_proposal IS NULL OR jsonb_typeof(normalized_proposal) = 'object'
    ),
    CONSTRAINT agent_jobs_terminal_time_check CHECK (
        (status = 'RESERVED' AND completed_at IS NULL)
        OR (status <> 'RESERVED' AND completed_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_jobs_player_window_kind
    ON public.agent_jobs (window_id, player_id, job_kind)
    WHERE player_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_jobs_gm_window_kind
    ON public.agent_jobs (window_id, job_kind)
    WHERE player_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_agent_jobs_game_window
    ON public.agent_jobs (game_id, window_id);
CREATE INDEX IF NOT EXISTS idx_agent_jobs_reserved_lease
    ON public.agent_jobs (lease_expires_at)
    WHERE status = 'RESERVED';

CREATE TABLE IF NOT EXISTS public.agent_capabilities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash char(64) NOT NULL UNIQUE,
    game_id uuid NOT NULL,
    subject_type varchar(16) NOT NULL,
    subject_player_id uuid,
    phase varchar(32) NOT NULL,
    state_version bigint NOT NULL,
    window_id uuid,
    allowed_resources jsonb NOT NULL,
    allowed_tools jsonb NOT NULL,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT agent_capabilities_game_id_fkey
        FOREIGN KEY (game_id)
        REFERENCES public.games (id)
        ON DELETE CASCADE,
    CONSTRAINT agent_capabilities_subject_player_fkey
        FOREIGN KEY (game_id, subject_player_id)
        REFERENCES public.game_players (game_id, id)
        ON DELETE CASCADE,
    CONSTRAINT agent_capabilities_window_fkey
        FOREIGN KEY (game_id, window_id)
        REFERENCES public.action_windows (game_id, id)
        ON DELETE CASCADE,
    CONSTRAINT agent_capabilities_token_hash_format CHECK (
        token_hash ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT agent_capabilities_subject_type_check
        CHECK (subject_type IN ('AI_PLAYER', 'GM')),
    CONSTRAINT agent_capabilities_subject_check CHECK (
        (subject_type = 'AI_PLAYER' AND subject_player_id IS NOT NULL)
        OR (subject_type = 'GM' AND subject_player_id IS NULL)
    ),
    CONSTRAINT agent_capabilities_phase_check CHECK (
        phase IN (
            'ROLE_REVEAL', 'DAY_DISCUSSION', 'NIGHT_ACTION', 'DAY_VOTE',
            'REVOTE', 'FINAL_DISCUSSION', 'FINAL_ACCUSATION', 'ENDED'
        )
    ),
    CONSTRAINT agent_capabilities_state_version_check CHECK (state_version > 0),
    CONSTRAINT agent_capabilities_resources_array
        CHECK (jsonb_typeof(allowed_resources) = 'array'),
    CONSTRAINT agent_capabilities_tools_array
        CHECK (jsonb_typeof(allowed_tools) = 'array'),
    CONSTRAINT agent_capabilities_gm_tools_empty CHECK (
        subject_type <> 'GM' OR allowed_tools = '[]'::jsonb
    ),
    CONSTRAINT agent_capabilities_expiry_check CHECK (expires_at > created_at),
    CONSTRAINT agent_capabilities_revoked_at_check CHECK (
        revoked_at IS NULL OR revoked_at >= created_at
    )
);

CREATE INDEX IF NOT EXISTS idx_agent_capabilities_subject
    ON public.agent_capabilities (game_id, subject_player_id)
    WHERE subject_player_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_agent_capabilities_window
    ON public.agent_capabilities (game_id, window_id)
    WHERE window_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_agent_capabilities_active_expiry
    ON public.agent_capabilities (expires_at)
    WHERE revoked_at IS NULL;

-- 내부 HMAC과 MCP bootstrap nonce는 Redis가 비어 있어도 PostgreSQL의 복합 PK가
-- 최종 replay 방어선이 되도록 하나의 영구 원장에 기록한다.
CREATE TABLE IF NOT EXISTS public.internal_request_nonces (
    scope varchar(24) NOT NULL,
    nonce uuid NOT NULL,
    request_hash char(64) NOT NULL,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT internal_request_nonces_pkey PRIMARY KEY (scope, nonce),
    CONSTRAINT internal_request_nonces_scope_check
        CHECK (scope IN ('ENGINE_HMAC', 'MCP_BOOTSTRAP')),
    CONSTRAINT internal_request_nonces_request_hash_format
        CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT internal_request_nonces_expiry_check CHECK (expires_at > created_at)
);

CREATE INDEX IF NOT EXISTS idx_internal_request_nonces_expires
    ON public.internal_request_nonces (expires_at);

-- outbox는 payload 복사본을 보관하지 않고 commit된 game_event만 참조한다.
CREATE TABLE IF NOT EXISTS public.event_outbox (
    id bigserial PRIMARY KEY,
    game_event_id uuid NOT NULL UNIQUE,
    available_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    published_at timestamptz,
    attempt_count integer NOT NULL DEFAULT 0,
    last_error_code varchar(64),
    CONSTRAINT event_outbox_game_event_id_fkey
        FOREIGN KEY (game_event_id)
        REFERENCES public.game_events (id)
        ON DELETE CASCADE,
    CONSTRAINT event_outbox_attempt_count_check CHECK (attempt_count >= 0),
    CONSTRAINT event_outbox_published_at_check CHECK (
        published_at IS NULL OR published_at >= available_at
    )
);

CREATE INDEX IF NOT EXISTS idx_event_outbox_unpublished_available
    ON public.event_outbox (available_at, id)
    WHERE published_at IS NULL;

CREATE TABLE IF NOT EXISTS public.feedback (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL,
    feedback_type varchar(16) NOT NULL,
    game_id uuid,
    rating smallint NOT NULL,
    comment varchar(1000),
    tags jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT feedback_user_id_fkey
        FOREIGN KEY (user_id)
        REFERENCES public.users (id)
        ON DELETE RESTRICT,
    CONSTRAINT feedback_game_id_fkey
        FOREIGN KEY (game_id)
        REFERENCES public.games (id)
        ON DELETE RESTRICT,
    CONSTRAINT feedback_type_check CHECK (feedback_type IN ('GENERAL', 'GAME')),
    CONSTRAINT feedback_game_scope_check CHECK (
        (feedback_type = 'GENERAL' AND game_id IS NULL)
        OR (feedback_type = 'GAME' AND game_id IS NOT NULL)
    ),
    CONSTRAINT feedback_rating_check CHECK (rating BETWEEN 1 AND 5),
    CONSTRAINT feedback_comment_check CHECK (
        comment IS NULL OR (btrim(comment) <> '' AND char_length(comment) <= 1000)
    ),
    CONSTRAINT feedback_tags_array CHECK (jsonb_typeof(tags) = 'array')
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_feedback_user_game
    ON public.feedback (user_id, game_id)
    WHERE feedback_type = 'GAME';
CREATE INDEX IF NOT EXISTS idx_feedback_user_created
    ON public.feedback (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_game
    ON public.feedback (game_id)
    WHERE game_id IS NOT NULL;

-- 관리자 감사 로그는 조회 흔적만 남기고 IP, header, 응답 payload와 비밀값을
-- 저장하지 않는다. 외부 사용자 삭제와 무관하게 감사 ID를 보존해 FK를 두지 않는다.
CREATE TABLE IF NOT EXISTS public.admin_audit_events (
    id bigserial PRIMARY KEY,
    admin_user_id uuid NOT NULL,
    action varchar(64) NOT NULL,
    target_game_id uuid,
    request_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT admin_audit_events_action_not_blank CHECK (btrim(action) <> '')
);

CREATE INDEX IF NOT EXISTS idx_admin_audit_events_admin_created
    ON public.admin_audit_events (admin_user_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_admin_audit_events_target_game
    ON public.admin_audit_events (target_game_id, created_at DESC)
    WHERE target_game_id IS NOT NULL;

-- 변경 가능한 canonical row의 updated_at은 애플리케이션 시계가 아니라 DB
-- transaction 시각으로 기록한다. 같은 이름의 잘못된 trigger를 만들지 않도록
-- table OID까지 확인한다.
DO $migration$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'set_games_updated_at'
          AND tgrelid = 'public.games'::regclass
          AND NOT tgisinternal
    ) THEN
        CREATE TRIGGER set_games_updated_at
        BEFORE UPDATE ON public.games
        FOR EACH ROW
        EXECUTE FUNCTION public.team4_set_updated_at();
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'set_game_players_updated_at'
          AND tgrelid = 'public.game_players'::regclass
          AND NOT tgisinternal
    ) THEN
        CREATE TRIGGER set_game_players_updated_at
        BEFORE UPDATE ON public.game_players
        FOR EACH ROW
        EXECUTE FUNCTION public.team4_set_updated_at();
    END IF;
END;
$migration$;

COMMIT;
