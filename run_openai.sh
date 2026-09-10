#!/usr/bin/env bash

set -euo pipefail

# 호출한 터미널의 현재 위치와 무관하게 저장소 루트의 .env와 가상환경을 사용한다.
# .env를 source하지 않아 값 안의 셸 문자가 명령으로 해석되는 문제를 피한다.
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ENV_FILE="${PROJECT_ROOT}/.env"
PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
DOTENV_BIN="${PROJECT_ROOT}/.venv/bin/dotenv"
MCP_ROOT="${PROJECT_ROOT}/mcp_server"
MCP_PYTHON_BIN="${MCP_ROOT}/.venv/bin/python"

BACKEND_PORT="${AI_MAFIA_BACKEND_PORT:-18000}"
MCP_PORT="${AI_MAFIA_MCP_PORT:-18100}"
FRONTEND_PORT="${AI_MAFIA_FRONTEND_PORT:-18501}"
BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}"
MCP_BASE_URL="http://127.0.0.1:${MCP_PORT}"
MCP_URL="${MCP_BASE_URL}/mcp"
FRONTEND_URL="http://127.0.0.1:${FRONTEND_PORT}"

validate_port() {
    local name="$1"
    local value="$2"

    # 선행 0을 거부해 Bash가 포트를 8진수로 해석하거나 같은 포트를 서로 다른
    # 문자열로 비교하는 일을 막는다. 최대 자릿수를 먼저 제한해 산술 overflow도 피한다.
    if [[ ! "${value}" =~ ^[0-9]+$ || "${value}" == 0* ]] || (( ${#value} > 5 )); then
        echo "오류: ${name}는 1부터 65535 사이의 포트여야 합니다." >&2
        exit 1
    fi
    if (( value > 65535 )); then
        echo "오류: ${name}는 1부터 65535 사이의 포트여야 합니다." >&2
        exit 1
    fi
}

validate_port "AI_MAFIA_BACKEND_PORT" "${BACKEND_PORT}"
validate_port "AI_MAFIA_MCP_PORT" "${MCP_PORT}"
validate_port "AI_MAFIA_FRONTEND_PORT" "${FRONTEND_PORT}"

if [[ "${BACKEND_PORT}" == "${MCP_PORT}" || "${BACKEND_PORT}" == "${FRONTEND_PORT}" \
        || "${MCP_PORT}" == "${FRONTEND_PORT}" ]]; then
    echo "오류: Backend, MCP, Front 포트는 서로 달라야 합니다." >&2
    exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
    echo "오류: 저장소 루트의 .env 파일이 없습니다." >&2
    exit 1
fi

if [[ ! -x "${PYTHON_BIN}" || ! -x "${DOTENV_BIN}" ]]; then
    echo "오류: 루트 가상환경이 준비되지 않았습니다. 먼저 'uv sync --locked --dev'를 실행하세요." >&2
    exit 1
fi

if [[ ! -x "${MCP_PYTHON_BIN}" ]]; then
    echo "오류: MCP 가상환경이 준비되지 않았습니다. 먼저 'uv sync --project mcp_server --locked --dev'를 실행하세요." >&2
    exit 1
fi

cd "${PROJECT_ROOT}"

read_required_env_value() {
    local name="$1"

    # python-dotenv로 한 값만 읽어 셸 source의 명령 해석을 피한다. 값 자체는 출력이나
    # 로그에 남기지 않고 Backend 자식 프로세스의 환경 변수로만 전달한다.
    "${PYTHON_BIN}" - "${ENV_FILE}" "${name}" <<'PY'
from pathlib import Path
import sys

from dotenv import dotenv_values

value = dotenv_values(Path(sys.argv[1])).get(sys.argv[2])
if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
    raise SystemExit(f"오류: 루트 .env에 {sys.argv[2]} 설정이 필요합니다.")
print(value.strip(), end="")
PY
}

STORAGE_MODE="$("${PYTHON_BIN}" - "${ENV_FILE}" <<'PY'
from pathlib import Path
import sys

from dotenv import dotenv_values

mode = dotenv_values(Path(sys.argv[1])).get("AI_MAFIA_STORAGE_MODE", "team")
if mode not in {"isolated", "team"}:
    raise SystemExit("오류: AI_MAFIA_STORAGE_MODE는 isolated 또는 team이어야 합니다.")
print(mode, end="")
PY
)"

# 팀 DB는 기본 테스트 저장소다. 명시적으로 isolated를 선택한 경우에만 별도
# 저장소를 사용하며, DB와 Redis를 같은 설정 묶음에서 선택해 게임 데이터를 섞지 않는다.
if [[ "${STORAGE_MODE}" == "team" ]]; then
    RUNTIME_DATABASE_URL="$(read_required_env_value TEAM_DATABASE_URL)"
    RUNTIME_REDIS_URL="$(read_required_env_value REDIS_URL)"
else
    RUNTIME_DATABASE_URL="$(read_required_env_value AI_MAFIA_DATABASE_URL)"
    RUNTIME_REDIS_URL="$(read_required_env_value AI_MAFIA_REDIS_URL)"
fi

# 자격증명이 달라도 host·port·database가 같으면 동일한 worker 원장을 공유한다.
# 접속 URL 원문은 셸 출력이나 명령행 인자로 보내지 않고 .env 안에서만 비교한다.
"${PYTHON_BIN}" - "${ENV_FILE}" <<'PY'
from pathlib import Path
import sys
from urllib.parse import unquote, urlsplit

from dotenv import dotenv_values

values = dotenv_values(Path(sys.argv[1]))
isolated = values.get("AI_MAFIA_DATABASE_URL")
shared = values.get("TEAM_DATABASE_URL")

def target(value: str) -> tuple[str, str | None, int, str]:
    parsed = urlsplit(value)
    return parsed.scheme.lower(), parsed.hostname, parsed.port or 5432, unquote(parsed.path)

if (values.get("AI_MAFIA_STORAGE_MODE", "team") == "isolated"
        and isinstance(isolated, str) and isinstance(shared, str)
        and target(isolated) == target(shared)):
    raise SystemExit("오류: AI_MAFIA_DATABASE_URL은 TEAM_DATABASE_URL과 다른 격리 DB여야 합니다.")
PY

if [[ "${1:-}" == "--check" ]]; then
    shift
    if (( $# > 0 )); then
        echo "오류: --check에는 추가 인자를 사용할 수 없습니다." >&2
        exit 1
    fi

    # 실제 API를 호출하지 않고 Backend 설정 생성과 세 런타임의 import까지 수행한다.
    # 설정 객체는 API 키를 repr에서 제외하며 이 출력도 Provider와 모델 이름만 표시한다.
    "${DOTENV_BIN}" -f "${ENV_FILE}" run --override -- \
        env TEAM_DATABASE_URL="${RUNTIME_DATABASE_URL}" DATABASE_URL="${RUNTIME_DATABASE_URL}" \
        REDIS_URL="${RUNTIME_REDIS_URL}" LLM_PROVIDER=openai MCP_SERVER_URL="${MCP_BASE_URL}" \
        "${PYTHON_BIN}" - <<'PY'
import psycopg
import redis

from backend.app.core.config import Settings

settings = Settings.from_env()
try:
    with psycopg.connect(settings.effective_database_url, connect_timeout=3) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT to_regclass('public.games') IS NOT NULL, "
                "EXISTS (SELECT 1 FROM public.scenario_catalog WHERE active = TRUE), "
                "EXISTS (SELECT 1 FROM public.agent_personas WHERE active = TRUE)"
            )
            games_ready, scenarios_ready, personas_ready = cursor.fetchone()
    redis_client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=3)
    try:
        redis_client.ping()
    finally:
        redis_client.close()
except Exception:
    raise SystemExit("오류: 선택한 PostgreSQL·Redis 연결과 migration 상태를 확인하세요.") from None
if not all((games_ready, scenarios_ready, personas_ready)):
    raise SystemExit("오류: 선택한 DB에 AI 마피아 migration과 seed가 필요합니다.")
print(f"OpenAI 실행 설정 확인 완료: provider={settings.llm_provider}, model={settings.openai_model}")
print("선택한 저장소 확인 완료: PostgreSQL, Redis 설정")
PY
    "${PYTHON_BIN}" -c 'import openai, streamlit, uvicorn'
    (
        cd "${MCP_ROOT}"
        "${MCP_PYTHON_BIN}" -c 'import uvicorn; from mcp.server.fastmcp import FastMCP; import mafia_game.main'
    )
    echo "동시 실행 구성 확인 완료: Backend, MCP, Front"
    exit 0
fi

if (( $# > 0 )); then
    echo "사용법: ./run_openai.sh [--check]" >&2
    exit 1
fi

# 일부 구성요소만 뜬 뒤 충돌하는 상황을 막기 위해 세 포트를 시작 전에 함께 검사한다.
"${PYTHON_BIN}" - "${BACKEND_PORT}" "${MCP_PORT}" "${FRONTEND_PORT}" <<'PY'
import socket
import sys

for port_text in sys.argv[1:]:
    port = int(port_text)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        # Uvicorn과 Streamlit의 재시작 조건에 맞춰 종료 직후 TIME_WAIT은 허용하되,
        # 실제로 LISTEN 중인 프로세스와의 충돌은 bind 실패로 구분한다.
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(("127.0.0.1", port))
        except OSError:
            raise SystemExit(f"오류: 127.0.0.1:{port} 포트가 이미 사용 중입니다.") from None
PY

CHILD_PIDS=()
CHILD_NAMES=()
CLEANUP_STARTED=0

cleanup() {
    local pid

    if (( CLEANUP_STARTED )); then
        return
    fi
    CLEANUP_STARTED=1
    trap - INT TERM EXIT

    for pid in "${CHILD_PIDS[@]}"; do
        kill -TERM "${pid}" 2>/dev/null || true
    done
    for pid in "${CHILD_PIDS[@]}"; do
        wait "${pid}" 2>/dev/null || true
    done
}

handle_signal() {
    local exit_code="$1"
    exit "${exit_code}"
}

clear_private_environment() {
    # Front와 MCP에는 공개 Backend 주소만 필요하다. 호출한 셸에 비밀 환경 변수가
    # 있더라도 별도 프로세스 경계로 전달하지 않아 구성요소별 소유권을 지킨다.
    unset OPENAI_API_KEY GEMINI_API_KEY
    unset TEAM_DATABASE_URL DATABASE_URL DATABASE_MIGRATION_URL REDIS_URL
    unset GAME_STATE_KEYRING_FILE GAME_STATE_ACTIVE_KEY_ID ADMIN_USER_IDS
}

wait_for_first_exit() {
    local index
    local pid

    # macOS 기본 Bash 3.2에는 wait -n이 없으므로 자식 상태를 짧게 확인한다.
    # 종료된 프로세스는 wait로 회수하고 그 종료 코드를 호출자에게 전달한다.
    while true; do
        index=0
        while (( index < ${#CHILD_PIDS[@]} )); do
            pid="${CHILD_PIDS[${index}]}"
            if ! kill -0 "${pid}" 2>/dev/null; then
                EXITED_COMPONENT="${CHILD_NAMES[${index}]}"
                wait "${pid}"
                return $?
            fi
            index=$((index + 1))
        done
        sleep 1
    done
}

trap 'handle_signal 130' INT
trap 'handle_signal 143' TERM
trap cleanup EXIT

# Provider 선택값만 OpenAI로 고정하고 키·모델·DB 등 Backend 설정은 루트 .env에서 읽는다.
"${DOTENV_BIN}" -f "${ENV_FILE}" run --override -- \
    env TEAM_DATABASE_URL="${RUNTIME_DATABASE_URL}" DATABASE_URL="${RUNTIME_DATABASE_URL}" \
    REDIS_URL="${RUNTIME_REDIS_URL}" LLM_PROVIDER=openai MCP_SERVER_URL="${MCP_BASE_URL}" \
    "${PYTHON_BIN}" -m uvicorn backend.app.main:app \
    --reload --reload-dir "${PROJECT_ROOT}/backend/app" \
    --host 127.0.0.1 --port "${BACKEND_PORT}" &
CHILD_PIDS+=("$!")
CHILD_NAMES+=("Backend")

(
    clear_private_environment
    cd "${MCP_ROOT}"
    exec env BACKEND_API_URL="${BACKEND_URL}" MCP_LISTEN_HOST=127.0.0.1 MCP_LISTEN_PORT="${MCP_PORT}" \
        "${MCP_PYTHON_BIN}" -m mafia_game
) &
CHILD_PIDS+=("$!")
CHILD_NAMES+=("MCP")

(
    clear_private_environment
    cd "${PROJECT_ROOT}"
    exec env BACKEND_API_URL="${BACKEND_URL}" "${PYTHON_BIN}" -m streamlit run \
        frontend_user/app.py --server.address 127.0.0.1 --server.port "${FRONTEND_PORT}"
) &
CHILD_PIDS+=("$!")
CHILD_NAMES+=("Front")

echo "Backend: ${BACKEND_URL} (OpenAI Provider)"
echo "저장소 모드: ${STORAGE_MODE}"
echo "MCP:     ${MCP_URL}"
echo "Front:   ${FRONTEND_URL}"
echo "종료하려면 Ctrl+C를 누르세요."

set +e
wait_for_first_exit
EXIT_STATUS=$?
set -e

if (( EXIT_STATUS == 0 )); then
    echo "${EXITED_COMPONENT} 프로세스가 종료되어 전체 실행을 정리합니다."
else
    echo "오류: ${EXITED_COMPONENT} 프로세스가 종료 코드 ${EXIT_STATUS}로 끝나 전체 실행을 정리합니다." >&2
fi
exit "${EXIT_STATUS}"
