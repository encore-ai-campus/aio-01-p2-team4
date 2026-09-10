# AI 마피아 최소 FastMCP 서버

이 package는 FastMCP Resource·Prompt·Tool, Backend HTTP adapter와 역할별 Agent
지침을 제공한다. 게임 판정, Agent Manager, DB, Redis, LLM 호출과 상태 변경은
Backend가 담당한다.

## 등록 항목

- Resource: `mafia://context/current/{game_id}/{user_id}`,
  `mafia://context/scoped/{game_id}/{user_id}/{player_id}/{scope}`
- Prompt: `agent_instruction(role="CITIZEN", phase="DAY_DISCUSSION")`
- Tool: `submit_action`, `manipulate_vote`, `inspect_special_roles`

Resource의 게임 데이터와 Tool 실행은 아래 Backend endpoint에 위임한다.

```text
GET  /internal/mcp/context
GET  /internal/mcp/special-roles
POST /internal/mcp/actions
```

`manipulate_vote`는 `vote.triple.v1`을 가진 HUMAN 커스텀 직업의 처형 투표를
제출한다. Backend가 게임 소유자의 HUMAN을 선택하며 DAY_VOTE·REVOTE에서 해당 표를
3표로 집계한다. 인수는 `user_id`, `game_id`, `expected_state_version`, `window_id`,
`idempotency_key`, `target_player_id`이며 actor·가중치 입력은 없다. 일반 투표와
자동 투표는 1표이고 최종 지목에는 적용하지 않는다. 기존 `submit_action` 서명은 유지한다.

`inspect_special_roles(user_id, game_id)`는 `intel.special_roles.v1`을 가진 생존
HUMAN이 첫 밤을 마친 뒤 다른 플레이어의 탐정·의사 역할을 조회한다. 사망자도 포함하며
본인·마피아·시민은 제외한다. 조회는 밤 행동 횟수를 소모하지 않는다. adapter는 UUID,
게임 응답 바인딩, 폐쇄형 최소 응답과 역할·생사 타입을 검증하고 요청마다 새로 읽는다.
소유권·능력·첫 밤·현재 게임 상태 판정은 Backend가 담당한다. 이 결과는 공개 Resource와
AI 문맥에 추가하지 않으며 기존 AI Tool allowlist도 확장하지 않는다. 두 Tool은 사용자
전용 후속 화면 연동을 위한 준비이며 최소 runtime의 loopback/소유자 UUID 신뢰 경계를
유지한다. 공개 인터넷용 사용자 인증을 제공하는 endpoint가 아니다.

역할별 승리 계획·단계별 행동 전략은 `api/prompts/instructions.py`의 `ROLE_PLANS`에서
관리한다. 시민·탐정·의사·마피아 중 `me.role`에 해당하는 전략만 운영 `me.data`의
`agent_instruction`으로 제공한다. `persona.data.agent_instruction`은 검증된 성격
수치로 만든 고정 말투 지침이며 토론 외 단계에서는 빈 문자열이다. 자유 문자열은
지시문에 삽입하지 않는다. Prompt도 같은 렌더러를 사용하며 Backend prompt endpoint를
호출하지 않는다. 기존 `game_id`·`user_id` 인자는 호환용으로만 받는다.

Backend는 두 지침을 developer 메시지로 한 번 전달하고 게임 원문은 user 데이터에
둔다. 메인 system 메시지는 짧은 공통 규칙만 유지한다. 운영 응답의 정확한 계약은
[API 명세](../../docs/개발상세플랜/01_core/AI_MAFIA_API_SPEC.md)의 WU-M6 절을 따른다.

`api/prompts`, `api/resources`, `api/tools`의 `__init__.py`는 패키지 설명만 포함한다.
FastMCP 등록 코드는 각 패키지의 `registry.py`에 두며, `main.py`는 이 모듈들을 직접
import한다. Prompt와 Resource는 `api/prompts/instructions.py`의 같은 생성 함수를
사용한다. 구조 분리로 프롬프트 내용·등록명·URI·인자는 변경하지 않는다.

## 실행

