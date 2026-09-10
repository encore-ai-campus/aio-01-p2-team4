$ErrorActionPreference = "Stop"

# 현재 터미널 위치와 무관하게 이 파일이 있는 저장소 루트를 기준으로 실행합니다.
# .env를 PowerShell 명령으로 실행하지 않아 값 안의 셸 문자가 코드로 해석되지 않습니다.
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvFile = Join-Path $ProjectRoot ".env"
$PythonBin = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$McpRoot = Join-Path $ProjectRoot "mcp_server"
$McpPythonBin = Join-Path $McpRoot ".venv\Scripts\python.exe"

function Fail([string]$Message) { [Console]::Error.WriteLine($Message); exit 1 }

function Get-DotEnvValue([string]$Name, [switch]$Required) {
    if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) { Fail "오류: 저장소 루트의 .env 파일이 없습니다." }
    # 따옴표·주석·export·변수 참조는 sh와 같은 python-dotenv 규칙으로 읽습니다.
    # JSON으로 값 하나만 회수해 줄 분리나 셸 해석을 피하고 원문은 출력하지 않습니다.
    $readValue = @'
import json
import logging
import sys

from dotenv import dotenv_values

logging.getLogger("dotenv.main").disabled = True
try:
    value = dotenv_values(sys.argv[1]).get(sys.argv[2])
except (OSError, UnicodeError, ValueError):
    raise SystemExit(1) from None
if isinstance(value, str):
    if "\n" in value or "\r" in value or "\x00" in value:
        raise SystemExit(1)
    value = value.strip()
print(json.dumps(value))
'@
    # Windows PowerShell 5.1의 명령행 따옴표 재해석을 피하도록 ASCII Python 코드를
    # 표준 입력으로 전달합니다. 값의 비 ASCII 문자는 JSON escape로 왕복합니다.
    $raw = $readValue | & $PythonBin - $EnvFile $Name
    if ($LASTEXITCODE -ne 0) { Fail "오류: 루트 .env의 $Name 설정을 읽지 못했습니다." }
    $value = ConvertFrom-Json -InputObject ($raw -join "`n")
    if ($Required -and [string]::IsNullOrWhiteSpace($value)) { Fail "오류: 루트 .env에 $Name 설정이 필요합니다." }
    return $value
}

function Get-Port([string]$Name, [int]$Default) {
    $raw = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($raw)) { $raw = [string]$Default }
    $port = 0
    if (-not [int]::TryParse($raw, [ref]$port) -or $port -lt 1 -or $port -gt 65535 -or $raw -match '^0\d') {
        Fail "오류: $Name은 1부터 65535 사이의 포트여야 합니다."
    }
    return $port
}

$BackendPort = Get-Port "AI_MAFIA_BACKEND_PORT" 18000
$McpPort = Get-Port "AI_MAFIA_MCP_PORT" 18100
$FrontendPort = Get-Port "AI_MAFIA_FRONTEND_PORT" 18501
if (($BackendPort -eq $McpPort) -or ($BackendPort -eq $FrontendPort) -or ($McpPort -eq $FrontendPort)) { Fail "오류: Backend, MCP, Front 포트는 서로 달라야 합니다." }
if (-not (Test-Path -LiteralPath $PythonBin -PathType Leaf)) { Fail "오류: 루트 Windows 가상환경이 준비되지 않았습니다. 먼저 'uv sync --locked --dev'를 실행하세요." }
if (-not (Test-Path -LiteralPath $McpPythonBin -PathType Leaf)) { Fail "오류: MCP Windows 가상환경이 준비되지 않았습니다. 먼저 'uv sync --project mcp_server --locked --dev'를 실행하세요." }

function Test-PythonInterpreter([string]$Path) {
    # PowerShell 전체 정책은 Stop으로 유지하되, 실행 파일 점검의 stderr만 여기서
    # 소비합니다. 호출자에게는 아래의 한국어 원인 메시지만 보여 주기 위함입니다.
    $ErrorActionPreference = "Continue"
    & $Path -c "import sys" *> $null
    return ($LASTEXITCODE -eq 0)
}

