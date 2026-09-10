# AI 마피아 구현 계획서

작성일: 2026-09-09  
문서 성격: 빈 프로젝트에서 현재 코드 수준까지 구현하기 위한 코드 중심 실행 계획

## 0. 문서 기준

이 문서는 기존 구현 계획서의 작업 순서를 전제로 하지 않는다. 설계서에 정의된
제품·API·DB·MCP·화면 계약과 저장소 디렉터리 구조를 입력으로 삼아, 현재 코드의
파일·클래스·함수·호출 관계를 역추적한 구현 순서를 정의한다.

상세 계약은 다음 arrangement 설계서를 참조한다.

- [전체 시스템 설계](AI_MAFIA_SYSTEM_ARCHITECTURE_DESIGN.md)
- [DB·Redis 설계](01_DB_REDIS_DESIGN.md)
- [API 계약](02_API_DESIGN.md)
- [MCP Server 설계](03_MCP_DESIGN.md)
- [게임 엔진·시나리오 설계](04_GAME_ENGINE_SCENARIO_DESIGN.md)
- [화면 설계](05_SCREEN_DESIGN.md)
- [에이전트 아키텍처 설계](06_AGENT_ARCHITECTURE_DESIGN.md)

영역별 세부 구현 계획은 다음 문서에서 관리한다. 세부 계획서는 이 상위 계획서의
IP 작업과 해당 설계서를 연결하며, 각 문서의 범위를 넘어서는 작업을 정의하지
않는다.

- [DB·Redis 세부 구현 계획](implementation/01_DB_REDIS_IMPLEMENTATION_PLAN.md)
- [API 세부 구현 계획](implementation/02_API_IMPLEMENTATION_PLAN.md)
- [MCP 세부 구현 계획](implementation/03_MCP_IMPLEMENTATION_PLAN.md)
- [게임 엔진 세부 구현 계획](implementation/04_GAME_ENGINE_IMPLEMENTATION_PLAN.md)
- [화면 세부 구현 계획](implementation/05_SCREEN_IMPLEMENTATION_PLAN.md)
- [Agent 세부 구현 계획](implementation/06_AGENT_IMPLEMENTATION_PLAN.md)

설계서의 상세 schema를 이 문서에 복사하지 않는다. 대신 각 작업에서 실제로
사용하는 필드, 함수, 호출 순서, 오류와 테스트를 명시한다.

상태 표기는 `계획`·`구현`·`focused 검증`·`통합 검증`·`완료`로 구분한다.

## 1. 구현 목표와 범위

### 1.1 목표

인간 사용자 1명이 여러 AI 플레이어와 게임을 생성하고, AI가 각자의 제한된
Context 안에서 발언·밤 행동·투표를 수행하며, Backend가 규칙과 최종 상태를
검증하는 서비스를 구현한다.

AI 실행의 구현 결과는 다음과 같다.

```text
게임 작업 생성
→ AI job 예약·권한 발급
→ actor별 Context 조회
→ Provider 구조화 proposal 생성
→ proposal·권한·phase·대상·version 검증
→ MCP/Backend action 제출
→ receipt·게임 상태 반영 확인
→ activity 기록
→ 오류 시 교정·fallback·안전한 종료
```

AI 플레이어별로 독립된 협업 에이전트를 만드는 것이 아니라, 하나의 공통
Agent Workflow를 actor별 Context와 함께 반복 실행하는 구조로 구현한다.

### 1.2 포함 범위

- UUID 기반 사용자 및 게임 생성
- 6~9명 게임의 역할·시나리오·phase·승패
- 낮 토론, 밤 행동, 투표·재투표, 최종 지목
- 저장·재개·관전·결과·feedback
- Backend API와 PostgreSQL transaction
- Redis lock·cache·stream 보조 기능
- Agent Context projection과 proposal 검증
- Dummy/Fake/Local/OpenAI/Gemini Provider
- Agent job·capability·lease·fencing·fallback
- MCP Resource·Prompt·Tool 및 Backend adapter
- AI worker, receipt, game event, activity 기록
- 사용자 Frontend와 read-only 관리자 Frontend
- 단위·통합·장애·E2E 검증

