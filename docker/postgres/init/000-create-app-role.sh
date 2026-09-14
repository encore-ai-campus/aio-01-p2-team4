#!/usr/bin/env bash
set -Eeuo pipefail

# POSTGRES_USER는 migration을 실행할 DDL 계정으로 사용한다. 애플리케이션 계정은
# 별도로 만들어 runtime 컨테이너가 schema 변경 권한을 갖지 않도록 분리한다.
: "${APP_DB_USER:=app_user}"
: "${APP_DB_PASSWORD:?APP_DB_PASSWORD must be set}"

psql --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" \
  --set=ON_ERROR_STOP=1 \
  --set=app_user="${APP_DB_USER}" \
  --set=app_password="${APP_DB_PASSWORD}" <<'SQL'
DROP ROLE IF EXISTS :"app_user";
CREATE ROLE :"app_user" LOGIN PASSWORD :'app_password';
SQL