# 실행 파일이 있어도 pyvenv.cfg가 가리키는 원본 Python이 삭제되었거나 실행 권한이
# 없으면 프로세스를 만들 수 없습니다. import 단계까지 진행한 뒤 모호한 오류를 내지
# 않도록 두 가상환경의 인터프리터 자체를 먼저 확인합니다.
if (-not (Test-PythonInterpreter $PythonBin)) {
    Fail "오류: 루트 .venv의 Python 실행기를 시작할 수 없습니다. 'uv sync --locked --dev'로 가상환경을 다시 준비하세요."
}
if (-not (Test-PythonInterpreter $McpPythonBin)) {
    Fail "오류: MCP .venv의 Python 실행기를 시작할 수 없습니다. 'uv sync --project mcp_server --locked --dev'로 가상환경을 다시 준비하세요."
}

$StorageMode = Get-DotEnvValue "AI_MAFIA_STORAGE_MODE"
if ($null -eq $StorageMode) { $StorageMode = "team" }
if ($StorageMode -cnotin @("isolated", "team")) { Fail "오류: AI_MAFIA_STORAGE_MODE는 isolated 또는 team이어야 합니다." }
if ($StorageMode -eq "team") {
    $RuntimeDatabaseUrl = Get-DotEnvValue "TEAM_DATABASE_URL" -Required
    $RuntimeRedisUrl = Get-DotEnvValue "REDIS_URL" -Required
} else {
    $RuntimeDatabaseUrl = Get-DotEnvValue "AI_MAFIA_DATABASE_URL" -Required
    $RuntimeRedisUrl = Get-DotEnvValue "AI_MAFIA_REDIS_URL" -Required

    # 계정이 달라도 host·port·database가 같으면 팀 원장을 공유합니다. sh와 같은
    # 대상 비교를 파일 안에서 수행해 DB URL이 프로세스 인자나 오류에 남지 않습니다.
    $checkIsolatedTarget = @'
import logging
import sys
from urllib.parse import unquote, urlsplit

from dotenv import dotenv_values

logging.getLogger("dotenv.main").disabled = True

def target(value):
    parsed = urlsplit(value.strip())
    return parsed.scheme.lower(), parsed.hostname, parsed.port or 5432, unquote(parsed.path)

try:
    values = dotenv_values(sys.argv[1])
    shared = values.get("TEAM_DATABASE_URL")
    if isinstance(shared, str) and shared.strip():
        if target(values["AI_MAFIA_DATABASE_URL"]) == target(shared):
            raise SystemExit(2)
except (OSError, UnicodeError, ValueError):
    raise SystemExit(1) from None
'@
    $checkIsolatedTarget | & $PythonBin - $EnvFile
    if ($LASTEXITCODE -eq 2) { Fail "오류: AI_MAFIA_DATABASE_URL은 TEAM_DATABASE_URL과 다른 격리 DB여야 합니다." }
    if ($LASTEXITCODE -ne 0) { Fail "오류: 격리 DB 대상 확인에 실패했습니다." }
}

$BackendUrl = "http://127.0.0.1:$BackendPort"
$McpBaseUrl = "http://127.0.0.1:$McpPort"
$FrontendUrl = "http://127.0.0.1:$FrontendPort"
if ($args.Count -gt 1 -or ($args.Count -eq 1 -and $args[0] -ne "--check")) { Fail "사용법: run_openai.bat [--check]" }

if ($args.Count -eq 1) {
    # --check는 외부 API 호출 없이 세 런타임의 핵심 import만 확인합니다.
    Push-Location $ProjectRoot
    try { & $PythonBin -c "import openai, psycopg, redis, streamlit, uvicorn; from backend.app.core.config import Settings" }
    finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { Fail "오류: Backend 의존성 import 확인에 실패했습니다." }
    Push-Location $McpRoot
    try { & $McpPythonBin -c "import uvicorn; from mcp.server.fastmcp import FastMCP; import mafia_game.main" }
    finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { Fail "오류: MCP 의존성 import 확인에 실패했습니다." }
    Write-Output "의존성 import 확인 완료: Backend, MCP, Front"
    Write-Output "저장소 선택: $StorageMode (.env 필수값 읽기 완료)"
    Write-Output "미검사: Settings.from_env 설정 검증, PostgreSQL·Redis 연결, migration·seed, 포트와 실제 기동, OpenAI API"
    exit 0
}

