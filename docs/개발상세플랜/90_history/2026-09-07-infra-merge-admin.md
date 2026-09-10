# 인프라·병합·관리자·로깅 변경 이력 (2026-09-07 ~ 2026-09-08)

루트 README의 변경 기록에서 옮긴 문서입니다. 섹터 병합, 관리자 앱 연결, Redis
공개 이력 캐시, 토큰 예산, 터미널 로그 정리와 MCP STALE 진단, 그리고 날짜별 회귀
기록을 다룹니다.

## 2026-09-07 섹터 병합과 검증

2026-09-07 병합 기준: `frontend_user`는 `Hwanseok`의 `c96821d`를 유지하고,
`frontend_admin`은 수신한 `origin/chd2`의 `5027155`를 반영했습니다. 관리자 확장에
필요한 Backend·정본 문서는 자동 병합 결과를 유지합니다. 후속 WU-F8 접속 오류 수정에서 Backend 주소 환경 변수와 관리자 UUID 입력·복구를
반영했습니다. 상세 실행 방법은
[관리자 README](../../../frontend_admin/README.md)를 참고하세요.

병합 검증 결과는 사용자 Front 374개·관리자 Front 14개·MCP 44개 통과입니다.
Backend 비DB 회귀는 525개 통과·15개 실패·8개 건너뜀이었으며, Streamlit이 없는
Backend 전용 환경 때문에 실패한 관리자 화면 연동 1개는 루트 `.venv`에서 재검증해
통과했습니다. 나머지 14개 실패는 병합 전 `Hwanseok`에서도 동일하게 재현됩니다.
기존 테스트 대역의 worker·토큰 설정 누락, Agent/Redis/SQL 계층 경계 검사와 MCP
공개 context 응답 실패는 이번 병합에서 수정하지 않았습니다. 실제 DB·migration·
유료 API·브라우저 E2E 검증은 실행하지 않았습니다. 아래 과거 검증 수치와 구분합니다.

- UUID-only 사용자 Frontend의 홈·게임 진행·관전·서버 확정 결과·게임별 피드백 화면과 Backend 공개 API client
- `POST /api/v1/feedback`의 PostgreSQL 영속 저장, 멱등 재생, 일반·게임별 피드백 검증
- 브라우저 UUID v4 생성·보관과 `X-User-Id` 기반 사용자 구분
- FastAPI 공개 게임 API와 UUID별 게임 소유권 확인
- Frontend API client의 `/health`·`/ready` 상태 확인과 공개 API header·오류 계약 테스트
- Backend 소유 PostgreSQL migration 실행 코드(MCP 섹터가 실제 실행)
- 독립 관리자 Streamlit 앱과 후속 MCP 서버 예약 구조(`mcp_server/mcp_2`)
- FastMCP 기반 `/mcp`와 최소 Resource·Prompt·Tool 등록부
- FastMCP의 역할별 Prompt와 Backend 게임 context·action endpoint로 전달하는 HTTP adapter

## 개발 섹터 역할과 실행 구조

개발 섹터 역할은 코드 소유권과 실행 환경 책임을 분리합니다. Backend 섹터는
DB schema·migration SQL·repository와 Redis client·lock 코드를 작성하고, MCP
섹터는 PostgreSQL·Redis 인스턴스 구축·기동·중지, DDL migrator와 DML runtime
계정·권한 준비,
migration 실행과 health 확인을 담당합니다. 실제 Backend 프로세스는 DB·Redis에
직접 연결하며 MCP 서버를 데이터 프록시로 사용하지 않습니다.
기존 `event_outbox`와 agent 관련 테이블·암호화 컬럼은 DB/migration 호환을 위해
보존합니다. 신규 MVP 실행 경로의 게임 추적은 `game_events`와 `receipts`를
사용하고, MCP는 FastMCP 표준 protocol session만 사용합니다.

AI 진행 worker는 actor별 Resource → Provider → 검증된 Tool 제출 경로를 사용하고,
read-only 관리자 API와 연결됩니다. 공개/본인/차례/persona 경계를 따로 검증하며
GM 안내는 기본 이벤트 수준입니다. canonical game의 Redis publisher 자동 기동,
LLM 비용·예산 집계와 별도 GM LLM 연출은 현재 범위에 포함하지 않습니다.

게임 흐름용 `DeterministicGameAgent`는 DB reservation이나 lease 없이 Backend가
제공한 context를 deterministic Fake Provider에 전달하고, 검증된 action만 Backend
경계로 반환합니다.

PostgreSQL에서는 검증된 AI SPEAK/PASS를 인간과 동일한 GameEngine 검증·transaction으로
기록합니다. AI 원장의 source 값은 기존
스키마 계약에 맞춘 `AGENT`입니다.