### 1.3 이 계획서의 범위 밖

- 상세 게임 규칙과 API schema의 재정의
- StateGraph library 도입 자체
- 지속 요약 memory의 신규 저장 구조
- 자동 프롬프트 학습
- 실제 유료 LLM을 사용하는 자동 회귀 테스트

## 2. 모듈별 전체 작업 리스트

빈 프로젝트에서 구현하는 권장 순서다. 세부 작업은 3절의 작업 단위로 연결한다.

| 순서 | 작업 ID | 모듈 | 주요 경로 | 구현 결과 | 의존성 |
|---:|---|---|---|---|---|
| 1 | IP-01 | 공통 기반 | `backend/app/core/`, `models/`, `schemas/` | 설정·오류·응답·enum·공통 DTO | 없음 |
| 2 | IP-02 | DB·migration | `backend/migrations/`, `infrastructure/` | schema·migration runner·connection | IP-01 |
| 3 | IP-03 | Repository | `backend/app/repositories/` | game/player/action/event/receipt 저장소 | IP-02 |
| 4 | IP-04 | Game Engine | `backend/app/game_engine/` | 순수 규칙·phase·승패·fallback | IP-01 |
| 5 | IP-05 | Game Service | `backend/app/services/game/` | 생성·command·sync·result·lifecycle | IP-03, IP-04 |
| 6 | IP-06 | Redis·동시성 | `backend/app/infrastructure/redis/` | lock·cache·stream | IP-02, IP-05 |
| 7 | IP-07 | 공개 Backend API | `backend/app/routers/`, `main.py` | health·game·sync·feedback·admin API | IP-05, IP-06 |
| 8 | IP-08 | Agent Context·계약 | `backend/app/agent/`, `llm_provider/schemas.py` | scope projection·proposal DTO·정책 | IP-04, IP-05 |
| 9 | IP-09 | Provider·Agent 실행 | `backend/app/llm_provider/`, `agent/orchestrator.py` | 모델 호출·교정·fallback·job 완료 | IP-03, IP-08 |
| 10 | IP-10 | MCP runtime | `mcp_server/mafia_game/` | FastMCP SDK session·Resource·Prompt·Tool·HTTP adapter | IP-07, IP-08 |
| 11 | IP-11 | AI worker·관찰성 | `ai_progress_worker.py`, `agent/activity.py` | 열린 window 실행·복구·trace | IP-05, IP-09, IP-10 |
| 12 | IP-12 | 사용자·관리자 Front | `frontend_user/`, `frontend_admin/` | 화면·API client·sync·상태 표시 | IP-07, IP-11 |
| 13 | IP-13 | 통합·운영 검증 | `backend/tests/`, `frontend_*/tests/`, `tests/`, `scripts/` | 회귀·장애·DB·브라우저 검증 | IP-01~12 |

작업 순서는 의존성 기준이다. 실제 팀에서는 한 모듈 내부를 병렬 개발할 수
있지만, 계약이 확정되기 전에는 소비 모듈을 구현하지 않는다.

## 3. 작업 단위별 구현 명세

### IP-01. 공통 기반과 도메인 타입

**목적:** 나머지 모듈이 공유할 설정, enum, 오류, schema와 응답 형식을 만든다.

**대상 파일:** `backend/app/core/`, `models/`, `schemas/` 아래의 설정·오류·응답·
enum·game state·game/command/sync/feedback/admin schema 파일.

**구현:** 설정 객체와 환경 변수 검증, phase·action enum, 오류 code, 공통
success/error envelope, snapshot·command·sync 모델을 정의한다. 외부 입력은
Pydantic 검증과 UUID·datetime 정규화를 통과시킨다.

