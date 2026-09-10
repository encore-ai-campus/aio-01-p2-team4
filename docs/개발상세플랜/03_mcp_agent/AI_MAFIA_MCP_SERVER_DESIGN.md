# AI 마피아 MVP MCP Server·Data Infrastructure 개발 설계서

> **MVP 단순화 프로파일:** 이 문서의 bootstrap token, Engine HMAC, capability
> state machine, custom session registry, agent lease/fencing, outbox 소비 및
> 자동 Provider failover 설계는 운영 정본 실행 경로에서 제외한다. DB·스키마·
> migration은 변경하지 않으며 해당 구조는 legacy 호환 문서로만 보존한다.

**문서 상태:** 구현 기준 확정안

**대상 패키지:** `mcp_server/mafia_game`

**최종 갱신:** 2026-09-03

> **현재 구현 기준 (2026-09-05):** 이 설계서의 bootstrap token, HMAC, nonce,
> custom session registry, Engine consume와 다중 Resource·Tool WU는 아직 구현하지
> 않는다. 현재 실행 경로는 [API 명세](../01_core/AI_MAFIA_API_SPEC.md) 상단 최소 프로파일의
> Resource·Prompt·Tool 등록부와 Backend 내부 endpoint다. 아래의
> 확장 설계는 후속 합의 전까지 실행 지시로 사용하지 않는다.

## 1. 목적과 정본 우선순위

2026-09-07 보완은 기존 최소 FastMCP Resource에 AI actor·scope 전달을 추가한다.
URI와 endpoint 계약은 API 명세의 `현재 FastMCP actor projection 보완` 절을 따른다.
WU-M3의 기존 resources 등록부와 integrations/engine_http.py가 이를 담당하며
다섯 data schema를 이 문서에 복제하지 않는다. 별도 인증 registry나 DB 직접 접근을
추가하는 작업은 아니다.

이 문서는 Mafia Game MCP runtime과 MCP·Data Infrastructure 작업 단위의 구현 구조,
선행조건, 검증 방법과 완료 증거를 정의한다. 제품 규칙, 저장 계약과 wire schema를
새로 정의하는 문서가 아니다.

| 계약 영역 | 정본 |
|---|---|
| 제품 규칙·소유권·WU·CP | [AI_MAFIA_MASTER_PLAN.md](../01_core/AI_MAFIA_MASTER_PLAN.md) |
| PostgreSQL·Redis·transaction·migration | [AI_MAFIA_DB_DESIGN.md](../02_backend_data/AI_MAFIA_DB_DESIGN.md) |
| 내부 Engine HTTP·MCP wire·5개 Resource `data` schema | [AI_MAFIA_API_SPEC.md](../01_core/AI_MAFIA_API_SPEC.md) |
| 섹터 간 최소 연결 형식 | [AI_MAFIA_INDEPENDENT_CONTRACT.md](../01_core/AI_MAFIA_INDEPENDENT_CONTRACT.md) |
| 사용자·관리자 화면 | [AI_MAFIA_SCREEN_FLOW.md](../04_frontend/AI_MAFIA_SCREEN_FLOW.md) |
| 현재 구현 상태·실행 명령 | [루트 README](../../../README.md) |

충돌 시 `AGENTS.MD`, 영역별 정본, 이 설계서 순으로 판정한다. 특히 다섯 MCP
Resource의 상세 `data` field, enum, nullable, union과 길이 제약은 API 명세 8.2절과
그 절이 명시적으로 참조하는 API 공통 모델만 정본이다. 이 문서의 매핑과 예시는
이해를 돕는 비규범 자료이며 fixture나 validator를 만드는 근거로 단독 사용하지 않는다.
구현 validator는 API 정본을 코드로 옮기되 별도 문서 계약을 만들지 않는다.

한 coding AI agent 세션은 마스터플랜의 WU 한 개 이하만 구현한다. 이 문서 전체를 한
세션에 구현하도록 지시하지 않는다.

## 1.1 현재 MVP FastMCP 전환 프로파일

2026-09-07 투표 보조 정보의 WU-M9는 Backend 소유 006 migration의 실행·재실행과
계정·권한·health 검증만 담당한다. pgvector가 없는 PostgreSQL에서도 적용하며
저장 상세는 DB 정본의 공개 AI 발언 분석 절을 따른다. 검증은 별도 합성 QA DB에서
수행하고 사용 중 DB와 구분한다. 발언 분석·OpenAI 호출·조회 API는 Backend가
소유하며 MCP runtime의 Resource schema나 DB 접근 권한은 추가하지 않는다.

현재 작업은 이 문서의 전체 운영 보안 프로파일을 한 번에 구현하지 않는다. FastMCP는
`mcp_server/mafia_game/main.py`를 composition root로 사용하고, 기존 디렉터리 안의
`api/resources/`, `api/prompts/`, `api/tools/` 등록 모듈을 통해 컨텍스트 표면을
제공한다. Resource·Tool handler는 Backend adapter 호출과 결과 전달을 담당하고,
Prompt는 MCP 소유 지침 생성 모듈을 사용한다. Tool의 게임 판정과 상태 변경은 Backend 책임이다.

현재 FastMCP 전환에서는 MCP 내부 HMAC·bootstrap token·capability state machine·
session registry·idle timeout·DELETE cleanup을 새로 추가하지 않는다. 이 문서의 기존
M2~M8 세션·Engine HMAC·proposal 상세는 후속 운영 프로파일이며, 현재 MVP 전환의
작업 기준과 충돌하는 항목은 현재 프로파일을 우선한다.

## 2. 확정 결정

1. Backend 규칙 엔진이 유일한 authoritative game engine이다. MCP runtime은 게임을
   판정하거나 상태를 저장하지 않고 Backend 내부 Engine API만 호출한다.
2. AI player는 `public`, `me`, `turn`, `persona` 허용 집합의 nonempty 부분집합과
   capability가 허용한 행동 Tool만 사용한다.
3. AI GM은 `public`, `gm-guide` 허용 집합의 nonempty 부분집합만 읽고 행동 Tool을
   갖지 않는다. 생성한 narration은 MCP proposal 경로가 아니라 LLM adapter에서
   Backend Agent Manager로 직접 반환된다.
4. `agent_jobs` reservation 한 건마다 새 capability, 일회성 MCP 세션 개설
   토큰(bootstrap token)과 새 MCP session을 만든다. terminal 처리 뒤 모두 폐기하며
   reconnect에도 이전 값을 재사용하지 않는다.
5. proposal 전송 결과가 불명확해 재시도한다면 같은 `proposal_id`와 같은 body를
   사용한다. 새 상태로 version이나 target을 자동 보정하지 않는다.
6. MCP runtime은 PostgreSQL·Redis에 직접 접근하지 않고 Backend `event_outbox`도
   사용하지 않는다. WU-M5는 별도 영속 outbox가 아닌 allowlist 구조화 운영 로그와
   redaction을 구현한다.
7. MCP·Data 담당자의 PostgreSQL·Redis 책임은 실행 환경, 계정·권한, Backend 작성
   migration의 실행·재실행과 health 확인이다. schema·migration SQL·repository·Redis
   application code는 Backend 소유다.
8. MCP context cache는 session-local을 포함해 두지 않는다. Resource list는
   consume binding만 사용하고 Engine 0회, 허용 read는 Engine GET 1회,
   거부 read는 Engine 0회를 고정한다. 요청 처리 중 transient local object는 허용하되
   요청 종료 뒤 Resource JSON·model·text의 retained reference와 재사용, stale fallback은
   금지한다.

## 3. 범위와 비범위

### 3.1 포함 범위

- MCP Streamable HTTP endpoint `${MAFIA_MCP_URL}`의 `/mcp` session
- 세션 개설 토큰 서명 검증과 Engine consume
- job·subject·capability에 고정된 session memory
- 다섯 Resource의 URI 등록, Engine scope 변환과 폐쇄형 응답 검증
- 네 행동 Tool의 입력 검증과 Engine proposal adapter
- Engine HMAC 요청 생성, 오류 정규화와 취소 전파
- 모든 MCP 경로의 allowlist 구조화 로그와 중앙 redaction
- fake Engine 기반 독립 계약 테스트와 실제 Backend 통합 검증
- PostgreSQL·Redis 실행 환경, 계정·권한, migration 실행·health runbook