Frontend sync는 Backend `game_events`의 operation `type`을 적용하며, DB·Redis를
직접 호출하지 않습니다.

인간 SPEAK/PASS와 행동 command는 자신의 제출만 PostgreSQL에 기록하고 즉시
반환합니다. 중앙 `AiProgressWorker`가 열린 AI window를 비동기로 회복하며,
LLM·MCP 실패 시에만 같은 command 경계의 deterministic fallback을 사용합니다.

PostgreSQL snapshot은 생성 직후뿐 아니라 `DAY_DISCUSSION` 진행 상태도 복원합니다.
새로고침 시 현재 `action_windows`와 토론 제출 원장을 다시 읽어 실제 window ID와
인간 legal action을 반환하므로, 같은 게임을 이어서 테스트할 수 있습니다.
밤 행동과 투표 command도 PostgreSQL action service를 통해 GameEngine과
`action_submissions`·`game_events`에 연결되어 있습니다. 투표는 인간 표를 먼저
원장에 기록하고 생존 AI 표를 이어서 수집한 뒤, 모든 생존자 표가 모였을 때만
해소합니다. 현재 열린 투표 원장은 snapshot·worker 재시작 시에도 복원합니다.
인간 시민의 밤은 별도 입력 없이 Backend가 자동 해소해 다음 낮으로 전환합니다.
실제 PostgreSQL smoke에서 밤 행동과 다음날 투표 command 왕복을 확인했으며,
재투표·승패 규칙과 종료 snapshot의 PostgreSQL smoke도 확인했습니다.
2026-09-07에는 격리 DB와 dummy Provider의 실제 8인 게임을 최종 지목까지 완주했습니다.
사망한 인간의 `FAST_FORWARD` command도 PostgreSQL action service에 연결했습니다.

## 터미널 진행 로그 정리 (WU-B6)

`SAVE_AND_EXIT`와 `RESUME`의 실제 PostgreSQL 왕복도 smoke로 확인했습니다.
Backend는 서버 시작 시 중앙 `AiProgressWorker`를 실행해 열린 AI speech·night·vote
window를 비동기로 회복합니다. phase 전환은 마지막 필수 actor 제출을 처리하는
동기 PostgreSQL transaction에서만 수행합니다. 테스트 앱에서는 수동 command와의
경쟁을 막기 위해 `enable_background_worker=False`를 사용할 수 있습니다. worker 장애는
외부 예외 원문 없이 고정된 실패 단계로 기록합니다. Backend 터미널에는 게임 생성·
시작·저장·재개·단계 변경·종료, AI 공개 발언 적용과 대체·실패만 JSON 한 줄씩
표시합니다. `STARTED`·`CONTEXT_READY`·`DECIDING`·`DECIDED`·`SKIPPED`, 중복되는
`COMMAND_APPLIED`와 PASS·비공개 행동의 개별 적용은 터미널에서 숨깁니다.
Backend 프로세스의 정상 HTTP access 및 httpx/httpcore/mcp INFO 로그도 숨기며,
HTTP 4xx·5xx, 서버 기동·종료 안내와 WARNING 이상은 유지합니다.
`run_openai.sh`는 Backend·MCP·Front의 출력을 같은 터미널에 연결하므로,
`INFO: ... "POST /mcp HTTP/1.1" 200 OK`는 별도 MCP 프로세스의 Uvicorn 접근
로그입니다. Backend의 정상 접근 로그 필터는 이 MCP 프로세스에 적용되지 않습니다.
`stage`·`action`·`summary`가 있는 진행 JSON은 Backend의
`agent/activity.py`가 만들고 `core/logging.py`의 `backend.game_progress`가 출력합니다.
AI 진행 worker는 브라우저 접속 여부나 현재 화면 대신 DB의 `IN_PROGRESS` 게임과
열린 AI 차례를 기준으로 동작합니다. `AI_MAFIA_STORAGE_MODE=team`이면 공유 DB의
다른 사용자 게임도 처리 대상이므로 본인이 플레이하지 않아도 MCP 요청과 AI 적용
로그가 발생할 수 있습니다. 화면 이탈만으로는 일시정지되지 않으며, `저장하고 나가기`
성공으로 `SAVED`가 된 게임은 새 AI 차례 조회에서 제외됩니다.
`backend/logs/game-progress.log`에는 기존 모든 상세 진행 JSON을 보존하고 UI의
진행 기록도 유지합니다. `run_id`는 서버 실행을, `sequence`는 그 실행 안의 발생
순서를 나타냅니다. 터미널은 일부만 표시하므로 순번이 건너뛸 수 있습니다.