**의존성:** Python 표준 라이브러리와 Pydantic만 사용한다. DB·Redis·LLM을
도메인 모델에 import하지 않는다.

**완료 기준:** 후속 모듈이 같은 enum과 DTO를 import하고, 잘못된 UUID·phase·
command가 schema 단계에서 거부된다.

### IP-02. PostgreSQL schema와 migration 실행

**목적:** 게임 상태의 확정 원장과 재실행 가능한 DB 준비 경로를 만든다.

**대상 파일:** `backend/migrations/001~011_*.sql`,
`backend/app/infrastructure/postgres.py`, `migrations.py`, `transaction.py`.

**구현 순서:** 사용자·scenario·player·fact → game·window·submission·event →
receipt·snapshot·agent job·capability → feedback·audit·knowledge·speech analysis
→ custom role·ability additive migration → version 확인·재실행 검증.

**계약:** PostgreSQL이 확정 원본이다. migration 계정과 runtime 계정을 구분하고,
기존 migration을 수정하지 않고 additive migration을 추가한다.

**완료 기준:** 빈 DB에서 순서대로 재실행 가능하고 schema version·필수 index·
unique receipt·foreign key가 확인된다.

### IP-03. Repository 계층

**목적:** SQL과 도메인 서비스를 분리하고 transaction에서 사용할 저장소를 만든다.

**주요 파일·책임:**

- `game_repository.py`: game·snapshot 조회·저장
- `player_repository.py`: player·role·fact 조회
- `action_repository.py`: window·submission 조회·저장
- `event_repository.py`: event cursor 조회·저장
- `receipt_repository.py`: idempotency receipt 조회·저장
- `agent_repository.py`: job reservation·capability·완료 상태
- `feedback_repository.py`, `admin_repository.py`, `speech_analysis_repository.py`

**계약:** repository는 cursor/transaction 경계를 호출자에게 노출하되 LLM·MCP를
호출하지 않는다. receipt unique 충돌은 기존 결과 재응답 또는 명시적 오류로
처리한다. 조회 결과가 없을 때 임의 기본값으로 상태를 만들지 않는다.

**완료 기준:** CRUD, rollback, 소유권 조건, idempotency, optimistic concurrency
query가 repository 단위 테스트를 통과한다.

### IP-04. 순수 Game Engine

**목적:** 외부 API나 모델 없이 게임 규칙을 결정적으로 실행한다.

**대상 파일:** `backend/app/game_engine/engine.py`, `commands.py`, `errors.py`,
`fallback.py`, `replay.py`, `rng.py`, `phases/`, `rules/` 전체.

**핵심 계약:** Application Service가 command type에 맞는 Game Engine의 phase별
명령 처리를 호출하고, Engine은 유효성 검증 뒤 상태와 event 정보를 변경한다.
fallback은 허용 후보에서만 deterministic 선택하고, RNG는 같은 seed·후보 순서에서
같은 결과를 반환한다.

**구현 순서:** 역할·생존자 → phase 전이 → 토론 → 밤 행동 → 투표·재투표 →
최종 지목 → 승패 → 저장·재개 replay.

**완료 기준:** 6~9명, 역할별 행동, invalid target, 동률, 최대 밤 수, 승패,
재현 가능한 RNG가 외부 서비스 없이 테스트된다.

### IP-05. Game Service와 transaction 조정

**목적:** Engine과 Repository를 조합해 실제 게임 command 경계를 만든다.

**주요 파일·클래스:** `creation_service.py`, `lifecycle_service.py`,
`discussion_command.py`, `action_command.py`, `command_service.py`,
`game_read_service.py`, `snapshot_service.py`, `result_service.py`,
`event_sync_service.py`, `sync_service.py`, `feedback_service.py`,
`postgres_runtime.py`, `runtime_factory.py`.

**처리 계약:**