### 3.2 비범위

- 게임 규칙·대상·승패·fallback 결과의 자체 판정
- DB schema, migration SQL, repository와 Redis key·lock·publisher 구현
- PostgreSQL·Redis·embedding/vector 저장소를 호출하는 MCP adapter
- Backend `event_outbox` 소비·수정 또는 MCP 전용 DB·queue·audit outbox
- LLM Provider 호출, prompt 조립, GM 결과 저장과 Agent worker scheduling
- Front 공개 API, 화면, OAuth·사용자 인증 구현
- 자동 Provider failover, token·비용·예산·조정 가능한 LLM timeout

현재 `mcp_server/mafia_game`에는 WU-M2/M3의 실행 entrypoint·session·Resource·Engine
adapter·독립 테스트와 WU-M5의 기존 경로 로그 선행 구현이 있다. Tool은 아직 없다.
일부 예약 `__init__.py`의 여행 도메인 placeholder와
`integrations/database`, `integrations/redis`, `integrations/embedding` 디렉터리는 구현
권한을 뜻하지 않는다. 삭제·이동·이름 변경이 필요하면 착수 전 정본과 README를 먼저
갱신하고 구조 변경 합의를 거친다.

현재 Backend scaffold client는 `8010/mcp` 기본값과 `game_ping`, `game_get_context`,
`game_submit_proposal` placeholder Tool을 사용하며 세션 개설 토큰·capability header가
없다.
목표 계약은 `8100/mcp`, 다섯 Resource와 네 Tool이다. `WU-B6`·`WU-B7`과 `WU-M6`에서
target client로 교체하며 MCP runtime에 legacy Tool alias를 추가해 이 scaffold를
유지하지 않는다.

## 4. 시스템 경계와 의존 방향

```text
Browser
  -> Frontend
    -> Backend public API
      -> authoritative game engine / Agent Manager / LLM adapter
          |                         |
          | 세션 개설 토큰 + capability | GM_NARRATION direct return
          v                         v
        Mafia Game MCP ----------> Backend internal Engine API
          Resource / Tool             validate / persist / fallback

PostgreSQL <-> Backend repository
Redis      <-> Backend cache·lock·publisher

MCP·Data 담당자 -> PostgreSQL·Redis 실행 환경·계정·migration·health 운영
MCP runtime     -X-> PostgreSQL·Redis
```

Backend는 LLM·MCP 외부 호출 동안 PostgreSQL transaction이나 Redis game lock을
보유하지 않는다. MCP 장애 때 동일 audience의 검증된 snapshot을 다시 투영하거나
규칙 기반 fallback을 확정하는 주체도 Backend Agent Manager다.

### 4.1 package 의존 방향

```text
api -> services -> ports <- integrations
           |
         domain

schemas와 core는 위 계층이 공유하는 검증·설정·오류·보안 정책을 제공한다.
```

| 계층 | 책임 | 금지 사항 |
|---|---|---|
| `api` | Streamable HTTP, initialize, Resource·Tool 등록과 protocol 변환 | Engine 규칙 판정 |
| `services` | 세션 개설 인증, Resource 조회, proposal 제출 orchestration | HTTP SDK·DB 세부 구현 결합 |
| `ports` | Engine transport, clock, ID 생성기, 안전한 log sink 추상 경계 | concrete client 생성 |
| `integrations` | 서명된 HTTP Engine adapter | DB·Redis·embedding adapter 사용 |
| `domain` | session subject, capability binding, 허용 operation의 순수 불변식 | MCP·HTTP import |
| `schemas` | 정본 wire 입력·응답의 폐쇄형 validation | 정본 밖 field·enum 추가 |
| `core` | 설정 allowlist, 고정 오류, HMAC·redaction 공통 정책 | secret·payload log |

`OPEN-01`은 다음과 같이 확정한다.

- `mcp_server/`를 독립 프로젝트 루트로 사용하고 Python import package는
  `mafia_game`으로 고정한다. `mcp_2`는 후속 예약 package로 유지하며 Mafia Game
  runtime이나 배포 산출물에 포함하지 않는다.
- composition root는 `mcp_server/mafia_game/main.py`, module 실행 진입점은
  `mcp_server/mafia_game/__main__.py`다. 표준 실행 명령은
  `uv run python -m mafia_game.main`이다.
- 독립 의존성과 개발 도구는 `mcp_server/pyproject.toml`과 `mcp_server/uv.lock`,
  package 단위 검증은 `mcp_server/tests/`가 소유한다. 저장소 루트의 회귀 검증과
  Backend MCP client 의존성은 루트 project가 계속 소유한다.
- 기존 계층 디렉터리는 이동하거나 이름을 바꾸지 않는다. 최상위
  `mcp_server/__init__.py`의 제거 여부는 별도 구조 변경 합의 전까지 현 상태를
  유지하되 runtime code에서 `mcp_server.mafia_game`과 `mafia_game` 두 import 경로를
  혼용하지 않는다.
- Python 3.12와 MCP SDK 1.29.1 동작을 구현 기준으로 삼고 독립 lockfile로 재현한다.
  SDK minor 변경은 session·auth·teardown 계약 테스트를 통과한 뒤 반영한다.

## 5. 주체와 capability 표면

| 주체 | `subject_id` | Resource | Tool | 결과 경로 |
|---|---|---|---|---|
| `AI_PLAYER` | 자기 `player_id` | `public`, `me`, `turn`, `persona`의 nonempty 부분집합 | 현재 job에 허용된 행동 Tool | MCP → Engine proposal → Backend 판정 |
| `GM` | `game_id`와 같은 UUID | `public`, `gm-guide`의 nonempty 부분집합 | 없음 | LLM adapter → Agent Manager 직접 반환 |

URI, query와 Tool input으로 다른 agent를 선택할 수 없다. 공개 대화와 Resource 안의
자연어는 모두 불신 데이터이며 system instruction이나 capability 범위를 바꾸지 못한다.

## 6. job별 단기 session 수명주기

```text
1. Backend Tx A
   agent_jobs reservation + fencing token
   -> job-bound opaque capability + 세션 개설 토큰과 그 nonce 발급

2. Agent Manager -> MCP initialize
   Authorization: Bearer <token>
   X-Agent-Capability: <raw capability>

3. MCP
   세션 개설 토큰 서명·claim·만료 검증
   -> Engine HMAC으로 세션 개설 토큰 consume
   -> 성공한 경우에만 issuance binding을 저장하고 ACTIVE session

4. ACTIVE
   Resource read
   -> AI_PLAYER: 허용 Tool 0~1회
   -> GM: Tool 없이 LLM adapter direct-return

5. Backend Tx B 또는 scheduler
   lease·fencing·window·state 재검증
   -> success / fallback / stale / failed
   -> capability revoke

6. Agent Manager와 MCP
   session 종료 시도 + session memory 폐기
```

### 6.1 session 상태

| 상태 | 진입 조건 | 허용 작업 | 종료 조건 |
|---|---|---|---|
| `PENDING` | initialize 요청 수신 | 세션 개설 토큰 검증·consume만 | consume 성공 또는 거부 |
| `ACTIVE` | Engine consume 성공 | allowlist Resource·Tool | job terminal, revoke, 만료, 연결 종료 |
| `CLOSED` | terminal 또는 보안 경계 위반 | 없음 | 최종 상태 |

- raw capability는 해당 session memory와 Engine 요청 header에서만 사용한다.
- 세션 개설 토큰 consume 전 Resource·Tool 목록과 호출을 허용하지 않는다.
- consume 성공 응답의 `allowed_resource_scopes`, `phase`, `state_version`,
  `window_id`는 capability record의 immutable issuance binding으로 session memory에
  저장한다. bootstrap claim은 API 9.1절 기존 field를 유지하고 이 binding을
  추가하지 않는다.