로그 시각은 UTC이며 파일은 5 MiB마다 회전하고 이전 파일 3개를 보관합니다.
실제 적용 성공은 DB transaction 성공 반환 뒤 기록하며 비공개 역할·밤 actor·대상,
프롬프트·모델 내부 추론 원문을 기록하지 않습니다.
터미널 로그 정리 검증(2026-09-08, WU-B6)은 관련 테스트 3개가 통과했습니다.
임시 파일·독립 logger로 터미널 선별, 전체 JSON·순서·UI 기록 보존, HTTP 실패·경고
보존과 반복 설정의 멱등성을 확인했습니다. 단일 로깅 기능 변경이므로 전체 회귀와
실제 DB·유료 API 검증은 생략했습니다. Backend의 자동 reload 또는 재시작 후 적용됩니다.

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest \
  -p pytest_asyncio.plugin -p anyio.pytest_plugin backend/tests/test_agent_activity.py \
  -k 'logging_configuration or access_status_filter or terminal_selection' -q
```

## 2026-09-08 MCP PASS 대조·STALE 진단과 팀 DB 실게임 검증

2026-09-08 14:15~14:18:55 KST의 최근 두 게임을 로그와 team DB 원장으로 대조한 결과,
확정 AI 행동 52건 중 SPEAK 9건·PASS 43건이었습니다. PASS는
`agent_jobs.status=FALLBACK`, `failure_code=MCP_UNAVAILABLE`인 41건과
`SUCCEEDED`, `public_rationale=NO_NEW_INFORMATION`인 2건으로 구분됐습니다.
첫날 PASS 21건은 모두 MCP 실패에 따른 대체 행동이었습니다. `PROVIDER_TIMEOUT`은
없었지만 MCP_UNAVAILABLE는 context 조회의 연결·timeout·응답 검증 실패를 뭉뚱그리므로
MCP 자체 timeout 여부까지 단정할 수 없습니다.
실제 적용은 AI의 `PLAYER_PASSED` event와 같은 actor의 직전 상태 버전 job을 맞춰
확인했습니다. 로컬의 모델 PASS 2건은 `DECIDED`부터 `APPLIED`까지 이어졌고,
별도의 MCP fallback 시도 1건은 사용자 발언으로 상태가 바뀐 뒤 `SKIPPED`로 끝났습니다.
DB에 확정된 fallback 41건의 대응 기록은 보관된 로컬 로그에 없으며, 같은 차례에 로컬은
중복·지난 작업을 건너뛴 정황이 있어 공유 DB의 다른 Backend 실행 경로를 우선 확인해야 합니다.
`STARTED`의 `decision_source=MODEL`이나 `SKIPPED`만으로 모델이 PASS했다고 집계하지 않습니다.
이후 사용자가 다른 PC의 Backend도 같은 DB에서 테스트 중임을 확인했고, 해당 PC는
이번 수정 범위에서 제외했습니다. 위 41건을 이 PC의 실패율로 해석하지 않습니다.
이 PC의 실제 모델 PASS 2건은 정상 선택이고, 로컬 MCP 오류 시도 1건은 상태 변경 뒤
적용되지 않은 결과입니다. 과거의 포괄적 오류 코드만으로 세부 원인을 확정할 수는 없습니다.

로컬 WU-M6 보완으로 같은 게임·actor의 context가 기대 phase·window·버전보다 진행한
경우 `STALE`/`SKIPPED`로 폐기하며 PASS proposal·`FALLBACK` 기록을 만들지 않습니다.
MCP 초기화 알림도 HTTP 성공 후에만 완료 처리해 거부된 session으로 Resource를
계속 요청하지 않습니다. 실제 timeout·연결·HTTP·RPC·JSON·응답 계약 오류는 기존
대체 정책을 유지하고 `MCP_CONTEXT_FAILED` 내부 JSON에 `scope`, `diagnostic_code`,
`http_status`, `game_id`, `state_version`, `run_id`, `process_id`를 기록합니다.
`MCP_TIMEOUT`과 `MCP_BACKEND_TIMEOUT`은 각각 Backend→MCP와 MCP→Backend 구간,
`MCP_BACKEND_HTTP_403`은 Backend의 context 거부, `MCP_INSTRUCTION_MISSING`은
MCP 소유 지침 누락, `MCP_CONTEXT_STALE`은 기대 상태 변경을 뜻합니다. 상태·권한
검증을 우회하지 않으며 원문 예외·URL·본문·비공개 actor·자격증명은 진단에 넣지 않습니다.
이 진단은 내부 파일·터미널 전용이며 UI와 DB의 공개 실패 사유는 그대로 유지합니다.
Backend는 `--reload`로 변경을 반영하지만 MCP는 자동 재적재하지 않으므로
`./run_openai.sh` 실행 묶음을 재시작해야 MCP adapter·프롬프트도 반영됩니다.
2026-09-08 로컬 검증: 관련 테스트 252개 통과(합성 FastMCP ASGI 왕복 4개 포함),
전체 Backend·MCP 회귀 1회는 격리 PostgreSQL·Redis와 dummy Provider로
1,079개 통과·15개 실패·6개 생략했습니다. 실패는 기존 fixture의 `_ai_worker`·
`llm_max_output_tokens` 누락, 공개 context fixture 및 기존 import·SQL 경계 검사이며
이번 범위에서 수정하지 않았습니다. `B6_LOCAL_QA=1`로 기존 8개 SQL 검증도 포함했고,
그중 추가 확인된 1개 실패의 fixture와 runtime은 HEAD 대비 변경이 없음을 확인했습니다.
로컬 실행 묶음 재시작 후 Backend `/health`·`/ready`, Front health, MCP initialize와
최신 Prompt 일치, 존재하지 않는 합성 게임의 Backend 404 진단 왕복을 확인했습니다.
team DB 데이터는 이 이슈 수정에서 변경하지 않았고, 유료 LLM 게임 재실행은 생략했습니다.

후속 사용자 요청으로 2026-09-08 14:41~14:47 KST에 팀 테스트 DB에서 실제
`gpt-5.6-luna` 6인 게임을 공개 게임 API로 생성·진행했습니다. 게임
`a71fbf98-8541-4070-a0be-170702668e01`은 빠른 진행 없이 토론 3회·밤 2회·투표 2회를
거쳐 셋째 날 시민 승리(`COMPLETED`, state version 71)로 종료됐습니다.
이 PC의 `run_id=bc38473f-7595-4986-81db-e130cb5b6050`와 원장을 맞춘 공개 AI
행동은 SPEAK 10건·모델 PASS 0건·장애 대체 PASS 0건입니다. 첫날 이 PC의 적용분은
SPEAK 2건·PASS 0건이며 한 게임의 작은 표본이므로 일반적인 발언율로 해석하지 않습니다.
사람 발언으로 v42→v43이 된 동안 AI context 조회가 진행된 사례에서
`MCP_CONTEXT_STALE → SKIPPED`와 PASS 미생성·미적용을 확인했습니다. 같은 예약의
DB 완료는 fencing으로 거부됐으므로 이 사례를 DB `status=STALE` 저장으로 표현하지 않습니다.
사람의 발언 요청 1회도 오래된 버전으로 409를 받은 뒤 최신 상태 재시도로 성공했습니다.
로컬 AI 투표 5건은 정상 적용됐습니다. 마지막 AI 투표 1건은 마감까지 유효 제출이
없어 자동표가 먼저 확정됐고, 모델 판단 시작 15.027초 뒤의 FALLBACK→SKIPPED도
이미 마감을 지난 결과였습니다. 비공개 단계의 기존 로그에는 세부 실패 코드가 없어
provider timeout인지 확정하지 못했습니다. 로컬 MCP 진단은 상태 변경 1건뿐이며
연결·HTTP·계약 오류는 없었습니다. 공개 발언 모델 응답은 3.607~14.300초,
중앙값 6.124초였습니다.
발언 내용에서는 AI가 자기 좌석 번호를 타인처럼 지칭하는 별도 품질 문제가 관찰됐습니다.
공유 원장의 공개 AI 행동 53건 중 로컬 대응 기록이 없는 `MCP_UNAVAILABLE` 대체
PASS 43건은 이 PC 집계에 합산하지 않습니다. 게임은 완료 상태로 보존했으며
다른 게임·프로세스는 이 검증에서 변경하지 않았습니다.
실게임 검증 후 사용자 요청으로 이 PC의 Backend(18000)·MCP(18100)·Front(18501)를
종료했고 세 포트의 listener가 없음을 확인했습니다. 다시 실행하려면 `./run_openai.sh`를 사용합니다.

## 토큰 예산과 Redis 공개 이력 캐시

Agent의 구조화 응답 한도는 `LLM_MAX_OUTPUT_TOKENS=8192`이며 발언·밤 행동·투표와
교정 요청에 같은 설정을 적용합니다. 추론 모델은 내부 추론도 이 예산을 사용합니다.
대사 200자와 호출·job의 기존 시간 제한은 유지하므로 토큰 상향이 투표 마감 문제를
해결하지는 않습니다. 설정 변경 뒤에는 Backend를 재시작해야 합니다.

전체 공개 사건·발언은 `.env`의 `REDIS_URL`로 연결한 Redis에 게임별로 저장하며,
Frontend snapshot과 AI public context가 같은 전체 이력을 읽습니다. 최근 일부 발언으로
잘라 저장하지 않습니다. key는 `mafia:v1:conversation:{db_scope}:{game_id}`이며 DB 접속
대상을 구분하는 namespace, 상태 버전·cursor·checksum과 7일 TTL을 사용합니다.
소유권·현재 DB 버전을 확인한 후 공개 필드를 재검증하고, 캐시 누락·손상·장애 시
PostgreSQL 전체 원장에서 복구합니다. PostgreSQL은 영구 원본이며 개인 정보 scope와
비공개 역할 원장·모델 내부 추론은 이 캐시에 넣지 않습니다.

AI의 멀티턴 입력도 매 행동마다 `Agent → MCP Resource → Backend 내부 context API`
경로로 재구성합니다. Backend는 DB에서 소유권·현재 상태를 확인하고,
`read_public_history()`에서 버전·cursor가 일치하는 Redis 공개 이력을 우선 사용합니다.
캐시를 쓸 수 없으면 `game_events`의 해당 시점까지 공개 사건·발언 전체를 읽어 복구한 뒤
Redis를 갱신합니다. 본인의 비공개 조사 기록은 DB에서 별도로 읽습니다. 프로세스 메모리의
dict·list는 이번 요청을 조합하는 용도이며 Agent별 누적 대화 저장소로 재사용하지 않습니다.
모델에는 매번 system·developer 지침과 전체 context JSON을 다시 보내며,
`previous_response_id`·대화 세션 연결을 사용하지 않습니다. 현재 Agent 대화 경로에는
과거 발언의 임베딩 검색·요약·최근 N개 절단을 적용하지 않습니다. Redis는 DB 이력 조회를
줄이는 캐시이므로 모델에 보내는 전체 이력 길이까지 줄여 주지는 않습니다.

### 멀티턴 효율 개선 검토안 (미구현)

멀티턴 효율 개선 검토안(미구현): PostgreSQL 원본과 Redis 캐시를 유지하면서 모델
입력을 현재 상태·본인 확정 정보, 최근 원문, 출처가 있는 공개 주장 기록, 관련 과거 원문으로
구성하는 방향을 권장합니다. 먼저 동일 기록에서 입력량·응답 시간·질문 누락·판단 오류를
비교하고, 중복 메타데이터 축소와 고정 지침의 프롬프트 캐시 경계를 적용한 뒤 이력 선별을
검증합니다. 이후 화자·대상·키워드와 임베딩을 함께 사용하는 검색을 추가합니다. 공개 발언
분석은 사용자·AI 발언을 실시간으로 처리하지만 Agent 입력의 검색·요약 연결은 아직
구현하지 않았습니다. Agent용 검색을 도입할 때는 분석 미준비 시 최근 원문으로 진행하고
기존 투표 준비 판정은 유지해야 합니다.
공개 요약은 여러 AI가 공유할 수 있지만 타인의 역할 주장과 서버 확정 사실을 구분하고,
모든 항목에 원문 event ID를 보존해야 합니다. 비공개 조사 기록은 공유 요약·검색에서 제외하고
actor별 권한 조회로만 전달합니다. Redis에는 DB 원문에서 복구 가능한 공개 파생 자료만 둡니다.
[OpenAI 프롬프트 캐시 안내](https://developers.openai.com/api/docs/guides/prompt-caching)에
따라 재사용할 접두부의 경계와 최소 길이를 확인하고 실제 캐시 읽기·쓰기 비용을 비교합니다.
`previous_response_id`로 연결하더라도 이전 입력은 과금되므로 입력 축소와 별도로 평가합니다.
근거는 [대화 상태 문서](https://developers.openai.com/api/docs/guides/conversation-state)입니다.

## 토큰·Redis 보완 검증 (2026-09-07)

토큰·Redis 보완에서는 로컬 `.env`에 Redis 설정이 없어 실행 중인 loopback Redis의
0번 DB를 지정하고 출력 한도를 8192로 설정한 뒤 로컬 Backend `18000`을 재시작했습니다.
실제 게임 snapshot API가 200을 반환했고, PostgreSQL·응답·Redis의 공개 이력 63건
(발언 45건)이 순서와 내용까지 일치했습니다. 해당 게임의 파생 캐시만 지운 뒤 다시
조회해 전체 이력이 복구되는 것도 확인했습니다. 자동 테스트·lint·전체 회귀와
추가 LLM 게임은 사용자 요청에 따라 생략했으며, 상향 후의 발언 품질은 미평가입니다.
실제 Redis에서 이전 상태 버전의 저장이 거부되고 최신 이력이 유지되는 것도 확인했습니다.

## 관리자 앱 연결 (WU-F8 후속 포함)

관리자 앱은 read-only 통합 운영 분석·피드백/로그/운영 에이전트 계획 화면을 제공합니다. 현재 Backend 계약이 제공하는 게임 KPI와 시민/마피아 결과는
실제 값으로 표시하고, 에이전트 페르소나별 AI 승률·사용자 피드백 목록·관리자 감사 로그도 Backend
조회 API에 연결합니다. 피드백 종류/평점과 감사 이벤트 유형을 필터링하고 20건씩
이전·다음 페이지로 조회합니다. 전체 사용자 KPI는 DB의 UUID 수입니다.
운영 에이전트 계획 탭에서는 승인 자료에 질문하고 검색 근거·점수·신뢰도를 확인할 수
있으며, Backend의 `POST /api/v1/admin/insights/query`는 질문 후 게임·문서 데이터를
변경하지 않습니다.

관리자 데모 모드에는 공개 테스트 키 `demo_ai_mafia_admin_v1`의 연결 확인 입력창이
있습니다. 실제 인증 키가 아닌 로컬 가상 API 전용 값입니다. 게임 1,200건·사용자 300명,
페르소나별 승률·30일 추이·피드백 240건·감사 로그 180건의 합성 예시를 표시하며 조회 유형 필터를
제공합니다. 합성 게임은 완료 900·저장 180·진행 96·실패 24건이며, 실제 DB에 삽입하지
않습니다. 진영별 승리는 시민 540승·마피아 360승 도넛 차트로 표시하며 KPI·페르소나별 AI
승률은 같은 합성 기록에서 계산합니다.
실제 API 권한은 기존 UUID allowlist로 검증합니다.
관리자 UUID는 임의로 생성하지 않습니다. 화면의 **관리자 식별자**에서 Backend의
`ADMIN_USER_IDS`에 등록된 UUID v4를 입력하고 확인한 뒤 적용합니다. 저장 응답 확인 전에는
데이터를 조회하지 않으며, 권한 거부와 연결 오류에서는 입력·재시도 경로를 유지합니다.
Backend의 allowlist가 비어 있으면 모든 관리자 접근이 거부되므로, 허용할 UUID를
Backend 실행 설정에 등록하고 Backend를 재시작해야 합니다.

2026-09-07 로컬 개발용 관리자 UUID: `33dc60ae-b47e-4fe7-8de9-9c5a3a9fc0a7`. 실행 중인 로컬
PostgreSQL `127.0.0.1:55432/mafia_qa`의 `public.users`에 생성하고, Git에서 제외된
루트 `.env`의 `ADMIN_USER_IDS`에 등록했습니다. 팀 공유 DB에는 생성하지 않았습니다.
관리자 화면 `http://127.0.0.1:8502`에서 **관리자 식별자 → 관리자 UUID v4**에
위 값을 입력하고 **입력값 확인 → 확인하고 적용**을 누르세요. 이 값은 README에
공개된 로컬 개발용 식별자이므로 공개 서비스의 관리자 인증에 사용하지 않습니다.
후속 접속 수정 검증은 관리자 테스트 18개 통과, Backend·사용자 Front 비DB 회귀
900개 통과·기존 실패 14개·opt-in 8개 건너뜀입니다. 실제 Backend health 200과
미등록 UUID 403, 관리자 서버 health 응답을 확인했습니다. 실제 DB 변경·유료 API
호출은 생략했습니다. 후속 관리자 등록에서 로컬 DB 사용자 저장과 Backend 설정
재로딩을 확인했고, 등록 UUID로 metrics·persona-win-rates·feedback·audit-logs
네 API가 모두 HTTP 200을 반환했습니다. 브라우저에서는 위 UUID를 직접 적용해야 합니다.