```text
요청 검증
→ 소유권·현재 상태 잠금
→ receipt 조회
→ Engine 적용
→ state·event·snapshot·receipt 원자 저장
→ sync 결과 반환
```

`expected_state_version`과 idempotency key를 모든 변경 경계에서 확인한다.
Front나 Agent가 phase·승패·valid target을 자체 계산하지 않게 한다.

**완료 기준:** command 중복, stale version, 권한 오류, transaction 실패에서
부분 상태가 남지 않고, 생성부터 종료까지 서비스 호출만으로 실행된다.

### IP-06. Redis와 동시성 보조 기능

**목적:** 확정 원장 위에 lock·cache·stream을 안전하게 추가한다.

**대상 파일:** `backend/app/infrastructure/redis/lock.py`, `cache.py`, `streams.py`.

**계약:** Redis 장애가 PostgreSQL 확정 상태를 바꾸지 않는다. lock key는 game·
window 범위를 포함하고, cache에는 version·cursor·checksum을 함께 저장한다.
private role·capability 원문·미확정 AI 행동은 Redis 공개 cache에 넣지 않는다.

**완료 기준:** 동시 command lock, cache miss 복구, 낮은 version cache 거부,
Redis 장애 시 안전한 기능 축소를 테스트한다.

### IP-07. Backend 공개·관리자 API

**목적:** Front와 관리자 앱이 사용할 HTTP 진입점을 제공한다.

**대상 파일:** `backend/app/main.py`, `routers/health_router.py`,
`game_router.py`, `admin_router.py`, `mcp_registry_router.py`,
`services/admin_service.py`.

**API 그룹:** health/ready, game create/list/detail/delete, command, sync/SSE,
feedback, admin games/detail/metrics/feedback/audit/speech analytics, 내부
agent context/action.

**계약:** `X-User-Id`, `X-Request-Id`, `Idempotency-Key`, `Last-Event-ID`를
형식 검증한다. 공개 응답에서 private role·secret·AI 내부 추론을 제거한다.
내부 API는 game·actor·window·state binding과 Backend 내부 검증을 적용한다. Agent
job capability의 발급·수명·폐기는 Agent 실행 경계에서 관리한다.

**완료 기준:** success/reject/idempotency 응답, CORS/SSE header, 소유권·allowlist·
redaction 테스트가 통과한다.

### IP-08. Agent Context와 proposal 계약

**목적:** AI가 자신의 권한 범위에 맞는 정보와 행동만 사용하도록 만든다.

**대상 파일:** `backend/app/agent/projections.py`, `policies.py`,
`backend/app/llm_provider/schemas.py`, `services/game/actor_context.py`.

**주요 함수·계약:**

- `build_context(...) -> scoped context`
- `_public_data()`, `_me_data()`, `_turn_data()`는 audience별 필드만 반환
- `agent_proposal_schema()`는 작업 종류별 출력 schema를 반환
- `normalize_agent_proposal()`은 모델 출력을 canonical proposal로 변환
- `AgentJobSpec`은 game/player/job/phase/window/version binding을 보존

`SPEAK`는 message만, `VOTE`·`NIGHT_ACTION`은 유효 target만, `PASS`는 금지
필드 없이 허용한다. 모델이 actor·권한·state version을 바꾸지 못하게 한다.

**완료 기준:** actor projection, invalid proposal, 금지 Tool, stale binding,
첫날 발언과 역할별 허용 행동이 테스트된다.

### IP-09. LLM Provider와 AgentOrchestrator

**목적:** Provider를 교체할 수 있는 AI 실행과 제한된 실패 복구를 구현한다.

**대상 파일·클래스:**

- `llm_provider/base.py`: `LLMRequest`, `LLMResponse`, `LLMProvider`
- `dummy.py`, `fake.py`, `local.py`, `openai_provider.py`, `gemini_provider.py`
- `factory.py`, `errors.py`
- `agent/orchestrator.py`: `AgentOrchestrator`, `AgentJobSpec`, `AgentRunResult`
- `repositories/agent_repository.py`: reservation·capability·complete/revoke