- consume 성공 응답 raw JSON의 duplicate member, invalid JSON 또는 5-field 폐쇄형
  binding 위반은 fail-closed한다. 기존 status-only 성공 응답은 허용하지 않는 breaking
  동기 전환이므로 MCP `WU-M3`와 Backend `WU-B7`이 같은 5-field shape로 함께 전환한다.
- phase, window 또는 state version이 바뀌면 기존 capability와 결과는 stale이다.
- 성공뿐 아니라 fallback, stale, failed(호출 취소 포함)와 lease 만료 경로에서도
  revoke·memory 폐기를 수행한다.
- 연결 단절 뒤 소비한 세션 개설 토큰, raw capability와 `Mcp-Session-Id`를 다시 사용하지
  않는다. 같은 lease의 job을 계속할 자격이 Backend에 남아 있을 때만 새 세 값을
  발급한다.
- `OPEN-02`는 세션마다 fresh low-level `mcp.server.lowlevel.Server`를 만들고, 그
  child application마다 정확히 하나의 stateful `StreamableHTTPSessionManager`
  (`stateless=False`, `event_store=None`, `json_response=True`,
  `session_idle_timeout=None`)를 만드는 것으로 확정한다. top-level session lifecycle
  pool은 SDK 공개 constructor·`run()`·`handle_request()`만 사용해 manager별 `run()`
  context를 정확히 한 번 소유한다. 이는 SDK의 one-manager-per-application 안내와
  stateful·private API 금지, 아래 30초 외부 reaper를 함께 지키며, 명시적 terminal 뒤
  해당 manager의 `run()`을 끝내 transport와 owner tombstone을 폐기하기 위한 MCP 내부
  구조다. stateless 전환, SDK monkeypatch, private map·method 접근은 금지한다.
- 최초 initialize 요청은 bearer 세션 개설 토큰과 `X-Agent-Capability`를 함께 검증하고
  Engine consume 성공 뒤에만 session transport와 `ACTIVE` memory를 노출한다. 같은
  활성 session의 후속 HTTP 요청은 최초와 같은 bearer를 보내되 capability header를
  다시 보내지 않는다. 후속 bearer는 같은 session owner인지 확인하는 용도이며
  세션 개설 토큰 consume을 다시 실행하지 않는다.
- 정상 종료는 Streamable HTTP `DELETE /mcp`와 `Mcp-Session-Id`를 사용한다. Tool의
  terminal 결과, Backend의 종료 요청, capability·세션 개설 토큰 만료, transport 종료,
  process shutdown에서도 같은 멱등 cleanup을 호출한다.
- stateful session idle TTL은 30초로 고정한다. 세션 개설 토큰 `exp` 또는 Backend
  capability 거부가 더 먼저 도달하면 TTL과 관계없이 즉시 닫는다. session memory는
  파일·DB·Redis·event store에 저장하지 않는다.
- 30초 외부 reaper는 만료 후보별 cleanup을 독립 dispatch하고 같은 binding의 중복
  dispatch를 억제한다. session gate 안에서는 만료 재확인과 registry·pool route 종료
  소유권만 확정하며, SDK `DELETE`와 manager `run()` 종료는 gate·registry lock 밖에서
  수행한다. 따라서 한 session의 transport 종료가 지연되어도 현재·이후 다른 session의
  route 제거와 teardown 시작을 막지 않는다.
- consume 응답을 받지 못하면 성공을 추측하거나 같은 세션 개설 토큰을 다시 consume하지
  않고 해당 transport와 memory를 폐기한다. fresh credential 조정은 `OPEN-07`의
  Backend 절차를 따른다.
- 종료 실패가 기존 자격을 다시 유효하게 만들 수는 없다.

## 7. Resource 설계

### 7.1 URI 매핑

아래 표는 routing 매핑일 뿐 `data` schema 정의가 아니다.

| MCP URI | Engine 요청 | 허용 subject | 용도 | schema 정본 |
|---|---|---|---|---|
| `mafia://session/public` | `scope=public` | AI_PLAYER, GM | 공개 game·scenario·player·event | API 8.2.1 |
| `mafia://session/me` | `scope=me` | AI_PLAYER | 자기 role·개인 사실·private event | API 8.2.2 |
| `mafia://session/turn` | `scope=turn` | AI_PLAYER | 현재 window·Tool·target·deadline | API 8.2.3 |
| `mafia://session/persona` | `scope=persona` | AI_PLAYER | 배정된 검증 persona | API 8.2.4 |
| `mafia://session/gm-guide` | `scope=gm-guide` | GM | 공개 event 또는 고정 문구 guide | API 8.2.5 |

AI_PLAYER와 GM이 공유하는 URI는 `public` 하나다. GM의 Resource 목록에 `me`, `turn`,
`persona`가 나타나거나 Tool 목록이 비어 있지 않으면 계약 위반이다.

raw MCP JSON-RPC 요청은 duplicate member를 허용하지 않는 decoder로 해석한다. 중복
member를 last-value-wins로 병합하지 않고 `-32602`로 fail-closed한다.

`resources/list`는 session에 저장한 `allowed_resource_scopes`만 사용해
`public`, `me`, `turn`, `persona`, `gm-guide` canonical order로 반환한다.
각 descriptor는 `uri`, scope 문자열인 `name`,
`mimeType=application/json` 세 field만 갖는 폐쇄형 object다. list 처리에서
Engine 호출은 0회다. 요청에 `cursor` field가 아예 없어야 하며 존재하면
`-32602`로 거부한다. 응답은 pagination·`nextCursor`를 제공하지 않는다.

MCP SDK 1.29.1의 Resource handler 등록으로 initialize 응답에 포함되는
`capabilities.resources`는 `subscribe=false`, `listChanged=false`로 고정한다. 이는
미지원 기능의 canonical 광고다. Resource template과 `resources/templates/list`,
`notifications/resources/list_changed`는 제공하지 않는다.

### 7.2 adapter 처리 순서

1. 현재 session이 `ACTIVE`인지 확인한다.
2. SDK의 `AnyUrl` 정규화 전에 raw `params.uri` 문자열이 상수 registry의 exact 다섯
   값 중 하나인지 확인하고 Engine scope로 변환한다. percent-encoding, case,
   trailing slash·문자 등 변형을 모두 거부한다.
3. scope가 session의 `allowed_resource_scopes`에 있는지 확인한다.
4. 2·3단계 실패는 존재를 숨긴 `-32002 CAPABILITY_DENIED`로 반환하고
   Engine을 호출하지 않는다.
5. 허용된 read에서 session capability로 해당 scope Engine HMAC GET을
   정확히 한 번만 보낸다.
6. 공통 envelope의 job subject·scope와 consume binding의 `phase`,
   `state_version`, `window_id` 일치를 확인한다.
7. API 8.2절의 해당 공통 envelope·폐쇄형 `data` schema와 단일 응답
   내에서 관측할 수 있는 불변식을 검증한다. raw JSON의 duplicate member는
   last-value-wins로 병합하지 않고 `-32004`로 거부한다.
8. URI가 같은 `application/json` text content 한 개로 직렬화한다.

Engine이 unknown field나 audience 금지 field를 반환하면 silent strip하지 않고
Resource read를 fail-closed한다. Backend는 매 GET에서 revoke·현재 상태,
projection provenance와 cross-scope 의미 불변식을 최종 판정한다. MCP는
추가 scope GET이나 이전 응답 비교로 이 판정을 재구성하지 않는다.

MCP context cache는 session-local을 포함해 두지 않는다. 한 요청을
decode·검증·직렬화하는 동안의 transient local object는 허용하지만 요청 종료 뒤
Resource JSON, 검증된 model object, 직렬화 text의 retained reference를 남기거나 다음
요청에서 재사용하지 않는다. Engine 오류에서 stale fallback으로 반환하지 않는다.

### 7.3 매핑 예시

```text
AI player가 mafia://session/turn을 읽음
-> registry가 scope=turn으로 변환
-> GET /internal/v1/agent-context?scope=turn 1회
-> API 8.2 공통 envelope와 8.2.3 data validator 통과
-> 같은 URI의 application/json content 반환
```

```text
GM이 mafia://session/me를 직접 요청
-> subject/URI allowlist에서 즉시 거부
-> Engine private projection 호출 0회
-> payload 없는 고정 protocol 오류만 반환
```

