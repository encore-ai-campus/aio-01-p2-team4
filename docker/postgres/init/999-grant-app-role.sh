#!/usr/bin/env bash
set -Eeuo pipefail

: "${APP_DB_USER:=app_user}"

# migration은 POSTGRES_USER가 소유하므로 애플리케이션에는 필요한 DML과 sequence
# 권한만 부여한다. Redis와 달리 PostgreSQL은 최종 게임 원장이므로 권한을 넓히지 않는다.
psql --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" \
  --set=ON_ERROR_STOP=1 \
  --set=db_name="${POSTGRES_DB}" \
  --set=app_user="${APP_DB_USER}" <<'SQL'
GRANT CONNECT ON DATABASE :"db_name" TO :"app_user";
GRANT USAGE ON SCHEMA public TO :"app_user";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO :"app_user";
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO :"app_user";
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO :"app_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO :"app_user";
SQL