**실행 순서:** reserve job → capability·lease 발급 → Context 조립 →
`LLMProvider.generate()` → `normalize_agent_proposal()` → 의미 검증 → 형식 오류
교정 1회 → 장애 fallback → lease·fencing·window 재검사 → proposal 완료 저장.
실제 action 제출과 `APPLIED` 확인은 runtime이 담당한다.

**오류 계약:** timeout, authentication, rate limit, invalid response, MCP
unavailable, stale, denied를 구분한다. 무제한 retry, 임의 target, 임의 상태
재기준화는 금지한다.

**완료 기준:** fake Provider로 정상·교정·timeout·MCP 오류·lease 만료·저장
proposal 복구가 재현되고, 실제 모델 호출 없이 회귀 테스트가 가능하다.

### IP-10. MCP runtime

**목적:** MCP protocol 표면을 제공하되 DB와 Redis를 직접 접근하지 않는다.

**대상 파일:** `mcp_server/mafia_game/main.py`, `api/streamable_session_pool.py`,
`api/resources/`, `api/tools/`, `api/prompts/`, `integrations/engine_http.py`,
`services/resources.py`, `core/audit.py`, `ports/`, `schemas/`, `domain/`.

**계약:** FastMCP SDK session과 요청 binding을 확인하고 Resource·Prompt·Tool 요청은
Backend 내부 HTTP adapter로 전달한다. Agent job capability의 수명 관리는 Backend
Agent 실행 경계에서 담당하며, 현재 MCP wire 요청에는 capability header를 전달하지
않는다. `submit_action` 결과는
`accepted`, `replayed`, typed receipt를 검증한 뒤 반환한다. Tool 입력으로 권한을
확대하지 않는다.

**완료 기준:** 정상 FastMCP session 왕복, 요청 binding·scope 격리, Resource schema,
Tool phase/target 검증, dependency payload redaction을 확인한다. Agent capability의
만료·재사용 검증은 Agent 실행 경계의 별도 검증 항목으로 관리하며, MCP session-level
capability 인증은 운영 보강 범위로 구분한다.

### IP-11. AI worker와 관찰 가능성

**목적:** 열린 AI window를 비동기로 진행하고 판단과 실제 반영을 구분한다.

**대상 함수:** `AiProgressWorker.start()`, `progress_once()`, `wake_votes()`,
`stop()`, `AgentActivity.record()`, `recent()`.

**구현:** worker가 열린 speech/night/vote 작업을 찾고 Agent 실행을 호출한다.
Provider 판단 완료는 `DECIDED`, 실제 게임 반영은 `APPLIED`, fallback 선택은
`FALLBACK`, 중복·만료 폐기는 `SKIPPED` 또는 `STALE`로 기록한다.

**trace 계약:** game/job/window/actor 식별자, stage, action, decision source,
고정 오류 code, state version만 기록한다. raw prompt, capability 원문, private
payload, 모델 내부 추론 전문은 기록하지 않는다.

**완료 기준:** worker 재시작, 열린 window 복구, 늦은 결과 거부, 중복 제출,
공개 activity redaction과 stage 순서가 테스트된다.

### IP-12. Frontend User와 Admin

**목적:** Backend 상태와 command를 사용자 화면으로 연결한다.

**사용자 Front 대상:** `frontend_user/app.py`, `app_pages/`, `components/`,
`core/` 전체. 핵심은 `api_client.py`, `commands.py`, `sync.py`, `session.py`,
`identity.py`, `action_panel.py`다.

**관리자 Front 대상:** `frontend_admin/app.py`, `app_pages/`, `core/` 전체.

**구현 순서:** UUID 초기화 → 홈·생성 → 역할 공개 → game shell → phase별 입력 →
SSE/polling 재연결 → 관전·결과 → feedback → 관리자 dashboard/detail.