예시의 생략된 payload를 fixture로 복원하지 않는다. 실제 fixture field와 값은 항상 API
명세 8.2절에서 생성한다.

## 8. Tool과 Engine proposal

| MCP Tool | Engine proposal type | 모델 입력 | 허용 window |
|---|---|---|---|
| `propose_speech` | `SPEAK` | `message`, `public_rationale` | 자기 발언 차례 |
| `propose_pass` | `PASS` | 없음 | 자기 발언 차례 |
| `propose_night_action` | `NIGHT_ACTION` | `target_player_id` | 생존 특수 역할의 밤 |
| `propose_vote` | `VOTE` | `target_player_id` | 일반·재·최종 투표 |

Tool input은 폐쇄형이다. `game_id`, `agent_id`, role, phase, window와 version은 모델
입력으로 받지 않고 session과 capability에서 가져온다.

처리 순서:

1. MCP schema로 Tool input의 타입·길이·unknown field를 검사한다.
2. 첫 Engine 전송 전에 UUID v4 `proposal_id`를 한 번 만든다.
3. session binding과 input으로 API 8.4절 proposal을 조립한다.
4. 새 HMAC timestamp·nonce·signature와 capability로 Engine에 전달한다.
5. Engine의 terminal 결과만 MCP Tool 결과로 변환한다.
6. terminal 결과 뒤에는 추가 Tool을 거부하고 session 종료 절차로 이동한다.

MCP 성공은 Backend 규칙 엔진이 proposal을 검증·반영했다는 응답이지 MCP가 판정했다는
뜻이 아니다. role·phase·target·deadline·중복·state version은 Backend가 다시
검증한다.

응답 유실로 같은 살아 있는 job에서 다시 전송한다면 `proposal_id`와 canonical body는
동일하고 HMAC nonce만 새 값이어야 한다. body 변경, 새 target 선택, version rebase와
다른 job에서의 ID 재사용은 금지한다. session 자체가 유실된 경우 Agent Manager가
Backend의 job 상태를 먼저 조정하며 MCP가 결과를 추측하지 않는다.

## 9. AI GM direct-return

```text
MCP public + gm-guide
  -> Backend LLM adapter가 GM에게 제공
  -> GM_NARRATION structured result
  -> Backend Agent Manager 직접 반환
  -> schema·guide reference·PUBLIC 범위·lease/fencing/window/state 재검증
  -> PUBLIC event 또는 고정 한국어 fallback
```

- GM session에는 Tool이 하나도 없고 `/internal/v1/agent-proposals`를 호출하지 않는다.
- GM 결과 schema의 정본은 API 10.2절이다. MCP package에 중복 schema나 GM submit Tool을
  만들지 않는다.
- GM이 읽는 event는 이미 `PUBLIC` projection이어야 한다. 공격자, 보호 대상, 조사
  결과, 개별 투표와 role-conditioned target은 전달하지 않는다.
- 공개 텍스트의 prompt injection은 명령이 아니라 game data로 처리한다.
- 잘못됐거나 늦은 GM 결과의 교정·fallback·저장은 Backend 책임이다.

## 10. 내부 Engine HTTP adapter

MCP가 호출하는 path는 세 개뿐이다.

```text
GET  /internal/v1/agent-context?scope=...
POST /internal/v1/mcp-bootstrap/consume
POST /internal/v1/agent-proposals
```

모든 요청은 API 8.1절의 canonical HMAC을 사용한다. adapter는 대문자 method, raw path,
정렬된 canonical query, raw body hash, timestamp와 UUID v4 nonce를 정확히 서명한다.
signature는 padding 없는 base64url이고 constant-time 비교는 Backend가 수행한다.

MCP는 opaque capability를 decode하거나 자체 권한 token으로 검증하지 않는다. 세션
개설 토큰 서명 검증은 session 개설 권한 확인이고, Engine은 매 context
GET에서 capability hash·job·subject·allowlist·expiry·revoke·현재 DB 상태와
projection provenance·cross-scope 의미 불변식의 최종 판정자다.
`MCP_SERVER_AUTH_SECRET`과
`ENGINE_INTERNAL_API_SECRET`은 방향과 용도가 다르며 같은 값을 쓰지 않는다.

## 11. 오류·fallback·재접속

운영 FastMCP HTTP adapter는 연결·timeout·Backend HTTP 상태·JSON 형식 실패를
비밀값 없는 고정 오류 코드로 표현한다. Backend MCP client도 RPC·응답 계약 실패를
구분하며 내부 진행 로그에 발생 scope와 작업 binding을 남긴다. 상세 진단은 내부
로그 전용으로, 공개 `MCP_UNAVAILABLE`나 fallback 결과·권한 검증을 바꾸지 않는다.
같은 게임·actor의 기대 phase·window·버전이 달라진 응답은 기존 `STALE` 결과로
폐기한다. 이 경우 PASS proposal이나 `FALLBACK`을 기록하지 않고 `SKIPPED`로 끝낸다.
구형 MCP의 역할 지침 누락과 구형 Backend의 persona 0.5 고정 검증은 정상 응답으로
우회하지 않으며, 양쪽을 같은 계약 버전으로 갱신한 뒤 네 scope 왕복을 확인한다.

| 상황 | MCP 처리 | Backend 처리 |
|---|---|---|
| 세션 개설 토큰 누락·변조·만료·replay | session 비활성, 고정 거부 | 새 job 자격 검토 또는 fallback |
| capability denied·stale | 상세 이유를 숨긴 고정 거부 | 현재 reservation·상태 판정 |
| Resource URI 미등록·미허용 | 존재 은닉 `-32002`, Engine 0회 | 관여하지 않음 |
| Resource schema/audience 위반 | fail-closed, payload 비노출·stale fallback 금지 | 검증된 동일 audience projection 또는 game fallback 판정 |
| Tool input 오류 | Engine 호출 전 고정 validation 오류 | 필요 시 한 번 교정 후 fallback |
| Engine timeout·연결 단절·429·5xx | 상태 추측·자체 fallback 금지 | job/receipt 조정 후 retry 또는 fallback |
| proposal 응답 유실 | 동일 ID·body만 재전송 가능 | idempotency terminal 결과 반환 |
| MCP session 유실 | 기존 자격 재사용 금지 | 살아 있는 job만 fresh reconnect |
| GM 출력 오류·late result | 관여하지 않음 | 교정 1회, fencing 검사, 고정 문구 또는 stale |
| logger/sink 장애 | 게임 payload spool 금지 | 게임 상태와 무관하게 운영 경보 |

`OPEN-03`은 다음 고정 매핑으로 확정한다. HTTP 인증 오류 body는 표의 `공개 code`만
가진 `{"error":"<code>"}`이고, JSON-RPC 오류는 표의 숫자 code와 고정 한국어
message만 가지며 `data`를 넣지 않는다.

| 경계 | 조건 | HTTP/JSON-RPC | 공개 code |
|---|---|---:|---|
| initialize | bearer 또는 capability header 누락·형식 오류 | HTTP 401 | `AUTH_REQUIRED` |
| initialize | 세션 개설 토큰 서명·claim·만료·replay·mismatch 또는 consume 거부 | HTTP 403 | `BOOTSTRAP_DENIED` |
| session | 알 수 없거나 이미 닫힌 `Mcp-Session-Id` | HTTP 404 | `SESSION_NOT_FOUND` |
| protocol | raw JSON-RPC duplicate member, Tool 폐쇄형 입력 오류 또는 `resources/list`의 `cursor` 존재 | `-32602` | `VALIDATION_ERROR` |
| handler | 비활성 session 또는 terminal 뒤 추가 호출 | `-32001` | `SESSION_NOT_ACTIVE` |
| Resource·Engine context | local exact registry·session allowlist 거부 또는 Engine 403·존재 은닉 404 | `-32002` | `CAPABILITY_DENIED` |
| Engine context | timeout·연결 단절·429·5xx | `-32003` | `DEPENDENCY_UNAVAILABLE` |
| Engine context | 그 밖의 1xx·200 외 2xx·3xx·예상 밖 4xx, 잘못된 Content-Type·invalid JSON·duplicate member, 200 응답의 binding·envelope·schema·응답 내부 불변식 위반 | `-32004` | `UPSTREAM_CONTRACT_VIOLATION` |
| proposal | 같은 `proposal_id`의 body conflict | `-32005` | `PROPOSAL_CONFLICT` |
| handler | 위 분류에 포함되지 않은 내부 실패 | `-32603` | `INTERNAL_ERROR` |

