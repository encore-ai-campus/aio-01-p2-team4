-- 기존 게임은 STANDARD로 유지하면서 HUMAN 자유 직업 snapshot 컬럼만 순방향 추가한다.
BEGIN;

ALTER TABLE public.games
    ADD COLUMN IF NOT EXISTS mode varchar(16) NOT NULL DEFAULT 'STANDARD';

DO $migration$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'games_mode_check' AND conrelid = 'public.games'::regclass
    ) THEN
        ALTER TABLE public.games ADD CONSTRAINT games_mode_check
            CHECK (mode IN ('STANDARD', 'CUSTOM_ROLE'));
    END IF;
END;
$migration$;

ALTER TABLE public.game_players
    ADD COLUMN IF NOT EXISTS custom_role_name varchar(40),
    ADD COLUMN IF NOT EXISTS custom_role_catalog_version varchar(32),
    ADD COLUMN IF NOT EXISTS custom_ability_ids jsonb;

DO $migration$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'game_players_custom_role_snapshot_check'
          AND conrelid = 'public.game_players'::regclass
    ) THEN
        ALTER TABLE public.game_players
            ADD CONSTRAINT game_players_custom_role_snapshot_check CHECK (
                (custom_role_name IS NULL AND custom_role_catalog_version IS NULL AND custom_ability_ids IS NULL)
                OR (
                    kind = 'HUMAN' AND custom_role_name IS NOT NULL
                    AND custom_role_catalog_version IS NOT NULL AND custom_ability_ids IS NOT NULL
                    AND btrim(custom_role_name) <> ''
                    AND custom_role_catalog_version = 'custom-role-v1'
                    AND jsonb_typeof(custom_ability_ids) = 'array'
                    AND jsonb_array_length(custom_ability_ids) BETWEEN 1 AND 3
                )
            );
    END IF;
END;
$migration$;

-- 과거·표준 제출은 NULL을 유지하고 custom 선택만 versioned ID로 기록한다.
ALTER TABLE public.action_submissions
    ADD COLUMN IF NOT EXISTS ability_id varchar(32);

DO $migration$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'action_submissions_ability_id_check'
          AND conrelid = 'public.action_submissions'::regclass
    ) THEN
        ALTER TABLE public.action_submissions
            ADD CONSTRAINT action_submissions_ability_id_check CHECK (
                ability_id IS NULL OR
                (ability_id = 'night.attack.v1' AND action_type = 'ATTACK') OR
                (ability_id = 'night.investigate.v1' AND action_type = 'INVESTIGATE') OR
                (ability_id = 'night.protect.v1' AND action_type = 'PROTECT')
            );
    END IF;
END;
$migration$;

COMMIT;