Backend를 먼저 실행한 뒤 다음 환경변수로 FastMCP process를 실행한다.

```powershell
$env:BACKEND_API_URL = "http://127.0.0.1:8000"
$env:MCP_LISTEN_HOST = "127.0.0.1"
$env:MCP_LISTEN_PORT = "8100"
python -m mafia_game
```

MCP endpoint는 `http://127.0.0.1:8100/mcp`다. FastMCP 표준 protocol session은 SDK가
관리하지만, 별도의 bootstrap token·HMAC·nonce·session registry는 사용하지 않는다.
이번 변경은 MCP를 먼저 갱신한 뒤 Backend를 갱신한다. 구버전 MCP가 역할 지침을
보내지 않으면 Backend는 MCP 오류로 처리한다. `run_openai.sh`를 사용 중이면 전체
스크립트를 재시작한다. MCP 프로세스에는 자동 reload가 없다.

## 검증 이력

2026-09-09 저장소 정리 요청으로 MCP 테스트 소스와 pytest 경로 설정을 삭제했다.
아래 WU-M10 수치는 삭제 전 실행한 이력이며 현재 checkout에서 같은 pytest 명령을
재실행할 수 없다. 현재 최소 확인은 `python -m compileall mafia_game`과
`ruff check mafia_game`, 저장소 루트의 `git diff --check`를 사용한다.

### 2026-09-08 WU-M10 팀 DB 적용 사전 검증

MCP 비DB 회귀는 삭제 전에 177개 통과했다. Backend의 B16·MCP registry·migration 테스트와 MCP adapter·등록·
ASGI 왕복 focused 검증은 514개 통과, 3개 실패했다. 실패는 Backend
`test_mcp_registry_api.py`의 public context 테스트이며 `ReaderFixture`에
`cache_public_history`가 없어 `actor_context.py`에서 503으로 변환되는 것이 원인이다.
이 검증 작업에서는 Backend fixture와 MCP runtime을 변경하지 않았다.

생성 API의 공통 body validator에서 top-level·custom_role의 raw Tool명·action·
subtype·prompt와 raw ability 값 총 15개가 `422 VALIDATION_ERROR`로 거부됨을
확인했다. 정본의 세 밤 능력 참조와 Backend NIGHT allowlist는 모두 logical
`propose_night_action`으로 일치하며 실제 wire Tool은 `submit_action`이다.
현재 공개 catalog에는 `mcp_tool` descriptor가 없고 label·factions만 있으므로
descriptor endpoint 일치를 검증했다고 해석하지 않는다.

팀 DB는 읽기 전용 `SELECT 1`에 성공했으나 다음 객체가 모두 없다.

- `games.mode`와 해당 STANDARD 기본값
- `game_players.custom_role_name`, `custom_role_catalog_version`, `custom_ability_ids`
- `action_submissions.ability_id`
- `games_mode_check`, `game_players_custom_role_snapshot_check`,
  `action_submissions_ability_id_check`

`DATABASE_MIGRATION_URL`이 없어 공식 runner의 연결 전 설정 검증이 실패한다.
따라서 010·011은 미적용이며 기존 행 STANDARD/custom NULL 및 실제 CHECK 거부·
재실행 안전성은 미검증이다. runtime 연결은 superuser이며 public CREATE와
game_events UPDATE·DELETE 권한이 있어 최소 권한 계약도 충족하지 않는다.
DSN·계정·행 값은 출력하지 않았고 데이터·권한·프로세스 변경은 없었다.
전용 DDL 설정을 준비한 뒤 공식 `run_migrations`의 `migrations_dir`에 원본
010·011만 연결한 임시 디렉터리를 전달해 이름순 적용·재실행을 확인해야 한다.
001~009 전체 재실행은 기존 데이터 UPDATE를 포함하므로 이 검증 범위에 넣지 않는다.
실제 DB process 왕복과 Backend 전체 회귀는 각각 migration 선행조건 누락 및
타 섹터 회귀 담당 범위로 생략했으며, 루트 README 통합은 CP-7 담당자가 반영한다.