- `-32002` message는 `요청한 리소스에 접근할 수 없습니다.`로 고정한다.
- `-32003` message는 `게임 컨텍스트를 불러올 수 없습니다.`로 고정한다.
- `-32004` message는 `게임 컨텍스트 응답 형식이 올바르지 않습니다.`로 고정한다.

위 세 오류에는 `data`를 넣지 않는다. Engine response body, 원문 오류·exception text와
stack은 어떤 매핑에서도 agent에게 전달하지 않는다.
취소는 상위 task로 전파한 뒤 session cleanup을 수행하며 임의 오류 payload로 바꾸지 않는다.

## 12. 구조화 로그와 redaction

### 2026-09-09 현재 FastMCP 진단 로그 보완 (WU-M5)

사용자가 요청한 단일 WU-M5는 현재 실행 중인 FastMCP의 HTTP 요청과 Backend
콜백 진단을 기존 `main.py`, `integrations/engine_http.py` 안에 추가한다. 새 디렉터리,
DB 접근·schema, Resource·Tool 계약이나 fallback 판정은 추가하지 않는다. 이 현재
프로파일에서는 stderr 수집을 명시적으로 사용하며 기존 실행 스크립트가 출력 파일을
선택한다. 아래 과거 선행 구현의 기본 sink 폐기 설명보다 이 절을 우선한다.

API 9.4의 여섯 application field만 기록하고 UTC·PID는 표준 process metadata로
덧붙인다. HTTP 요청마다 새 UUID를 만들어 SDK가 전달한 해당 요청의 ASGI scope에서
복원하므로 장수 session task가 initialize의 추적 ID를 재사용하지 않는다. MCP HTTP
상태와 JSON-RPC 오류, Backend callback의 scope별 성공·HTTP 실패·연결/읽기/쓰기/풀
timeout·취소를 서로 구분한다. 요청·응답 body는 제한된 크기 안에서 operation과
오류 유무를 분류할 때만 사용하고 출력하거나 요청 종료 후 보관하지 않는다.
표준 SDK·HTTP·Uvicorn logger의 원문은 출력 전에 고정 분류로 교체한다. 진단 출력
실패는 게임 결과나 예외 전파를 변경하지 않는다. 검증은 합성 HTTP/ASGI 성공·오류·
취소·동시 요청 및 민감 marker 비노출을 포함하며, 재실행 후 팀 DB의 실제 테스트
게임과 로그의 시각·요청 수를 대조한다. 다른 MCP로 향하거나 이 MCP에 도달하지
않은 요청의 실제 endpoint·실행 위치는 이 서버 로그만으로 판정하지 않는다.

API 9.4절의 application allowlist만 사용한다. 적용 범위는 initialize, consume,
Resource, Tool, Engine adapter, teardown의 성공·거부·예외 전체다.

허용 대상:

- request·correlation ID
- operation 이름
- status
- duration
- 비밀 없는 폐쇄형 error class

두 log ID는 검증된 UUID만 사용하고 임의 header 문자열을 그대로 기록하지 않는다.

금지 대상:

- Resource·Tool request/response payload와 target
- game·agent·player ID 및 private context
- capability, 세션 개설 토큰, signature, secret과 HTTP header
- prompt, raw model response, exception 전문·stack, chain-of-thought
- DB·Redis·queue·파일 spool을 이용한 MCP 영속 audit outbox

테스트는 marker를 각 중첩 field와 exception에 주입하고 모든 log record를 캡처해 key
allowlist와 marker 부재를 검사한다. logger 실패 경로도 payload를 fallback file에 쓰지
않아야 한다. sink 제품과 보존 정책은 `OPEN-04`이며 wire 계약과 분리한다.

### 12.1 운영 sink 결정과 독립적인 선행 구현

`ports/audit.py`는 비밀 없는 record를 받는 동기 `AuditSink` 경계,
`core/audit.py`는 API 9.4의 여섯 필드만 생성하는 검증기와 기간 측정기를 제공한다.
`create_app(..., audit_sink=None)`의 기본값은 기록을 폐기하며 파일·표준 출력·DB·Redis·
queue를 자동으로 선택하지 않는다. 주입하는 sink는 블로킹하지 않는 신뢰된 호출자
구현이어야 한다. sink 예외는 재전송·spool 없이 폐기하고 게임 처리 결과를 바꾸지 않는다.

로그 ID는 MCP request/session/job ID나 인증 header에서 복사하지 않고 독립 UUID로
생성한다. 한 HTTP 요청과 그 내부 작업은 이 안전한 ID만 공유한다. operation·status·
error class는 내부 폐쇄형 분류이며 원문 exception을 인자로 받지 않는다. duration은
monotonic clock으로 측정하고 유한한 0 이상의 수만 허용한다.

선행 계측 대상은 이미 구현된 initialize·consume·Resource list/read·Engine context·
protocol 요청·session teardown이다. `tests/test_audit_logging.py`는 record와 sink 실패를,
`tests/test_audit_runtime.py`는 실제 SDK·ASGI/fake Engine 경로의 성공·거부·예외·취소와
민감 marker 비노출을 검증한다. WU-M4 Tool 계측, 운영 수집기·보존 정책, 실제 운영
전달 증거는 이 선행 범위에 포함하지 않으며 OPEN-04는 계속 미결정으로 유지한다.

SDK 장수 task에서 Resource handler를 실행할 때는 HTTP scope에 전달한 안전한
`AuditSpan`의 UUID context만 복원한다. initialize 시점의 추적 ID를 이후 요청에
재사용하지 않는다. context 조회의 성공은 HTTP 응답뿐 아니라 schema·직렬화 검증까지
포함한다. SDK·HTTP·Uvicorn 진단 원문은 표준 logging filter로 formatter 전에 폐기하며
중첩 runtime lifespan은 참조계수로 보호한다. 독립 entrypoint는 access log를 끄고
host의 시작·종료 오류 처리까지 filter를 유지한다. 이 경계는 운영 sink 선택이 아니다.

## 13. 설정·secret·network

| 프로세스 | 허용 설정 |
|---|---|
| Backend | `MAFIA_MCP_URL`, `MCP_REQUIRE_TLS`, `MCP_TLS_CA_FILE`, `MCP_SERVER_AUTH_SECRET`, `ENGINE_INTERNAL_API_SECRET` 등 Backend allowlist |
| MCP runtime | `MCP_SERVER_AUTH_SECRET`, `ENGINE_INTERNAL_API_SECRET`, `ENGINE_API_URL`, 비밀이 아닌 listen·TLS 설정 |
| migration | `DATABASE_MIGRATION_URL`, `DATABASE_NAME`, DB path 비교용 `TEAM_DATABASE_URL`/`DATABASE_URL` |

- MCP runtime에는 DB·Redis·LLM 자격증명을 주입하지 않는다.
- 실제 secret, DSN, token과 인증서 개인키를 문서·fixture·log·Git에 넣지 않는다.
- `${MAFIA_MCP_URL}`은 `/mcp`를 포함한 전체 endpoint이며 client가 경로를 중복하지
  않는다.
- Backend→MCP 운영 연결은 검증된 TLS를 사용한다. 평문 HTTP는 loopback 개발에서만
  허용하고 downgrade나 검증 실패 시 fail-open하지 않는다.
- MCP→Engine TLS 종료, CA/mTLS 여부와 MCP listen 인증서 환경변수명은 `OPEN-05`다.
- MCP 자체 liveness/readiness endpoint와 readiness 기준은 `OPEN-06`이다. 정본 변경 전
  임의 공개 endpoint를 추가하지 않는다.

## 14. 테스트 전략

### 14.1 독립 개발 원칙

