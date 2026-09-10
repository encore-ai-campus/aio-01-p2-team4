-- 연결 뼈대에서 사용하는 최소 영속 구조다. 실제 ruleset 확장 시 순방향 migration으로 추가한다.
BEGIN;

CREATE TABLE IF NOT EXISTS public.scaffold_games (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- 개발용 X-User-Id를 사용하는 scaffold-v1에서는 identity row가 없어도
    -- 연결 경계를 시험할 수 있어 users FK를 후속 basic-v1에서 추가한다.
    owner_user_id uuid NULL,
    player_count smallint NOT NULL CHECK (player_count BETWEEN 5 AND 9),
    ruleset_version varchar(32) NOT NULL CHECK (ruleset_version = 'scaffold-v1'),
    status varchar(16) NOT NULL CHECK (status IN ('IN_PROGRESS', 'PAUSED')),
    phase varchar(32) NOT NULL CHECK (phase IN ('ROLE_REVEAL', 'PAUSED')),
    state_version bigint NOT NULL DEFAULT 1 CHECK (state_version > 0),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS public.scaffold_operations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id uuid NOT NULL REFERENCES public.scaffold_games (id) ON DELETE CASCADE,
    command varchar(32) NOT NULL CHECK (command IN ('PING', 'BEGIN_GAME', 'PAUSE', 'RESUME')),
    status varchar(16) NOT NULL CHECK (status IN ('COMPLETED', 'FAILED')),
    accepted_version bigint NOT NULL,
    result_version bigint,
    error_code varchar(64),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_scaffold_games_owner_updated
    ON public.scaffold_games (owner_user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_scaffold_operations_game_created
    ON public.scaffold_operations (game_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.scaffold_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    game_id uuid NOT NULL REFERENCES public.scaffold_games (id) ON DELETE CASCADE,
    sequence bigint NOT NULL CHECK (sequence > 0),
    event_type varchar(48) NOT NULL,
    payload jsonb NOT NULL,
    state_version bigint NOT NULL CHECK (state_version > 0),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (game_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_scaffold_events_game_sequence
    ON public.scaffold_events (game_id, sequence);
COMMIT;
