-- 기존 제출 행과 010을 보존하고 인간이 명시 사용한 투표 능력 조합만 추가 허용한다.
BEGIN;

ALTER TABLE public.action_submissions
    DROP CONSTRAINT IF EXISTS action_submissions_ability_id_check;

ALTER TABLE public.action_submissions
    ADD CONSTRAINT action_submissions_ability_id_check CHECK (
        ability_id IS NULL OR
        (ability_id = 'night.attack.v1' AND action_type = 'ATTACK') OR
        (ability_id = 'night.investigate.v1' AND action_type = 'INVESTIGATE') OR
        (ability_id = 'night.protect.v1' AND action_type = 'PROTECT') OR
        (ability_id = 'vote.triple.v1' AND action_type = 'VOTE' AND source = 'HUMAN')
    );

COMMIT;