WU-M2~WU-M5의 자동 테스트는 실제 Backend, PostgreSQL, Redis와 유료 LLM 없이 synthetic
fixture와 fake Engine port를 사용한다. fixture는 API 정본에서 만들고 정본 밖 field,
enum과 상태 전이를 계약으로 추가하지 않는다.

WU-M3 fake Engine 증거는 consume binding 저장, list descriptor·순서·Engine 0회,
허용 read당 GET 1회, 거부 read Engine 0회, 단일 응답 폐쇄형 검증, 요청 종료 뒤
Resource context 무저장과 서로 다른 MCP session·audience 간 private payload의
비재사용·비간섭을 독립적으로 입증한다. session pool의 공개 candidate·active·running
count와 manager `run()` exit 사건으로 terminal 뒤 tombstone 폐기도 검증하되 SDK private
state를 관측하지 않는다. 한 teardown을 멈춘 상태에서도 다른 만료 session의 route 제거와
teardown 시작이 독립적으로 진행되고 shutdown cancellation이 지연된 session 하나에
직렬화되지 않음을 검증한다. 이 fake 증거는 Backend가
authoritative state와 projection provenance·cross-scope 의미 불변식을 올바르게
판정했음을 입증하지 않는다. 그 권위 검증은 WU-B7, 실제
Backend↔MCP 호출 횟수·binding·비간섭성 end-to-end 증거는 WU-M6이 소유한다.

fake Engine은 다음 결과를 script할 수 있어야 한다.

- 세션 개설 토큰 consume 성공·거부·지연·응답 유실
- scope별 정상 context와 unknown/private field가 섞인 잘못된 context
- proposal accepted, 동일 replay, body conflict, capability deny와 dependency failure
- timeout, cancellation과 connection loss
- 호출 path·header 존재·body hash를 검증할 수 있는 비밀 없는 호출 기록

### 14.2 필수 검증 matrix

| 축 | 최소 검증 |
|---|---|
| 세션 개설 토큰 | canonical signature, claim, expiry, nonce replay, capability hash mismatch |
| lifecycle | job마다 다른 capability·nonce·session, 모든 terminal revoke, fresh reconnect |
| subject | 2×5 Resource 허용표, 다른 subject 선택 거부 |
| Resource | consume 5-field binding, list cursor 거부·descriptor·order·Engine 0회, SDK capability 광고, raw exact URI, 5개 exact schema, read 1/0 call, unknown field fail-closed·요청 종료 뒤 context 무저장 |
| noninterference | 서로 다른 MCP session·audience 간 private payload 비재사용, 다른 AI role·사실·event·persona와 GM private field·target 비노출 |
| Tool | closed input, 현재 allowlist, target, stale version, Backend 재검증 |
| idempotency | 같은 proposal ID/body terminal replay, 다른 body conflict, 새 HMAC nonce |
| GM | `public`·`gm-guide`의 nonempty 부분집합·Tool 0개, direct-return, guide mismatch, late fencing fallback |
| 장애 | Engine 4xx·5xx·timeout, MCP restart, session loss, 취소 전파 |
| 로그 | 전 경로 key allowlist, payload·ID·secret·exception marker 부재 |
| 경계 | MCP process에 DB·Redis client·credential 없음, Engine 세 path만 호출 |

SDK-level Streamable HTTP test, fake Engine 계약 test와 실제 Backend 통합 test를
분리한다. 실제 Provider smoke는 이 설계의 필수 게이트가 아니다.

## 15. WU 실행 계획

### 15.1 의존 순서

```text
CP-0 -> WU-M1A -> WU-B2 -> WU-M1B -> CP-2

CP-0 -> WU-M2 -> WU-M3 -> WU-M4 -> WU-M5 --\
                                             +-> WU-M6 -> WU-M7 -> WU-M8 -> CP-6
WU-B6 + WU-B7 -------------------------------/      |
                                                    CP-4
```

각 WU는 별도 구현 세션과 별도 검증 기록을 사용한다. 선행 WU가 없으면 fake 경계로
독립 개발할 수 있는 범위만 수행하고 실제 통합 완료로 표시하지 않는다.

### 15.2 WU별 경계

| WU | 선행조건 | 산출물 | 검증 | 명시적 비산출물 |
|---|---|---|---|---|
| `WU-M1A` | DB 정본·환경 합의 | PostgreSQL·Redis 인스턴스, DDL/DML 계정, health 증거 | 계정별 연결·권한 allow/deny, Redis health | migration SQL·repository·Redis app 코드 변경 |
| `WU-M1B` | WU-M1A, WU-B2 migration | 이름순 실행·재실행 기록, schema version 증거 | 빈 DB·기존 DB upgrade, 재실행, runtime DDL·event 수정 거부 | 적용 migration 수정, 임의 DDL, 실제 DSN 기록 |
| `WU-M2` | CP-0, secret 분리, fake Engine | Streamable HTTP server, initialize·세션 개설 토큰 consume | 정상 initialize, 누락·변조·만료·replay·mismatch 거부 | Resource·Tool, DB·Redis, 게임 판정 |
| `WU-M3` | WU-M2, API 8.2·8.3·9.2 | consume binding의 job/subject session, 세션별 `Server`·stateful manager lifecycle pool, list·다섯 Resource adapter | binding 폐쇄형, 2×5 허용표, descriptor order, read 1/0 call, exact schema·요청 종료 뒤 무저장·session/audience·teardown 비간섭 fake 증거 | Backend 현재 상태·projection 권위 입증, 별도 문서 schema 재정의, Front snapshot 재사용, Tool |
| `WU-M4` | WU-M3, API 8.4·9.3 | 네 Tool, proposal 조립과 Engine adapter | 입력·phase·target·stale·idempotency·응답 유실 | 규칙 판정, DB mutation, GM Tool |
| `WU-M5` | WU-M2~WU-M4 operation/error 경로 | 중앙 allowlist log와 redaction | 성공·거부·예외 marker 캡처, 허용 key 검사 | DB·queue·spool·audit outbox, event_outbox 소비 |
| `WU-M6` | WU-B6·WU-B7, WU-M2~WU-M5, 통합 network | 실제 Backend↔MCP job 왕복 증거 | initialize→consume→Resource→Tool, GM read-only·direct-return, Backend 최종 판정 | 공개 API·DB schema 변경, 유료 Provider 강제 |
| `WU-M7` | WU-M6 정상 경로 | fault/reconnect 결과 | stale·expired·revoked, Engine 장애, restart, fresh reconnect, redaction | 기존 자격 재사용, authoritative cache, MCP fallback 판정 |
| `WU-M8` | WU-M1A·WU-M1B·WU-M2~WU-M7 | 기동·중지·migration·health·TLS·rotation runbook과 release evidence | 제3자 clean 재현, positive·negative·권한·장애 확인 | 실제 secret·DSN 기록, Backend migration 수정 |

### 15.3 WU별 완료 증거

모든 WU 완료 보고는 다음 중 해당 항목을 비밀 없이 남긴다.

- 변경 파일과 각 변경의 정본 근거
- 실행 명령, exit 결과와 focused·회귀 검증 범위
- positive, reject, fault와 noninterference matrix 결과
- fake·실제 dependency 구분과 외부 API 과금 여부
- redaction 캡처와 forbidden marker 검사 결과
- 실제 session roundtrip의 ID·payload·secret 제거 trace
- 인프라 계정 권한과 health 결과
- 생략한 테스트와 위험도 기반 사유

WU-M2~WU-M5는 fake Engine 독립 증거를 완료 근거로 삼는다. 특히
WU-M3는 MCP에서 관측 가능한 schema·binding·호출 횟수·무저장만 입증하고,
Backend의 revoke·현재 상태·projection provenance·cross-scope 최종 판정은
WU-B7 증거로 분리한다. WU-M6은 실제 Backend 계약과 end-to-end binding·
호출 횟수·비간섭성, WU-M7은 장애 주입, WU-M8은 제3자 runbook 재현을 각각
완료 근거로 삼는다.

### 15.4 협의 제외 선행 작업 결과 — 2026-09-05