macOS에서 기존 관리자 가상환경으로 실제 API 모드를 실행하려면 저장소 루트에서
다음 명령을 사용합니다. 접속 주소는 `http://127.0.0.1:8502`이며, 관리자
클라이언트는 `BACKEND_API_URL`을 사용하며, 미설정 시 `http://127.0.0.1:8000`입니다.
현재 로컬 Backend는 `18000` 포트이므로 아래처럼 주소를 명시합니다.

```bash
BACKEND_API_URL=http://127.0.0.1:18000 ADMIN_DEMO_MODE=false \
  frontend_admin/.venv/bin/python -m streamlit run frontend_admin/app.py \
  --server.address 127.0.0.1 --server.port 8502 --server.headless true
```

운영 분석 화면은 전체 사용자·누적 게임·완료율·시민/마피아 승률 KPI, 진영별 도넛,
얇은 페르소나별 가로 막대와 상세 표를 중복 없이 한 화면에 배치합니다. 최근 게임 목록과
종료 게임 수는 관리자 요약 화면에서 제외했습니다.

관리자 계약은 [API 명세 7절](../01_core/AI_MAFIA_API_SPEC.md)의 7.4~7.8에
확장되어 있습니다. `GET /api/v1/admin/persona-win-rates`, `/api/v1/admin/feedback`,
`/api/v1/admin/audit-logs`를 제공하고 metrics는 users_total·daily_games를 추가합니다.
계획서는 WU-B8에 통합 관리자 화면 연결까지 명시합니다. 실제 모드는 Backend의
`ADMIN_USER_IDS`와 같은 관리자 UUID를 사용하며 `ADMIN_DEMO_MODE=false`로 실행합니다.
Backend 실행 명령은 저장소 루트에서 `python -m uvicorn backend.app.main:app --port 8000`입니다.
현재 서버가 실행 중이면 같은 포트의 해당 프로세스를 재시작해 변경 모듈을 적용합니다.
관리자 테스트는 실제 DB 없이 fake repository와 메모리 HTTP 전송을 사용합니다:
`python -m pytest -c pyproject.toml frontend_admin/tests backend/tests/test_b8_admin_api.py -q`.
실 PostgreSQL 집계 실행 계획·DB 통합 검증은 격리된 테스트 DB에서 별도로 수행해야 합니다.

