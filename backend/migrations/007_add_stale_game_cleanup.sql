-- 진행 중 게임의 마지막 사용자 동작을 별도로 추적해 AI·자동 진행이 보존 시간을
-- 늘리지 않게 한다. 기존 행은 공개 USER command receipt를 우선 사용하고, 해당
-- 원장이 없는 초기 데이터는 게임 생성 시각부터 15분을 계산한다.
BEGIN;

ALTER TABLE public.games
    ADD COLUMN IF NOT EXISTS last_user_action_at timestamptz;

-- 이력 보정은 실제 게임 동작이 아니므로 목록 정렬에 쓰는 updated_at을 보존한다.
-- ALTER TABLE의 배타 잠금 안에서 이 트리거만 잠시 끄며 오류 시 transaction 전체가
-- 되돌아간다. FK·검증 트리거는 계속 활성 상태이고 commit 전에 원래 갱신 동작을 복구한다.
ALTER TABLE public.games DISABLE TRIGGER set_games_updated_at;

WITH last_user_actions AS (
    SELECT
        game.id,
        GREATEST(
            game.created_at,
            COALESCE(MAX(receipt.created_at), game.created_at)
        ) AS occurred_at
    FROM public.games AS game
    LEFT JOIN public.command_receipts AS receipt
      ON receipt.game_id = game.id
     AND receipt.principal_type = 'USER'
     AND receipt.http_status BETWEEN 200 AND 299
     AND (
         receipt.route_scope = 'POST /api/v1/games'
         OR receipt.route_scope = 'POST /api/v1/games/' || game.id::text || '/commands'
     )
    GROUP BY game.id, game.created_at
)
UPDATE public.games AS game
SET last_user_action_at = action.occurred_at
FROM last_user_actions AS action
WHERE game.id = action.id
  AND game.last_user_action_at IS NULL;

ALTER TABLE public.games ENABLE TRIGGER set_games_updated_at;

ALTER TABLE public.games
    ALTER COLUMN last_user_action_at SET DEFAULT CURRENT_TIMESTAMP,
    ALTER COLUMN last_user_action_at SET NOT NULL;

DO $migration$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'games_last_user_action_not_before_created_at'
          AND conrelid = 'public.games'::regclass
    ) THEN
        ALTER TABLE public.games
            ADD CONSTRAINT games_last_user_action_not_before_created_at
            CHECK (last_user_action_at >= created_at);
    END IF;
END;
$migration$;

CREATE INDEX IF NOT EXISTS idx_games_stale_in_progress
    ON public.games (last_user_action_at, id)
    WHERE status = 'IN_PROGRESS';

COMMIT;