사용자의 독립 작업 일괄 요청에 따라 기존 M3 보완과 M5의 sink와 독립적인 부분을
구분해 구현·검증했다. 이 요청은 다른 섹터 소유 코드나 미정 계약을 변경하는 승인으로
해석하지 않았으며, WU별 전체 완료와 선행 작업 완료를 구별한다.

| 항목 | 현재 결과 | 남은 경계 |
|---|---|---|
| M3 | UTF-8 불가능 문자열 거부, 소수초 정밀도 손실 없는 deadline 비교, 전체 package 검증 통과 | Backend 권위·실제 통합 증거는 B7/M6 |
| M5 선행 | 안전 record·주입 sink·기존 경로 계측·SDK 원문 차단 및 실패·취소 검증 | Tool 계측, OPEN-04 운영 sink·보존 결정 |
| M8 준비 | package README에 확정된 로컬 실행·종료·설정 분리 절차 반영 | TLS/readiness/rotation 정책, 실제 통합·제3자 재현 |

MCP 전체 255개 테스트, Ruff, `uv lock --check --offline`을 통과했다. M3 schema focused
63개와 M5 record/runtime focused 41개는 전체 수에 포함된다. Backend/Front 검증은
루트 README의 같은 날짜 결과를 참조하며 이 수에 합산하지 않는다.

다음은 협의·타 섹터 산출물이 필요해 이번 구현에서 제외했다.

- M4: Tool 현재 허용표의 조회 시점·호출 횟수·`turn` 미허용 session 처리, proposal
  nullable/필수값과 public rationale 경계, proposal POST 오류 매핑의 구체화.
- M1A: 기존 인스턴스·대상 환경·계정·데이터 보존 범위 확인 전 새 인프라를 생성하거나
  기존 서비스를 중지하지 않았다. 실제 구축 여부를 이번 검증으로 판정하지 않는다.
- M1B: Backend `004_seed_scenarios_and_personas.sql`의 시나리오 검증은 비정상 행을
  세면서 `5-count(*)`를 계산하므로 정상 5개가 있어도 예외가 발생하는 구조다.
  이는 SQL 정적 판독 결과이며 실제 DB 실행으로 재현하지 않았다. SQL 수정·실행 생략을
  MCP가 대신 결정하지 않으며 Backend 수정 산출물 후 실행·재실행한다.
- M6: Backend의 5-field consume, context/proposal handler와 실제 Agent MCP client 연결.
- M7/M8: OPEN-04~07의 운영 sink·TLS·health·consume 응답 유실 조정 결정 및 실제
  Backend 장애·재접속 왕복. fake 검증을 해당 WU 전체 통과로 표시하지 않는다.

## 16. 구현 결정 등록부

아래 항목은 확정 정본 밖 구현 세부다. 해당 WU 전에 owner가 결정하고 wire·환경 변수·
파일 구조에 영향이 있으면 정본과 README를 먼저 갱신한다.

| ID | 상태 | 결정 항목 | owner | 적용 WU |
|---|---|---|---|---|
| `OPEN-01` | RESOLVED | `mcp_server` 독립 project, `mafia_game.main` composition root와 package-local lock/test | MCP | WU-M2 |
| `OPEN-02` | RESOLVED | 세션별 fresh `Server`와 stateful manager, 공개 lifecycle pool, initialize 전 consume, route-first DELETE·terminal cleanup, manager `run()` 종료, 독립 30초 reaper | MCP·Backend | WU-M2, WU-M3, WU-M7 |
| `OPEN-03` | RESOLVED | 11절과 API 9.3.1절의 고정 HTTP·JSON-RPC 오류 매핑 | 공통 | WU-M2~WU-M4 |
| `OPEN-08` | RESOLVED | MCP context cache 없음; list Engine 0회, 허용 read GET 1회, 거부 read Engine 0회, 요청 종료 뒤 Resource JSON·model·text retained reference·재사용과 stale fallback 금지 | 공통 | WU-M3, WU-M7 |

남은 OPEN 항목은 다음과 같다.

| ID | 결정 항목 | owner | 차단 WU | 결정 전 금지 |
|---|---|---|---|---|
| `OPEN-04` | 구조화 log sink와 운영 보존 기간 | 운영·MCP | WU-M5, WU-M8 | payload spool·영속 outbox |
| `OPEN-05` | MCP→Engine TLS 종료·CA·mTLS와 설정 이름 | 운영·공통 | WU-M6, WU-M8 | TLS 검증 우회 |
| `OPEN-06` | MCP liveness/readiness endpoint와 판정 기준 | MCP·운영 | WU-M8 | 임의 공개 health API 추가 |
| `OPEN-07` | 세션 개설 토큰 consume 응답 유실의 Backend 조정 절차 | Backend·MCP | WU-M7 | 소비 token 재사용 |

남은 `OPEN`은 확정 계약을 약화하지 않는다. 결정 전 기본값은 fail-closed,
no persistent spool과 fresh credential이다. Resource context no-cache는 이제 기본값이
아니라 `OPEN-08` 확정 계약이다.

## 17. 구현 착수·완료 체크리스트

### 착수

- [ ] 이번 세션의 WU가 하나 이하인가
- [ ] `AGENTS.MD`와 해당 정본·이 설계서를 읽었는가
- [ ] 선행 WU와 필요한 OPEN 결정이 닫혔는가
- [ ] 현재 branch와 사용자 소유 변경을 확인했는가
- [ ] 실제 secret·유료 API 없이 검증할 fake 경계를 준비했는가

### 완료

- [ ] MCP runtime이 DB·Redis·`event_outbox`에 접근하지 않는가
- [ ] Resource validator가 API 8.2절과 일치하고 별도 문서 정본을 만들지 않았는가
- [ ] consume binding, list descriptor·순서, read 1/0 호출과 요청 종료 뒤 context 무저장을 fake
  Engine으로 증명했으며 Backend 권위 증거로 오인하지 않았는가
- [ ] AI_PLAYER/GM allowlist와 GM Tool 0개를 negative test로 증명했는가
- [ ] job terminal·reconnect에서 capability와 session memory가 폐기되는가
- [ ] proposal retry가 같은 ID·body이고 stale rebase가 없는가
- [ ] 로그가 API 9.4 allowlist만 가지는가
- [ ] 위험도에 맞는 검증 결과와 생략 사유를 기록했는가
- [ ] 루트 README와 package README가 실제 구현 상태·명령과 일치하는가
- [ ] 사용자 승인 없이 commit·push하지 않았는가

이번 단일 WU-M3 보완은 사용자가 요청한 운영 FastMCP 모델 입력 축약·게임 규칙 안내 추가다. 기존 Resource 등록 파일에서만 변환하며 상세 계약은 API 명세의 FastMCP 모델 입력 축약 절을 따른다. Backend MCP 소비 클라이언트는 기존·축약 응답을 함께 허용하는 최소 호환 변경을 포함한다. DB·게임 판정은 변경하지 않는다.

## 2026-09-08 역할별 프롬프트 이관 (WU-M6)

후속 사용자 요청으로 `instructions.py`의 토론 지침은 일률적 추궁보다 상대 답변에
대한 반응·신뢰 조정·조건부 협력과 역할별 블러핑을 안내한다. 마피아는 사실과 필요한
왜곡을 섞어 표를 모으고 시민 진영은 오처형 위험에 따라 미끼 주장을 거둔다. 게임 대사의
전략일 뿐 실제 Resource 기록·Tool 인자·본인 역할·정보 scope는 바꾸지 않는다.
페르소나 원문을 보간하거나 수치를 재매핑하지 않고, 모델 입력에서 제외한 알리바이·
관찰을 첫 발언에 요구하지 않는다. 첫날 SPEAK 의무와 Prompt 등록명·서명·2400자 한도는
유지한다. 기존 등록·소비 테스트와 비DB 회귀로 전달 계약을 검증하며 실제 모델의
자연스러움·승률·반복률은 별도 평가 대상으로 남긴다.