**계약:** Front는 규칙·승패·AI 선택을 계산하지 않고 snapshot의 `legal_actions`,
`action_window`, `valid_targets`를 표시한다. sync version/sequence가 어긋나면
부분 적용하지 않고 authoritative snapshot을 재조회한다.

**완료 기준:** loading/empty/error, command 중복, stale, reconnect, private 화면,
AI activity 표시, 관리자 allowlist와 redaction을 합성 API로 검증한다.

### IP-13. 통합·운영 검증

**목적:** 모듈별 성공을 실제 사용자 흐름과 장애 상황의 성공으로 확정한다.

**검증 순서:** 공통 schema·Engine → repository·transaction → Agent Context·
proposal·fallback → MCP session·Resource·Tool → Backend/MCP HTTP 왕복 →
Frontend 합성 API → Team DB 게임 smoke → 브라우저 전체 흐름 → 전체 회귀.

## 4. 테스트 계획과 완료 기준

### 4.1 테스트 매핑

| 테스트 대상 | 실행 대상 | 필수 케이스 |
|---|---|---|
| 공통 schema | `backend/tests/` 관련 테스트 | invalid enum·UUID·필드 누락 |
| Game Engine | Engine phase/rule 테스트 | 6~9명·역할·동률·승패·RNG |
| Repository/DB | `test_b3_infrastructure.py`, migration 테스트 | rollback·receipt·lock·재실행 |
| Agent | `test_b6_agent_manager.py` | 정상·invalid JSON·교정·timeout·fallback·stale |
| Context | `test_actor_context.py` | public/me/turn/persona 격리 |
| Activity | `test_agent_activity.py` | stage·redaction·APPLIED/FALLBACK 구분 |
| MCP | `test_fastmcp_agent_client.py`, `test_mcp_registry_api.py` | session·scope·Tool·receipt |
| 장애 복구 | `test_b9_operational_resilience.py` | timeout·재연결·worker 복구 |
| 발언 분석 | speech analysis 테스트 | fake provider·중복·부분 결과·권한 |
| 사용자 Front | `frontend_user/tests/` | UUID·동기화·투표 보조·오류 화면 |
| 관리자 Front | `frontend_admin/tests/` | allowlist·목록·상세·지표 |
| E2E | Team DB·실제 프로세스·브라우저 | 대표 게임 전체 완주 |

### 4.2 AI 평가 케이스

- 정상 SPEAK, PASS, VOTE, NIGHT_ACTION
- 필수 Context 누락과 다른 actor private 정보 요청
- 허용되지 않은 Tool, 잘못된 target·phase
- Provider timeout·인증 실패·잘못된 JSON
- MCP session 만료와 Backend 403
- state version 변경과 window 만료
- 중복 proposal·receipt replay
- worker 재시작과 저장 proposal 복구
- fallback 후 실제 `APPLIED` 반영

### 4.3 표준 실행 명령

```powershell
pytest backend/tests/test_b6_agent_manager.py -q
pytest backend/tests/test_agent_activity.py -q
pytest backend/tests/test_actor_context.py -q
pytest backend/tests/test_fastmcp_agent_client.py -q
pytest frontend_user/tests -q
pytest frontend_admin/tests -q
pytest -q
```

Team DB 검증은 migration·seed·DB/Redis health를 먼저 확인하고 테스트 전용 게임과
자료만 사용한다. 유료 Provider 자동 호출은 하지 않고 fake/mock을 사용한다.

### 4.4 작업 완료 기준

각 작업은 다음 조건을 모두 만족해야 한다.

- 계획된 파일과 실제 변경 파일이 일치한다.
- 공개·내부 계약이 설계서와 일치한다.
- 정상 경로와 실패·거부 경로가 구현되어 있다.
- 관련 focused test가 통과한다.
- 선행 작업의 회귀 테스트가 통과한다.
- 필요한 경우 실제 DB·MCP·브라우저 왕복 증거가 있다.
- 로그·문서·fixture에 비밀값과 private payload가 없다.
- 구현 완료와 검증 완료가 상태표에서 구분되어 있다.