관리자 센터의 운영 분석·사용자 피드백·관리자 로그·운영 에이전트 계획 네 화면은 동일한
짙은 퍼플 관리자 스타일로 통일해 운영 화면의 구분과 가독성을 높였습니다. 운영 에이전트
계획 탭은 RAG/운영 에이전트의 구현 계획과 데이터 보호 경계를 설명하며, 검색 코드 경로는
외부 LLM 없는 로컬 임베딩과 pgvector 혼합 검색으로 동작하도록 연결했습니다. 자동 조치는 연결하지 않습니다.
당시 상세 계획서는 2026-09-08 `chd_test` 병합에서 계획 탭과 함께 제거됐습니다.
현재 세 탭의 동작은 루트 [README](../../../README.md)와
[화면 흐름](../04_frontend/AI_MAFIA_SCREEN_FLOW.md)을 기준으로 확인합니다.

화면용 `ADMIN_DEMO_MODE=true` 합성 데이터와 별도로, 실제 DB 검증이 필요한 담당자는
`backend/seed_admin_demo_data.sql`을 수동 실행할 수 있습니다. 이 파일은 기존 데이터를
보존하면서 합성 게임 30건, 게임 참가자 210건, 피드백 30건을 idempotent하게 추가하고,
실제 조회를 의미하는 관리자 감사 로그는 생성하지 않습니다. seed 실행 직후 확인한 집계는
users 89건, games 96건, game_players 680건, feedback 35건이며 이후 운영 실행에 따라
현재 수치는 달라질 수 있습니다. 운영 에이전트 색인은 `backend/migrations/005_create_admin_knowledge_schema.sql`
적용 후 `backend/index_admin_knowledge.py`를 수동 실행합니다. 현재 연결된 원격 DB는
`pgvector` 확장을 제공하지 않아 이 migration과 색인은 아직 적용하지 않았습니다.