사용자 승인에 따라 `api/prompts/instructions.py`가 네 역할의 승리 전략·단계별 행동·페르소나
적용 경계를 소유한다. 성향 수치의 구간별 문구 변환과 deception 증폭은 제거하고,
기존 Backend 응답의 말투·배경·수치를 보존한다. 운영 Resource 등록부에서 동일 renderer를 사용하여 추가 HTTP 호출
없이 본인 역할 지침과 말투 지침을 전달한다. 상세 응답 변경은 API 명세의 같은 날짜
계약을 따른다. 공통 system·출력 검증·Provider 호출은 Backend가 유지하고, MCP Prompt는
더 이상 Backend prompt endpoint에서 본문을 가져오지 않는다.

같은 WU의 패키지 구조 보완으로 `api/prompts/instructions.py`에 지침 생성 코드를,
`api/prompts/registry.py`에 Prompt 등록을 둔다. Resource·Tool 등록도 각각
`api/resources/registry.py`, `api/tools/registry.py`로 분리한다. 세 API 패키지의
`__init__.py`에는 설명 docstring만 남기고 composition root와 소비자는 구현 모듈을
직접 import한다. 등록명·URI·인자·프롬프트 내용은 유지한다.

## 2026-09-07 자유 토론 변경 (사용자 승인 WU-B4)

2026-09-08 사용자 확인으로 같은 규칙 경계에 첫날 인간·AI PASS 금지를 적용한다.
MCP 역할 지침·공개 규칙은 첫날 반드시 SPEAK하도록 안내하고, 허용 Tool 검증은
API 명세 8.2.3의 첫날 배열을 수용한다. Backend가 최종 규칙과 실패 시 기본 발언을
소유하며 MCP가 대체 발언을 생성하거나 DB에 접근하지 않는다.

이번 단일 WU-B4는 1분 45초 자유 토론과 연결되는 Front·MCP 표현의 변경이다. 이 절이 기존 좌석당 한 번 발언·전원 PASS 추가 순환 규칙보다 우선한다. 새 일반·최종 토론은 Backend deadline 105초까지 열리며 인간은 AI 처리 순서와 무관하게 발언한다. 플레이어별 최근 60초 SPEAK는 최대 7회이며 서버 게임 행 잠금 안에서 원장으로 검증한다. PASS는 조기 마감하지 않는다. AI 작업은 기존 단일 예약 창을 재사용해 공정하게 배분하고, 발언마다 새 window를 열되 토론 deadline은 보존한다. turn_player_id는 AI 스케줄링 힌트이며 인간의 발언 권한 제한이 아니다. SPEECH에도 deadline·remaining_ms가 제공된다. 저장 시 잔여 시간을 보존한다. 마감 뒤 첫날은 밤, 이후 낮은 투표, 최종 토론은 최종 지목으로 진행한다. 과거 deadline 없는 발언 창은 기존 방식으로 처리한다. DB 구조와 idempotency·게임 상태 버전 검증은 보존한다.

## 2026-09-08 CUSTOM_ROLE MCP 경계 (CP-0, WU-M10 예약)

`custom-role-v1`은 HUMAN-only이므로 MCP runtime은 자유 직업명을 prompt로 소비하지 않고
custom AI를 생성하지 않는다. 신규 MCP Tool을 등록하거나 PostgreSQL·Redis에 직접
접근하지 않으며, 게임 규칙·allowlist·진영·밤 해소의 권위는 계속 Backend에 있다.
custom AI 지원은 별도 후속 WU에서 계약부터 다시 승인한다.

Backend의 catalog descriptor는 다음 세 ID가 모두 기존 logical MCP Tool
`propose_night_action`을 참조한다고 정본화한다.

| catalog version | ability ID | logical Tool 참조 |
|---|---|---|
| `custom-role-v1` | `night.attack.v1` | `propose_night_action` |
| `custom-role-v1` | `night.investigate.v1` | `propose_night_action` |
| `custom-role-v1` | `night.protect.v1` | `propose_night_action` |

이 매핑은 공개 사용자가 raw MCP Tool명, action subtype 또는 prompt를 입력한다는 뜻이
아니다. 공개 API는 오직 versioned `ability_id`만 받고 Backend가 저장된 HUMAN 능력과
대조한 뒤 내부 logical action으로 변환한다. MCP에는 검증되지 않은 직업명을 system
instruction으로 전달하지 않는다. WU-M10은 runtime mutation 없이 descriptor 참조,
STANDARD 기존 호출, HUMAN-only custom 요청이 MCP 호출을 새로 만들지 않는다는 호환
증거만 소유한다.

## 2026-09-09 저장소 구조 정리

사용자 요청에 따라 구현이 없던 `mcp_2`, `integrations/database`,
`integrations/redis`, `integrations/embedding` 예약 디렉터리와 현재 composition root에서
사용하지 않으면서 누락된 security/session 모듈을 참조하던 과거 Resource 계층을
삭제했다. Backend의 미사용 MCP adapter·registry·tool router 예약 모듈도 제거했다.

현재 MCP runtime의 실제 구조는 `api/prompts`, `api/resources`, `api/tools`,
`integrations/engine_http.py`, `schemas/common.py`, `main.py`다. 신규 기능은 이 구조 안에
추가하며 예약 디렉터리를 미리 만들지 않는다. 저장소의 Backend·Front·MCP 테스트 소스와
pytest 경로 설정도 같은 요청으로 삭제했다. 이전 절의 `mcp_2` 유지, 비어 있는 계층 유지,
`mcp_server/tests` 소유 규칙은 현재 checkout 구조에 더 이상 적용하지 않는다.
과거 검증 수치는 실행 이력으로만 보존하며 자동 회귀를 다시 운영하려면 테스트 소스와
설정을 별도 작업 단위에서 복원해야 한다.

### 2026-09-08 WU-M10 사용자 전용 Tool 확장

이번 신규 Tool 요청은 위 M10 runtime 변경 금지를 두 능력에 한해 대체한다.
기존 `api/tools/registry.py`에 `manipulate_vote`, `inspect_special_roles`를 등록하고
`integrations/engine_http.py`에서 Backend 내부 API로만 위임한다. 실제 wire 이름은
기존 `submit_action`과 두 새 Tool이며 logical `propose_night_action`은 기존 계약 참조다.

| catalog version | ability ID | Tool 참조 |
|---|---|---|
| `custom-role-v1` | `vote.triple.v1` | `manipulate_vote` |
| `custom-role-v1` | `intel.special_roles.v1` | `inspect_special_roles` |

MCP는 actor·직업·가중치·첫 밤 완료를 인수로 신뢰하거나 자체 판정하지 않는다.
user_id·game_id와 필요한 투표 낙관 잠금 인수만 받고 Backend가 소유 HUMAN을 결정한다.
조회 Tool의 입력은 UUID로 제한하고 출력은 API 명세의 전용 최소 schema로 검증한다.
Backend 오류 본문·비공개 응답을 로그·예외 원문에 복사하지 않는다. 기존 AI용
Resource·Prompt·submit_action 및 AI Tool allowlist에는 새 권한을 부여하지 않는다.
이전 최소 runtime의 UUID 소유권/loopback 신뢰 경계를 유지하므로 공개 인터넷에 직접
노출하는 사용자 인증 서버로 해석하지 않는다. Front는 후속 공개 API 연결을 통해 사용한다.


### 2026-09-08 CP-0.1 사용자 Front 연결 경계

사용자 Front는 `manipulate_vote`·`inspect_special_roles` 등 raw MCP Tool을 직접 호출하지
않는다. 투표는 공개 `SUBMIT_VOTE`에 선택한 `ability_id=vote.triple.v1`을 전달하고,
특수 직업 조회는 인증된 사용자 흐름의 공개 `GET /api/v1/games/{game_id}/special-roles`에
`X-User-Id`를 전달한다. WU-B17 공개 adapter는 Backend의 기존 `read_special_roles`를
직접 재사용하며 `/internal/mcp/special-roles`는 `inspect_special_roles` 전용으로 유지한다.
두 Tool 등록·내부 HTTP 위임·AI allowlist 비간섭 계약은 변경하지 않는다.
공개 success envelope·no-store·404/403/409와 최소 projection은
[API 명세](../01_core/AI_MAFIA_API_SPEC.md)의 CP-0.1 절만 참조하며 Resource schema를 복제하지 않는다.
