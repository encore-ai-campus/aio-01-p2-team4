-- Team4 OAuth 로그인에 필요한 내부 사용자와 외부 신원 연결 스키마입니다.
-- 애플리케이션은 이메일이 아닌 (provider, provider_subject)를 외부 계정의
-- 불변 키로 사용합니다. access token, refresh token, ID token 원문은 이
-- 스키마 어디에도 저장하지 않습니다.
--
-- 파일 전체를 하나의 명시적 트랜잭션으로 묶어 테이블, 인덱스, 트리거 중
-- 일부만 생성된 상태가 커밋되지 않게 합니다. IF NOT EXISTS와 조건부 트리거
-- 생성으로 같은 마이그레이션을 다시 실행해도 기존 객체를 중복 생성하지 않습니다.
BEGIN;

-- 사용자 및 연결 레코드의 UUID를 DB에서 생성하기 위한 확장입니다. 이미 같은
-- 데이터베이스에 설치돼 있으면 아무 작업도 하지 않습니다.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- users는 애플리케이션 내부 계정의 현재 프로필과 활성 상태를 보관합니다.
-- 이메일은 NULL과 중복을 허용하며 로그인 계정 연결 키가 아닙니다. 외부
-- 제공자와의 영속적인 연결 정보는 아래 oauth_identities에 분리합니다.
CREATE TABLE IF NOT EXISTS public.users (
    -- 내부 관계와 API 응답에서 사용할 애플리케이션 고유 식별자입니다.
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- 다음 세 필드는 OIDC 재로그인 때 최신 claim으로 갱신할 수 있는 프로필입니다.
    email text,
    display_name text,
    avatar_url text,
    -- false로 전환된 기존 사용자는 저장소에서 프로필 갱신과 로그인을 모두 거부합니다.
    is_active boolean NOT NULL DEFAULT true,
    last_login_at timestamptz,
    -- updated_at은 아래 공용 BEFORE UPDATE 트리거가 자동으로 관리합니다.
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- 선택 프로필은 NULL을 허용하지만 빈 문자열과 비정상적으로 긴 값은 막습니다.
    CONSTRAINT users_email_not_blank
        CHECK (
            email IS NULL
            OR (btrim(email) <> '' AND char_length(email) <= 320)
        ),
    CONSTRAINT users_display_name_not_blank
        CHECK (
            display_name IS NULL
            OR (btrim(display_name) <> '' AND char_length(display_name) <= 120)
        ),
    -- UI에서 외부 URL을 이미지 src로 사용하므로 평문 HTTP 및 기타 스킴을 거부합니다.
    CONSTRAINT users_avatar_url_is_https
        CHECK (
            avatar_url IS NULL
            OR (avatar_url ~ '^https://' AND char_length(avatar_url) <= 2048)
        ),
    -- 감사용 타임스탬프가 레코드 생성 시점보다 과거로 내려가지 않게 합니다.
    CONSTRAINT users_updated_at_not_before_created_at
        CHECK (updated_at >= created_at)
);

-- oauth_identities는 OIDC 제공자의 한 계정과 내부 users 행을 연결합니다.
-- provider_subject는 OIDC의 sub claim이며 제공자 안에서 변하지 않는 값입니다.
-- 이메일이 바뀌어도 같은 (provider, sub)를 통해 동일한 내부 사용자를 찾습니다.
CREATE TABLE IF NOT EXISTS public.oauth_identities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL,
    provider text NOT NULL,
    provider_subject text NOT NULL,
    -- 아래 값들은 마지막 로그인 claim의 스냅샷입니다. 식별키로 사용하지 않습니다.
    provider_email text,
    email_verified boolean,
    last_login_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- 내부 사용자를 명시적으로 삭제하면 고아 외부 연결도 함께 제거합니다.
    CONSTRAINT oauth_identities_user_id_fkey
        FOREIGN KEY (user_id)
        REFERENCES public.users (id)
        ON DELETE CASCADE,
    -- 애플리케이션 advisory lock과 별개로 DB가 외부 계정 중복 연결을 최종 차단합니다.
    CONSTRAINT oauth_identities_provider_subject_key
        UNIQUE (provider, provider_subject),
    -- 저장소에서 소문자로 정규화한 provider 코드만 허용합니다.
    CONSTRAINT oauth_identities_provider_format
        CHECK (provider ~ '^[a-z0-9][a-z0-9_-]{0,63}$'),
    -- sub는 계정 연결의 핵심 키이므로 공백일 수 없고 저장 길이를 제한합니다.
    CONSTRAINT oauth_identities_provider_subject_not_blank
        CHECK (
            btrim(provider_subject) <> ''
            AND char_length(provider_subject) <= 512
        ),
    CONSTRAINT oauth_identities_provider_email_not_blank
        CHECK (
            provider_email IS NULL
            OR (btrim(provider_email) <> '' AND char_length(provider_email) <= 320)
        ),
    CONSTRAINT oauth_identities_updated_at_not_before_created_at
        CHECK (updated_at >= created_at)
);

-- 이메일은 연락처/프로필 속성일 뿐 계정 식별키가 아닙니다. 대소문자를
-- 무시한 운영 조회를 돕되 서로 다른 계정의 동일 이메일을 허용하는 비고유
-- 부분 인덱스로 둡니다.
CREATE INDEX IF NOT EXISTS idx_users_email_lower
    ON public.users (lower(email))
    WHERE email IS NOT NULL;

-- 한 내부 사용자에 연결된 외부 제공자 목록을 조회할 때 전체 테이블 스캔을 피합니다.
CREATE INDEX IF NOT EXISTS idx_oauth_identities_user_id
    ON public.oauth_identities (user_id);

-- 두 테이블의 updated_at을 애플리케이션 시계가 아니라 PostgreSQL 트랜잭션의
-- 현재 시각으로 일관되게 기록하는 공용 트리거 함수입니다.
CREATE OR REPLACE FUNCTION public.team4_set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    NEW.updated_at := CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$function$;

-- PostgreSQL에는 CREATE TRIGGER IF NOT EXISTS가 없으므로 카탈로그를 확인한 뒤
-- 필요한 트리거만 생성합니다. 이름뿐 아니라 대상 테이블 OID와 내부 트리거
-- 여부까지 검사해 재실행 시 잘못된 객체를 중복 생성하지 않습니다.
DO $migration$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'set_users_updated_at'
          AND tgrelid = 'public.users'::regclass
          AND NOT tgisinternal
    ) THEN
        CREATE TRIGGER set_users_updated_at
        BEFORE UPDATE ON public.users
        FOR EACH ROW
        EXECUTE FUNCTION public.team4_set_updated_at();
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'set_oauth_identities_updated_at'
          AND tgrelid = 'public.oauth_identities'::regclass
          AND NOT tgisinternal
    ) THEN
        CREATE TRIGGER set_oauth_identities_updated_at
        BEFORE UPDATE ON public.oauth_identities
        FOR EACH ROW
        EXECUTE FUNCTION public.team4_set_updated_at();
    END IF;
END;
$migration$;

COMMIT;