Backend와 관리자 UUID 없이 UI를 확인해야 할 때는 PowerShell에서
`$env:ADMIN_DEMO_MODE = "true"`를 설정해 합성된 관리자 메타데이터를 사용할 수
있습니다. 가상 모드는 화면 개발용이며 실제 운영 데이터나 권한 검증을 대신하지
않습니다.

```bash
uv run streamlit run frontend_admin/app.py --server.port 8502
```

관리자 entrypoint는 실행 위치와 무관하게 저장소 루트를 import 경로에 등록해
`frontend_admin` 패키지를 불러옵니다.

## 2026-09-07 후속 수정의 최종 회귀 기록

2026-09-07 후속 수정의 최종 회귀는 **Backend 510개, MCP 44개, 관리자 Front 18개**가
통과했습니다. 사용자 Front **331개**를 더해 **총 903개 통과, 실패 0**입니다.
실브라우저 근거는
[보고서 8절](../05_reports/AI_MAFIA_GAME_TEST_GAP_REPORT.md#8-수정권고-반영과-ai-진행-표시)에 기록합니다.
최초 Backend 회귀의 2개 실패는 강화된 window 계약을 반영하지 않은 테스트 대역을
수정한 뒤 해소됐습니다. Front의 낡은 sync fixture·소스 문자열 검사 2개도 현재 계약과
Node 동작 검증으로 보완한 뒤 통과했습니다. 기존 config의 긴 줄 Ruff 경고 1개는 범위 밖으로 남겼습니다.

## 실제 SQL·통합 검증 조건

실제 SQL을 사용하는 `test_b5_game_api.py`, `test_postgres_game_flow.py`,
`test_b6_agent_manager.py`의 opt-in 8개와 MCP process 테스트도 **격리된 로컬 QA DB**에서
검증했습니다. 공유 DB를 대상으로 실행하지 않습니다. MCP process 테스트는 이제
Tool `accepted=true`, receipt와 window/version 변경을 확인하며 오류 응답을 통과시키지 않습니다.

아래는 이번에 사용한 **합성 자격증명의 임시 DB 전용** 검증 예입니다. 해당 DB에
기존 migration 4개를 적용하고 로컬 Redis 15번 DB를 준비한 뒤 실행합니다. 두 DB
변수를 함께 덮어써 원격 `.env` 값이 선택되지 않게 합니다. B6 opt-in은 아래 loopback
QA 주소만 허용합니다. 테스트는 자신이 만든 UUID·게임·Redis key만 정리합니다.

```bash
export TEAM_DATABASE_URL='postgresql://qa:synthetic-only@127.0.0.1:55432/mafia_qa'
export DATABASE_URL="$TEAM_DATABASE_URL"
export DATABASE_MIGRATION_URL="$TEAM_DATABASE_URL"
export TEST_DATABASE_URL="$TEAM_DATABASE_URL"
export DATABASE_NAME=mafia_qa REDIS_URL=redis://127.0.0.1:6379/15
export GAME_STATE_KEYRING_FILE='' GAME_STATE_ACTIVE_KEY_ID=''
export LLM_PROVIDER=dummy OPENAI_API_KEY='' GEMINI_API_KEY=''
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
B6_LOCAL_QA=1 backend/.venv/bin/python -m pytest \
  -p pytest_asyncio.plugin -p anyio.pytest_plugin backend/tests -q
PYTHONPATH=.:mcp_server .venv/bin/python -m pytest \
  -p pytest_asyncio.plugin -p anyio.pytest_plugin mcp_server/tests -q
```

실제 유료/Local LLM의 추론 품질·운영 DDL 권한·기존 데이터 암호화 전환·운영 TLS는
검증하지 않았습니다. 6~9명 각각 100판의 heuristic 시뮬레이션 400판은 전부 종료됐으나,
마피아 승률 62/54/68/69%는 실제 LLM의 시나리오별 균형을 보장하지 않습니다.

## 2026-09-08 시간 예산·lease 정리 검증

2026-09-08 시간 예산 수정 검증은 관련 **96개 통과**(팀 DB 임시 SQL 10개 포함),
Backend·MCP 회귀 **1,070개 통과·기존 실패 14개·생략 17개**입니다. 실패는 기존
fixture의 `_ai_worker`·`llm_max_output_tokens` 누락, 공개 context fixture, import·SQL
경계 검사로 새 실패는 없었습니다. B6 SQL은 focused 실행에서 별도 검증했고 기존
runtime batch 복구 fixture 1건과 무관한 선택형 vote-insights DB 검증 6건은 생략했습니다.

수정 후 실제 `gpt-5.6-luna` 게임 `90c5bf07-ca03-44a4-bf38-d0870bfbb411`은
15:09~15:15 KST에 빠른 진행 없이 토론 3회·밤 2회·투표 2회를 거쳐 셋째 날 시민
승리(`COMPLETED`, state version 78)로 종료됐습니다. 이 PC의 SPEAK 선택 15건 중
11건 적용·상태 변경 4건 폐기, 모델 PASS·대체 PASS·timeout·MCP 오류·제출 실패는
모두 0건이었습니다. 첫날은 SPEAK 3건·PASS 0건이며 로컬 투표 6건도 모두 적용됐습니다.
로컬이 선점한 밤 행동은 없었습니다. 공개 job 15개의 실제 lease도 최대 40초 11건·
창 마감 제한 4건으로 새 규칙과 일치했습니다. 모델 응답은 3.289~8.519초여서 15초
초과 응답은 실게임에서 관찰되지 않았으며 해당 경계는 합성 시간 테스트로 검증했습니다.
공유 원장의 MCP 오류 PASS 48건과 밤 대체 4건은 로컬 대응 기록이 없어 별도 집계했습니다.
검증 게임은 완료 상태로 보존했으며 다른 PC의 Backend는 변경하지 않았습니다.