# 실제 프로세스를 시작하기 전에 세 포트를 모두 bind해 부분 기동을 방지합니다.
$portCheck = "import socket,sys; [((lambda s,p:(s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1),s.bind(('127.0.0.1',p)),s.close()))(socket.socket(),int(p))) for p in sys.argv[1:]]"
& $PythonBin -c $portCheck $BackendPort $McpPort $FrontendPort
if ($LASTEXITCODE -ne 0) { Fail "오류: Backend, MCP, Front 포트 중 하나가 이미 사용 중입니다." }

# 제거 목록과 덮어쓸 키를 함께 보관해 실패·Ctrl+C 종료 후 호출자의 환경도 복구합니다.
# 별칭 DSN과 과거 인증 secret도 현재의 최소 MCP·Front runtime에는 전달하지 않습니다.
$PrivateEnvironment = @(
    "TEAM_DATABASE_URL", "DATABASE_URL", "DATABASE_MIGRATION_URL", "DATABASE_NAME", "REDIS_URL",
    "AI_MAFIA_DATABASE_URL", "AI_MAFIA_REDIS_URL", "OPENAI_API_KEY", "GEMINI_API_KEY",
    "GAME_STATE_KEYRING_FILE", "GAME_STATE_ACTIVE_KEY_ID", "ADMIN_USER_IDS",
    "MCP_SERVER_AUTH_SECRET", "ENGINE_INTERNAL_API_SECRET",
    "LLM_PROVIDER", "MCP_SERVER_URL"
)
$old = @{}
foreach ($name in ($PrivateEnvironment + @("BACKEND_API_URL", "MCP_LISTEN_HOST", "MCP_LISTEN_PORT"))) {
    $old[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}
$processes = @()
try {
    $env:TEAM_DATABASE_URL = $RuntimeDatabaseUrl
    $env:DATABASE_URL = $RuntimeDatabaseUrl
    $env:REDIS_URL = $RuntimeRedisUrl
    $env:LLM_PROVIDER = "openai"
    $env:MCP_SERVER_URL = $McpBaseUrl
    # Front·테스트 편집은 Backend를 재시작하지 않아 진행 중 API 요청을 끊지 않는다.
    $ReloadDirectory = '"' + (Join-Path $ProjectRoot "backend\app") + '"'
    $processes += Start-Process $PythonBin -ArgumentList @("-m", "uvicorn", "backend.app.main:app", "--reload", "--reload-dir", $ReloadDirectory, "--host", "127.0.0.1", "--port", "$BackendPort") -WorkingDirectory $ProjectRoot -PassThru -NoNewWindow

    # MCP와 Front에는 Backend 공개 주소만 전달하고 DB·Redis·LLM 관련 값은 제거합니다.
    foreach ($name in $PrivateEnvironment) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue }
    $env:BACKEND_API_URL = $BackendUrl
    $env:MCP_LISTEN_HOST = "127.0.0.1"
    $env:MCP_LISTEN_PORT = "$McpPort"
    $processes += Start-Process $McpPythonBin -ArgumentList @("-m", "mafia_game") -WorkingDirectory $McpRoot -PassThru -NoNewWindow
    Remove-Item Env:MCP_LISTEN_HOST,Env:MCP_LISTEN_PORT -ErrorAction SilentlyContinue
    $processes += Start-Process $PythonBin -ArgumentList @("-m", "streamlit", "run", "frontend_user/app.py", "--server.address", "127.0.0.1", "--server.port", "$FrontendPort") -WorkingDirectory $ProjectRoot -PassThru -NoNewWindow

    Write-Output "Backend: $BackendUrl (OpenAI Provider)"
    Write-Output "저장소 모드: $StorageMode"
    Write-Output "MCP:     $McpBaseUrl/mcp"
    Write-Output "Front:   $FrontendUrl"
    Write-Output "종료하려면 Ctrl+C를 누르세요."
    while ($true) {
        Start-Sleep -Seconds 1
        $ended = $processes | Where-Object { $_.HasExited }
        if ($ended) { Write-Output "프로세스가 종료되어 전체 실행을 정리합니다."; exit $ended[0].ExitCode }
    }
} finally {
    foreach ($process in $processes) { if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue } }
    foreach ($name in $old.Keys) { if ($null -eq $old[$name]) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue } else { Set-Item "Env:$name" $old[$name] } }
}