### 4.5 최종 MVP 완료 기준

- [ ] 빈 DB에서 migration과 seed를 재현할 수 있다.
- [ ] 인간 사용자가 6~9명 게임을 생성할 수 있다.
- [ ] 역할 공개부터 게임 종료까지 주요 phase가 동작한다.
- [ ] AI가 actor별 허용 Context 안에서 proposal을 생성한다.
- [ ] 잘못된 proposal·target·version이 Backend에서 거부된다.
- [ ] Provider/MCP 실패 시 retry 상한과 fallback이 동작한다.
- [ ] AI 판단 완료와 실제 게임 반영이 trace에서 구분된다.
- [ ] 저장·재개·재접속·중복 요청이 원장 기준으로 안전하다.
- [ ] 사용자 Front와 관리자 Front가 실제 Backend 계약으로 동작한다.
- [ ] 대표 게임의 전체 E2E가 완료된다.
- [ ] focused test와 전체 회귀 테스트 결과가 기록된다.

## 5. 구현 상태 추적표

| 작업 ID | 구현 상태 | focused test | 통합 검증 | 남은 문제 | 근거 |
|---|---|---|---|---|---|
| IP-01 | 구현 | 관련 schema 테스트 | 미확인 | 실행 결과 갱신 필요 | `backend/app/core/`, `models/`, `schemas/` |
| IP-02 | 구현 | migration 테스트 | 미확인 | 전체 rollback은 제공하지 않음 | `backend/migrations/`, `infrastructure/migrations.py` |
| IP-03 | 구현 | repository 테스트 | 미확인 | 실행 결과 갱신 필요 | `backend/app/repositories/` |
| IP-04 | 구현 | Engine 테스트 | 미확인 | 실행 결과 갱신 필요 | `backend/app/game_engine/` |
| IP-05 | 구현 | game service 테스트 | 미확인 | 실행 결과 갱신 필요 | `backend/app/services/game/` |
| IP-06 | 구현 | infrastructure 테스트 | 미확인 | 실행 결과 갱신 필요 | `backend/app/infrastructure/redis/` |
| IP-07 | 구현 | Backend API 테스트 | 미확인 | 실행 결과 갱신 필요 | `backend/app/routers/` |
| IP-08 | 구현 | Context·proposal 테스트 | 미확인 | 별도 Agent 설계서는 추후 작성 | `backend/app/agent/`, `llm_provider/` |
| IP-09 | 구현 | Agent Manager 테스트 | 미확인 | 실행 결과 갱신 필요 | `backend/app/agent/orchestrator.py` |
| IP-10 | 구현 | MCP 테스트 | 미확인 | 공개 interface와 내부 처리 구분 유지 | `mcp_server/mafia_game/` |
| IP-11 | 구현 | worker·activity 테스트 | 미확인 | 실행 결과 갱신 필요 | `ai_progress_worker.py`, `agent/activity.py` |
| IP-12 | 구현 | User/Admin Front 테스트 | 미확인 | 실행 결과 갱신 필요 | `frontend_user/`, `frontend_admin/` |
| IP-13 | focused 검증 | 테스트 파일 존재 | 통합 실행 필요 | Team DB·브라우저 결과 갱신 필요 | `backend/tests/`, `frontend_*/tests/` |

이 표는 현재 코드와 테스트 파일의 정적 확인을 반영한 상태다. `구현`은 구현
구성요소가 존재한다는 뜻이며 테스트 통과를 의미하지 않는다. 테스트 명령과 실제
DB·MCP·브라우저 왕복 결과를 확인한 뒤 `focused 검증`, `통합 검증`, `완료`로
단계적으로 갱신한다.
