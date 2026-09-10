# AI 마피아 Backend 개발 계획서

## 1. 문서 목적과 기준

이 문서는 AI 마피아 MVP Backend의 개발 순서와 구현 기준을 정리한 실행 계획서다.
구현자는 아래 5개 정본을 함께 확인하고, DB 계약은 AI_MAFIA_DB_DESIGN.md를 최우선으로
따른다.

- AI_MAFIA_MASTER_PLAN.md: 제품 규칙, 게임 흐름, 소유권, WU와 CP
- AI_MAFIA_DB_DESIGN.md: PostgreSQL·Redis, 테이블, Transaction, Migration
- AI_MAFIA_API_SPEC.md: 공개·관리자·내부 API와 MCP 계약
- AI_MAFIA_SCREEN_FLOW.md: snapshot·sync·저장·재개·화면 상태 흐름
- AI_MAFIA_INDEPENDENT_CONTRACT.md: 섹터 간 공통 형식과 담당 경계

이 문서와 DB 정본이 다르면 DB 정본을 우선한다. 변경이 필요하면 정본 합의 후
순방향 Migration으로 처리한다. 이 문서는 Backend 계획서만 추가하며 기존 정본은
수정하지 않는다.

### Backend가 담당하는 범위

- PostgreSQL schema·Migration·Repository
- Redis application code
- 공개 사용자 API와 관리자 read-only API
- 내부 Engine API와 Agent Manager
- authoritative 게임 상태와 규칙 엔진
- 역할·생존·승패·RNG 결과 확정
- snapshot·event·sync·SSE
- 저장·재개·fast-forward

### Backend가 담당하지 않는 범위

- Front 화면 렌더링과 화면 상태 계산
- PostgreSQL·Redis 프로세스 운영과 계정 준비
- MCP Server runtime의 DB·Redis 직접 접근
- MCP의 게임 판정

한 coding AI 세션은 AI_MAFIA_MASTER_PLAN.md의 Backend WU 한 개 이하로 제한한다.

## 2. 현재 코드 뼈대 적용

기존 Scaffold 구조를 먼저 확장한다. 파일 이동·삭제·이름 변경은 하지 않고, 기능
분리가 꼭 필요할 때만 새 파일을 최소 범위로 추가한다.

| 현재 위치 | 계획상 역할 |
|---|---|
| backend/app/main.py | FastAPI 앱, router, 공통 예외 처리 등록 |
| backend/app/core/config.py | 정본 환경변수와 보안 설정 검증 |
| backend/app/core/responses.py | 성공·실패 envelope 통일 |
| backend/app/core/errors.py | 정본 오류 코드와 HTTP status 변환 |
| backend/app/routers/scaffold_game_router.py | 공개 게임 API로 확장 |
| backend/app/routers/scaffold_mcp_router.py | 내부 MCP 관련 API로 전환 |
| backend/app/services/ | 사용자, 게임, command, sync, Agent, 관리자 서비스 |
| backend/app/repositories/ | PostgreSQL 테이블별 조회·저장 |
| backend/app/infrastructure/postgres.py | PostgreSQL 연결과 Transaction |
| backend/app/infrastructure/redis/ | lock·cache·stream·nonce cache |
| backend/app/agent/ | 규칙 엔진, Agent Manager, fallback |
| backend/app/mcp/ | MCP Streamable HTTP client |
| backend/app/llm_provider/ | 설정된 단일 Provider adapter |
| backend/migrations/ | 정본 schema를 위한 순방향 SQL |

기존 Scaffold 전용 응답과 scaffold-v1 계약은 canonical MVP API로 전환한 뒤 사용하지
않는다. 기존 001, 002 Migration 파일은 수정하지 않는다.
+
### 2.1 한 명의 개발자가 사용할 최종 Backend 구조

기존 파일은 유지하고 canonical 기능은 책임별 파일로 분리한다. 기존 scaffold 파일은
B1~B5 전환이 끝날 때까지 호환용으로 남길 수 있지만, 새 기능을 scaffold 전용
schema나 repository에 추가하지 않는다.

~~~text
backend/
├─ app/
│  ├─ main.py
│  ├─ core/
│  │  ├─ config.py
│  │  ├─ errors.py
│  │  ├─ responses.py
│  │  └─ logging.py
│  ├─ routers/
│  │  ├─ health_router.py
│  │  ├─ identity_router.py
│  │  ├─ scaffold_game_router.py
│  │  └─ scaffold_mcp_router.py
│  ├─ schemas/
│  │  ├─ common_schema.py
│  │  ├─ user_schema.py
│  │  ├─ game_schema.py
│  │  ├─ command_schema.py
│  │  ├─ sync_schema.py
│  │  ├─ internal_schema.py
│  │  ├─ feedback_schema.py
│  │  └─ admin_schema.py
│  ├─ models/
│  │  ├─ identity.py
│  │  ├─ scaffold_game.py
│  │  ├─ game_state.py
│  │  └─ enums.py
│  ├─ repositories/
│  │  ├─ user_repository.py
│  │  ├─ scenario_repository.py
│  │  ├─ game_repository.py
│  │  ├─ player_repository.py
│  │  ├─ action_repository.py
│  │  ├─ event_repository.py
│  │  ├─ receipt_repository.py
│  │  ├─ snapshot_repository.py
│  │  ├─ agent_repository.py
│  │  ├─ nonce_repository.py
│  │  ├─ outbox_repository.py
│  │  ├─ feedback_repository.py
│  │  └─ admin_repository.py
│  ├─ services/
│  │  ├─ identity_service.py
│  │  ├─ scaffold_game_service.py
│  │  ├─ command_service.py
│  │  ├─ window_service.py
│  │  ├─ sync_service.py
│  │  ├─ feedback_service.py
│  │  └─ admin_service.py
│  ├─ agent/
│  │  ├─ orchestrator.py
│  │  ├─ game_engine.py
│  │  ├─ state_machine.py
│  │  ├─ projections.py
│  │  └─ fallback.py
│  ├─ game_engine/
│  │  ├─ engine.py
│  │  ├─ phases/
│  │  ├─ rules/
│  │  ├─ rng.py
│  │  └─ fallback.py
│  ├─ infrastructure/
│  │  ├─ postgres.py
│  │  ├─ migrations.py
│  │  ├─ transaction.py
│  │  ├─ security/internal_request.py
│  │  ├─ security/game_crypto.py
│  │  └─ redis/
│  │     ├─ lock.py
│  │     ├─ cache.py
│  │     ├─ streams.py
│  │     └─ nonce.py
│  ├─ mcp/
│  │  ├─ client.py
│  │  ├─ game_client.py
│  │  └─ registry.py
│  └─ llm_provider/
│     ├─ base.py
│     ├─ factory.py
│     ├─ dummy.py
│     └─ configured_provider.py
├─ migrations/
│  ├─ 001_create_oauth_schema.sql
│  ├─ 002_create_scaffold_game_schema.sql
│  ├─ 003_create_mystery_v1_schema.sql
│  └─ 004_seed_scenarios_and_personas.sql
└─ tests/
   ├─ test_identity_api.py
   ├─ test_migrations.py
   ├─ test_repositories.py
   ├─ test_transactions.py
   ├─ test_redis.py
   ├─ test_game_engine.py
   ├─ test_game_api.py
   ├─ test_sync.py
   ├─ test_agent_manager.py
   ├─ test_internal_api.py
   ├─ test_admin_api.py
   └─ test_end_to_end_game.py
~~~

이미 존재하는 파일은 수정·확장하고 새 파일은 해당 WU에서만 추가한다. 파일 이동,
삭제, 이름 변경과 game2·v2·scaffold2 디렉터리 추가는 하지 않는다.

### 2.2 파일 간 호출 규칙

외부 요청은 다음 방향으로만 흐른다.

~~~text
router
→ schema 검증
→ service
→ repository / engine
→ transaction
→ PostgreSQL
→ event_outbox
→ Redis publisher 또는 sync 조회
~~~

- router: HTTP 입력과 response envelope만 담당
- schema: 요청 field, enum, 길이와 정규화 검증
- service: owner, state_version, window, Transaction 조정
- repository: SQL과 row mapping만 담당
- engine: 현재 상태를 받아 규칙 결과만 반환
- projection: public·human·AI·GM별 허용 정보만 생성
- orchestrator: Agent reservation과 외부 호출 전후 상태 관리
- publisher: commit된 event_outbox만 Redis로 전달

engine은 FastAPI·PostgreSQL·Redis·LLM을 직접 호출하지 않는다. router에서 SQL을
실행하거나 engine에서 외부 서비스를 호출하지 않는다.

### 2.3 WU별 파일 작업 목록

| WU | 주요 수정·추가 파일 | 구현 결과 |
|---|---|---|
| B1 | core/config.py, identity_router.py, identity_service.py, user_repository.py, main.py | UUID-only 사용자 context와 ownership |
| B2 | migrations/003_create_mystery_v1_schema.sql, migrations/004_seed_scenarios_and_personas.sql, infrastructure/migrations.py | 19개 table·constraint·seed |
| B3 | infrastructure/postgres.py, infrastructure/transaction.py, infrastructure/redis/*, repositories/* | row lock·receipt·outbox·Redis |
| B4 | models/game_state.py, models/enums.py, game_engine/engine.py, game_engine/phases/, game_engine/rules/, game_engine/rng.py, game_engine/fallback.py | 순수 규칙 엔진·결정적 RNG |
| B6 | agent/orchestrator.py, projections.py, mcp/client.py, llm_provider/*, agent_repository.py | Agent job·capability·proposal·fallback |
| B7 | scaffold_mcp_router.py, security/internal_request.py, sync_service.py, event_repository.py, outbox_repository.py | HMAC·nonce·Engine API·SSE |
| B5 | scaffold_game_router.py, scaffold_game_service.py, command_service.py, window_service.py, sync_service.py, schemas/* | 공개 game·command·sync·feedback |
| B8 | routers/admin_router.py, schemas/admin_schema.py, admin_service.py, admin_repository.py | read-only 관리자와 audit |
| B9 | tests/test_end_to_end_game.py, tests/simulations/, tests/fixtures/ | 전체 회귀·시뮬레이션·장애 검증 |

admin_router.py가 없으면 B8에서 새로 추가한다. 기존 scaffold router를 유지하더라도
path·request·response는 API 정본을 사용한다.

### 2.4 Migration 실행 순서

| 파일 | 내용 | 실행 |
|---|---|---|
| 001_create_oauth_schema.sql | 기존 legacy schema | 수정하지 않음 |
| 002_create_scaffold_game_schema.sql | 기존 scaffold schema | 수정하지 않음 |
| 003_create_mystery_v1_schema.sql | 19개 table, FK, CHECK, unique, partial index | 기존 canonical migration, Backend 검증 |
| 004_seed_scenarios_and_personas.sql | 5 scenario, 90개 이상 template, persona | Backend 작성, MCP 실행 |

003은 schema를 만들고 004는 안정 key 기준으로 재실행 가능하게 만든다. legacy
identity cleanup은 실제 데이터와 FK 의존성을 확인하고 승인한 별도 순방향 Migration으로
진행한다.

### 2.5 한 개발자의 작업 순서

~~~text
1. B1: 사용자 UUID·ownership·공통 오류
2. B2: canonical schema·seed를 빈 DB에서 검증
3. B3: repository·Transaction·Redis lock
4. B4: 외부 서비스 없는 게임 전체 replay
5. B6: fake MCP·dummy Provider Agent 연결
6. B7: 내부 API·outbox·SSE
7. B5: Front 공개 API
8. B8: 관리자 read-only
9. B9: 전체 회귀·장애·시뮬레이션
~~~

각 WU의 테스트를 통과한 뒤 다음 WU로 이동한다. B4 전에는 LLM이 규칙을 결정하지
않고, B7 전에는 MCP runtime을 실제 통합하지 않는다.


## 3. DB 정본

### 3.1 공통 규칙

- PostgreSQL이 사용자, 게임 상태, 역할, 행동, event와 결과의 영구 원본이다.
- Redis는 game lock, 공개 projection cache와 event fan-out만 담당한다.
- Backend 외 섹터는 PostgreSQL·Redis에 직접 접근하지 않는다.
- client-visible 변경은 한 PostgreSQL Transaction에서 상태, state_version, event,
  receipt와 outbox를 함께 확정한다.
- AI reservation처럼 Front projection을 바꾸지 않는 내부 기록은 state_version을 올리지 않는다.
- 외부 LLM·MCP 호출 중 DB Transaction과 Redis game lock을 유지하지 않는다.
- 모든 시각은 UTC timestamptz다.
- 문자열 enum은 대문자 고정값과 CHECK로 제한한다.
- 게임별 내부 event sequence는 1부터 증가한다.
- Front-visible batch는 front_sequence 하나와 0부터 연속인 operation_index를 사용한다.

### 3.2 정확한 테이블과 컬럼

아래 19개 테이블은 AI_MAFIA_DB_DESIGN.md의 logical schema를 그대로 구현한다.
타입·NULL 조건·FK·UNIQUE·index를 임의로 바꾸지 않는다.

#### users

~~~text
id uuid PRIMARY KEY                         -- DB default 없음, API UUID v4
created_at timestamptz NOT NULL
last_seen_at timestamptz NOT NULL
~~~

email, profile, avatar, OAuth subject, password와 사용자 role은 저장하지 않는다.
최초 쓰기에서 INSERT ... ON CONFLICT (id) DO UPDATE로 last_seen_at만 갱신한다.
조회 요청의 알 수 없는 UUID는 자동 생성하지 않는다.

#### scenario_catalog

~~~text
id varchar(64) PRIMARY KEY
version varchar(32) NOT NULL
title varchar(120) NOT NULL
background text NOT NULL
victim varchar(120) NOT NULL
locations jsonb NOT NULL                  -- 4~5개 문자열 배열
active boolean NOT NULL
content_hash char(64) NOT NULL
approved_at timestamptz NULL
created_at timestamptz NOT NULL
~~~

UNIQUE(version, id)을 사용한다. 고정 scenario ID는 다음 5개다.

~~~text
BLACKOUT_STUDIO
SNOWBOUND_LODGE
CLOSING_MUSEUM
LAST_BANQUET_GUEST
STOPPED_NIGHT_TRAIN
~~~

#### scenario_templates

~~~text
id uuid PRIMARY KEY
scenario_id varchar(64) NOT NULL REFERENCES scenario_catalog(id) ON DELETE RESTRICT
template_kind varchar(16) NOT NULL          -- ALIBI / OBSERVATION
template_key varchar(64) NOT NULL
text_template varchar(240) NOT NULL
subject_mode varchar(16) NOT NULL           -- NONE / SEAT / ANONYMOUS
active boolean NOT NULL
created_at timestamptz NOT NULL
~~~

UNIQUE(scenario_id, template_kind, template_key)을 둔다. 시나리오마다 활성 ALIBI
9개 이상과 OBSERVATION 9개 이상을 가져야 한다. SEAT이면 좌석 placeholder가 있어야
하며 role, faction과 범인을 직접 나타내는 컬럼은 두지 않는다.

#### agent_personas

~~~text
id varchar(64) PRIMARY KEY
version varchar(32) NOT NULL
display_name varchar(40) NOT NULL
speech_style varchar(240) NOT NULL
backstory varchar(500) NOT NULL
parameters jsonb NOT NULL
active boolean NOT NULL
content_hash char(64) NOT NULL
created_at timestamptz NOT NULL
~~~

parameters의 고정 key는 sociability, assertiveness, suspicion, deception,
risk_tolerance, memory_recall, reasoning_skill, emotionality, cooperativeness,
verbosity다. 모두 유한한 0.0~1.0이며 reasoning_skill도 preset별 값을 허용한다.
현재 등록 목표는 마스터플랜의 WU-B6 추론 수치 표에 따른 0.60~0.80이다.

#### games

~~~text
id uuid PRIMARY KEY
owner_user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT
status varchar(16) NOT NULL                -- IN_PROGRESS / SAVED / COMPLETED / FAILED
phase varchar(32) NOT NULL
round smallint NOT NULL                     -- 0~5
day_number smallint NOT NULL                -- 1~6
state_version bigint NOT NULL               -- 1 이상
next_event_sequence bigint NOT NULL        -- 1 이상
next_front_sequence bigint NOT NULL        -- 1 이상
player_count smallint NOT NULL             -- 6~9
mafia_count smallint NOT NULL
ruleset_version varchar(32) NOT NULL       -- mystery-v1
scenario_version varchar(32) NOT NULL      -- scenario-v1
scenario_id varchar(64) NOT NULL REFERENCES scenario_catalog(id) ON DELETE RESTRICT
scenario_content_hash char(64) NOT NULL
seed_ciphertext bytea NOT NULL
seed_nonce bytea NOT NULL
seed_key_id varchar(64) NOT NULL
agent_config_version varchar(64) NOT NULL
fast_forward_enabled boolean NOT NULL
winner varchar(16) NULL                    -- CITIZEN / MAFIA
win_reason varchar(32) NULL
saved_at timestamptz NULL
finished_at timestamptz NULL
created_at timestamptz NOT NULL
updated_at timestamptz NOT NULL
~~~

허용 phase는 ROLE_REVEAL, DAY_DISCUSSION, NIGHT_ACTION, DAY_VOTE, REVOTE,
FINAL_DISCUSSION, FINAL_ACCUSATION, ENDED다. NIGHT_RESOLUTION은 저장 phase가 아니라
밤 결과를 확정하는 Backend 내부 Transaction 단계다.

COMPLETED이면 phase=ENDED, winner, win_reason, finished_at이 모두 있어야 한다.
SAVED이면 열린 window의 deadline_at은 NULL이고 timed window만 remaining_ms_on_save를
가진다. fast_forward_enabled=true는 인간 player 사망 시에만 허용한다.

#### game_players

~~~text
id uuid PRIMARY KEY
game_id uuid NOT NULL REFERENCES games(id) ON DELETE CASCADE
user_id uuid NULL REFERENCES users(id)
kind varchar(8) NOT NULL                    -- HUMAN / AI
seat smallint NOT NULL                      -- 1~9
display_name varchar(40) NOT NULL
role varchar(16) NOT NULL                   -- MAFIA / DETECTIVE / DOCTOR / CITIZEN
faction varchar(16) NOT NULL                -- MAFIA / CITIZEN
alive boolean NOT NULL
persona_id varchar(64) NULL REFERENCES agent_personas(id)
eliminated_phase varchar(32) NULL
eliminated_round smallint NULL              -- 1~5
created_at timestamptz NOT NULL
updated_at timestamptz NOT NULL
~~~

UNIQUE(game_id, seat), UNIQUE(game_id, id), UNIQUE(game_id, user_id)
WHERE user_id IS NOT NULL을 둔다. HUMAN은 정확히 한 명이고 user_id가 있으며
persona_id는 NULL이다. AI는 반대다. role은 projection 전까지 비공개다.

#### player_scenario_facts

~~~text
id uuid PRIMARY KEY
game_id uuid NOT NULL REFERENCES games(id) ON DELETE CASCADE
player_id uuid NOT NULL REFERENCES game_players(id) ON DELETE CASCADE
fact_kind varchar(16) NOT NULL              -- ALIBI / OBSERVATION
template_id uuid NOT NULL REFERENCES scenario_templates(id) ON DELETE RESTRICT
rendered_text varchar(240) NOT NULL
subject_player_id uuid NULL
created_at timestamptz NOT NULL
~~~

UNIQUE(game_id, player_id, fact_kind)을 둔다. game/player와 subject_player는
game_players를 참조하는 복합 FK를 사용한다. 익명 관찰은 subject_player_id=NULL이다.

#### action_windows

~~~text
id uuid PRIMARY KEY
game_id uuid NOT NULL REFERENCES games(id) ON DELETE CASCADE
window_kind varchar(24) NOT NULL            -- SPEECH / NIGHT / VOTE / REVOTE / FINAL_VOTE
phase varchar(32) NOT NULL
round smallint NOT NULL                     -- 0~5
cycle smallint NOT NULL                     -- 현재 MVP에서는 1
turn_player_id uuid NULL
opened_state_version bigint NOT NULL
status varchar(16) NOT NULL                 -- OPEN / PAUSED / RESOLVING / RESOLVED / CANCELLED
opened_at timestamptz NOT NULL
deadline_at timestamptz NULL
remaining_ms_on_save integer NULL
resolved_at timestamptz NULL
~~~

게임당 OPEN, PAUSED, RESOLVING window는 하나만 허용한다. turn_player_id는 개별
발언 window에서만 설정한다. 밤은 30초, 투표 계열은 30초이며 OPEN window만 제출을
받는다.

#### action_submissions

~~~text
id uuid PRIMARY KEY
game_id uuid NOT NULL REFERENCES games(id) ON DELETE CASCADE
window_id uuid NOT NULL REFERENCES action_windows(id) ON DELETE CASCADE
actor_player_id uuid NOT NULL REFERENCES game_players(id) ON DELETE CASCADE
action_type varchar(24) NOT NULL             -- SPEAK / PASS / ATTACK / INVESTIGATE / PROTECT / VOTE
target_player_id uuid NULL
message varchar(200) NULL
source varchar(16) NOT NULL                 -- HUMAN / AGENT / AUTO
observed_state_version bigint NOT NULL
submitted_at timestamptz NOT NULL
~~~

UNIQUE(window_id, actor_player_id)로 최초 유효 제출만 허용한다. game/window/actor/target
소속은 복합 FK로 확인하고, role·phase·alive·target·deadline은 INSERT 전 engine이
검증한다. 자동 선택도 submission으로 저장한다.

#### action_window_resolutions

~~~text
id uuid PRIMARY KEY
game_id uuid NOT NULL REFERENCES games(id) ON DELETE CASCADE
window_id uuid UNIQUE NOT NULL
resolution_type varchar(24) NOT NULL        -- NIGHT / VOTE / REVOTE / FINAL_VOTE
resolution_source varchar(24) NOT NULL      -- SUBMISSIONS / FACTION_AUTO / TIE_RNG 등
resolved_target_player_id uuid NULL
result_payload jsonb NOT NULL
rng_proof_hash char(64) NULL
resolved_state_version bigint NOT NULL
resolved_at timestamptz NOT NULL
~~~

window과 target은 같은 game인지 복합 FK로 확인한다. 생존 마피아 한 명만 제출하면
그 공격을 사용하고, 전원 미제출이면 진영 자동 공격을 한 번 기록한다. 탐정·의사·투표
미제출은 player별 AUTO submission을 만든다.

#### game_events

~~~text
id uuid PRIMARY KEY
game_id uuid NOT NULL REFERENCES games(id) ON DELETE CASCADE
sequence bigint NOT NULL
front_sequence bigint NULL
operation_index smallint NULL
state_version bigint NOT NULL
event_type varchar(64) NOT NULL
audience varchar(16) NOT NULL                -- PUBLIC / PLAYER / ADMIN
audience_player_id uuid NULL
schema_version smallint NOT NULL
operation_type varchar(32) NULL
payload jsonb NOT NULL
created_at timestamptz NOT NULL
~~~

UNIQUE(game_id, sequence)와
UNIQUE(game_id, front_sequence, operation_index) WHERE front_sequence IS NOT NULL을
둔다. 공개 event에는 role·개별 투표·밤 행동을 넣지 않는다. PLAYER event는 정확한
audience_player_id가 필요하다. event는 append-only이며 runtime UPDATE·DELETE 권한을
주지 않는다.

허용 operation type은 SET_GAME_STATE, REPLACE_PLAYERS, SET_PRIVATE_STATE,
SET_ACTION_WINDOW, CLEAR_ACTION_WINDOW, APPEND_PUBLIC_EVENT, APPEND_PRIVATE_EVENT,
SET_RESULT다. visible Transaction의 공개 event와 인간 대상 private event는 같은
front_sequence를 사용한다. AI 대상·ADMIN event는 Front sequence를 사용하지 않는다.

#### command_receipts

~~~text
id uuid PRIMARY KEY
principal_type varchar(16) NOT NULL         -- USER / AGENT
principal_id uuid NOT NULL
idempotency_key uuid NOT NULL
route_scope varchar(120) NOT NULL
game_id uuid NULL
request_hash char(64) NOT NULL
result_state_version bigint NOT NULL
http_status smallint NOT NULL
result_body jsonb NOT NULL
created_at timestamptz NOT NULL
~~~

UNIQUE(principal_type, principal_id, idempotency_key)을 둔다. 같은 key와 다른 request
hash는 IDEMPOTENCY_KEY_REUSED다. 공개 API key는 Idempotency-Key, 내부 proposal key는
body의 proposal_id이며 MCP 세션 개설 토큰(bootstrap token)은 nonce ledger를
사용한다.

#### game_snapshots

~~~text
id uuid PRIMARY KEY
game_id uuid NOT NULL REFERENCES games(id) ON DELETE CASCADE
state_version bigint NOT NULL
last_front_sequence bigint NOT NULL
schema_version smallint NOT NULL
state_ciphertext bytea NOT NULL
nonce bytea NOT NULL
key_id varchar(64) NOT NULL
checksum char(64) NOT NULL
created_at timestamptz NOT NULL
~~~

UNIQUE(game_id, state_version)을 둔다. checksum이 맞지 않으면 normalized table과
event로 재구성한다. 암호문이나 전체 engine object를 API로 반환하지 않는다.

#### agent_jobs

~~~text
id uuid PRIMARY KEY
game_id uuid NOT NULL REFERENCES games(id) ON DELETE CASCADE
player_id uuid NULL
window_id uuid NOT NULL
job_kind varchar(24) NOT NULL               -- SPEECH / NIGHT_ACTION / VOTE / GM_NARRATION
reserved_state_version bigint NOT NULL
status varchar(16) NOT NULL                 -- RESERVED / SUCCEEDED / FALLBACK / STALE / FAILED
lease_token uuid NOT NULL
lease_expires_at timestamptz NOT NULL
normalized_proposal jsonb NULL
failure_code varchar(64) NULL
created_at timestamptz NOT NULL
completed_at timestamptz NULL
~~~

AI player job은 (window_id, player_id, job_kind) 조건부 unique, GM job은
(window_id, job_kind) 조건부 unique를 둔다. GM job만 player_id가 NULL이다. lease는
예약 시각부터 최대 40초 또는 현재 window deadline 중 이른 시각이다. MCP 조회와
모델 최초·교정 호출은 이 마감에서 완료·제출 여유 3초를 뺀 예산을 공유하며,
모델 호출 상한은 Backend 배포 `LLM_TIMEOUT_SECONDS`(기본 30초)를 따른다.

#### agent_capabilities

~~~text
id uuid PRIMARY KEY
token_hash char(64) UNIQUE NOT NULL
game_id uuid NOT NULL REFERENCES games(id) ON DELETE CASCADE
subject_type varchar(16) NOT NULL           -- AI_PLAYER / GM
subject_player_id uuid NULL
phase varchar(32) NOT NULL
state_version bigint NOT NULL
window_id uuid NULL
allowed_resources jsonb NOT NULL
allowed_tools jsonb NOT NULL
expires_at timestamptz NOT NULL
revoked_at timestamptz NULL
created_at timestamptz NOT NULL
~~~

AI player만 subject_player_id를 가지며 GM은 NULL이다. raw capability는 CSPRNG
32-byte base64url로 만들고 DB·log에는 저장하지 않는다. phase·window·game 종료 시
revoke한다.

#### internal_request_nonces

~~~text
scope varchar(24) NOT NULL                 -- ENGINE_HMAC / MCP_BOOTSTRAP
nonce uuid NOT NULL
request_hash char(64) NOT NULL
expires_at timestamptz NOT NULL
created_at timestamptz NOT NULL
~~~

PRIMARY KEY(scope, nonce)로 replay를 막는다. Redis 존재 여부가 아니라 PostgreSQL
unique ledger가 최종 판정한다.

#### event_outbox

~~~text
id bigserial PRIMARY KEY
game_event_id uuid UNIQUE NOT NULL REFERENCES game_events(id) ON DELETE CASCADE
available_at timestamptz NOT NULL
published_at timestamptz NULL
attempt_count integer NOT NULL
last_error_code varchar(64) NULL
~~~

payload 복사본은 저장하지 않는다. publisher가 DB event를 읽어 같은 Front batch를
Redis stream에 전달한다. private event는 SSE stream에 발행하지 않는다.

#### feedback

~~~text
id uuid PRIMARY KEY
user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT
feedback_type varchar(16) NOT NULL         -- GENERAL / GAME
game_id uuid NULL
rating smallint NOT NULL                    -- 1~5
comment varchar(1000) NULL
tags jsonb NOT NULL
created_at timestamptz NOT NULL
~~~

GAME feedback은 소유자이며 종료된 게임에만 허용하고
UNIQUE(user_id, game_id) WHERE feedback_type='GAME'을 둔다. GENERAL feedback의
game_id는 NULL이며 feedback은 게임 engine input이 아니다.

#### admin_audit_events

~~~text
id bigserial PRIMARY KEY
admin_user_id uuid NOT NULL
action varchar(64) NOT NULL
target_game_id uuid NULL
request_id uuid NOT NULL
created_at timestamptz NOT NULL
~~~

IP, 전체 header, secret과 응답 payload를 저장하지 않는다.

## 4. 게임 규칙 구현

### 저장 phase와 내부 처리

게임 생성 직후 값은 IN_PROGRESS, ROLE_REVEAL, round=0, state_version=1이다.
BEGIN_GAME이 첫날 낮을 연다. NIGHT_RESOLUTION은 DB phase로 저장하지 않고 밤 결과,
사망, 승패, 다음 phase와 event를 하나의 내부 Transaction에서 확정한다.

### 역할 배정

| 인원 | 마피아 | 탐정 | 의사 | 시민 |
|---:|---:|---:|---:|---:|
| 6 | 1 | 1 | 1 | 3 |
| 7 | 1 | 1 | 1 | 4 |
| 8 | 2 | 1 | 1 | 4 |
| 9 | 2 | 1 | 1 | 5 |

Backend CSPRNG seed에서 결정적 RNG를 만들고 결과를 저장한다. 인간 역할은 무작위이며
방 생성자에게 특별 권한은 없다. 마피아끼리 서로의 정체를 알려주지 않는다.

### 낮·밤·투표

- 낮 발언은 생존자 좌석순으로 SPEAK 또는 PASS를 한 번씩 처리한다.
- 발언은 정규화 후 1~200자다.
- 첫날은 투표하지 않는다.
- 생존자 전원이 발언 또는 PASS를 제출하면 다음 phase로 전환한다.
- 밤은 30초, 투표는 30초다.
- 마피아는 자기 자신을 공격할 수 없고, 탐정은 자기 자신을 조사할 수 없다.
- 의사는 자기 자신을 보호할 수 있다.
- 밤 시작 시 생존자와 대상 후보를 고정한다.
- 첫 유효 제출만 인정하고 이후 제출은 거부한다.
- 마피아 한 명 제출은 그 공격을 사용하고, 전원 미제출이면 진영 자동 공격을 한다.
- 탐정·의사 미제출은 역할별 자동 대상, 투표 미제출은 규칙 기반 자동 투표다.
- 탐정 결과는 해당 탐정에게만 마피아 또는 마피아가 아닙니다로 제공한다.
- 투표 중간 선택과 개별 표는 숨기고 결과 집계만 공개한다.
- 동률이면 재투표하고, 재투표도 동률이면 처형하지 않는다.

### 승리·저장·관전

- 생존 마피아가 0명이면 시민 승리
- 생존 마피아 수가 생존 비마피아 수 이상이면 마피아 승리
- 표준 승패가 없으면 다섯 번째 밤 뒤 최종 토론과 최종 고발
- 인간 player가 사망하면 관전 상태가 되고 FAST_FORWARD를 허용한다.
- FAST_FORWARD는 인간 행동을 대신 제출하지 않고 AI turn을 자동 진행한다.
- 저장 시 timed window의 남은 millisecond를 보관하고 deadline_at을 NULL로 만든다.
- 재개 시 timed window만 새 deadline_at을 만들며 role·scenario·seed·결과를 다시 뽑지 않는다.
- 브라우저 새로고침·연결 해제는 서버 deadline을 중단하지 않는다.

## 5. Transaction과 Redis

### 사용자 최초 쓰기·게임 생성

~~~text
Idempotency lock
→ users upsert
→ 동일 사용자 동시 create 직렬화
→ 직전 성공 scenario 제외 후 seed 기반 scenario 선택
→ player·role·persona·fact 계산
→ seed 암호화
→ games/player/fact INSERT
→ GAME_CREATED event와 outbox INSERT
→ command receipt INSERT
→ COMMIT
~~~

### 사용자 command

~~~text
Idempotency receipt 확인
→ games FOR UPDATE
→ owner/status/expected_state_version 검증
→ window/player/role/alive/target/deadline 검증
→ submission 또는 phase 변경
→ state_version + 1
→ event·outbox·receipt INSERT
→ COMMIT
~~~

### Window 해소

한 worker만 OPEN → RESOLVING을 성공하도록 한다. 실패하면 다시 OPEN으로 돌린다.
자동 submission, 결과 집계, 사망, 승패, 다음 phase, event와 snapshot을 한 Transaction에서
확정한다.

### Agent 외부 호출

~~~text
Tx A: agent_jobs reservation COMMIT
→ 외부 MCP context 조회
→ 선택된 단일 Provider 호출
→ proposal schema 검증
Tx B: game lock 재획득 및 lease·phase·window·version 재검증
→ 유효하면 반영, 아니면 STALE 또는 fallback
→ COMMIT
~~~

외부 호출 중에는 DB Transaction과 Redis game lock을 잡지 않는다.

### Redis key

~~~text
mafia:v1:lock:game:{game_id}
mafia:v1:public:{game_id}:{state_version}
mafia:v1:events:{game_id}
mafia:v1:outbox:wakeup
mafia:v1:nonce:engine:{nonce}
mafia:v1:nonce:mcp-bootstrap:{nonce}
mafia:v1:health
~~~

Redis lock은 token과 bounded TTL을 사용한다. Redis가 없어도 PostgreSQL row lock,
unique constraint와 state_version이 최종 방어선이다. Redis 장애 중 새 Agent turn과
fan-out 최적화를 중단하고 PostgreSQL 원본으로 복구한다.

## 6. API 계획

### 공통 형식

공개 API prefix는 /api/v1이다. JSON은 UTF-8, 시각은 UTC RFC3339, 알 수 없는 request
field는 422 VALIDATION_ERROR로 거부한다. 문자열은 제어문자 제거, Unicode NFC,
줄바꿈·연속 공백 정규화를 거친다.

필수·선택 header:

~~~text
X-User-Id       -- 공개·관리자 API, UUID v4
X-Request-Id    -- 선택
Idempotency-Key -- 변경하는 공개 POST, UUID v4
Last-Event-ID   -- SSE 재연결용 front_sequence
~~~

UUID는 인증 증명이 아니므로 개인 개발·사설망 범위에서 사용한다. Front→Backend
OAuth, Front HMAC과 URL 내 role/private 정보는 사용하지 않는다.

성공 envelope는 data와 meta(request_id, server_time, replayed)를 사용하고, 실패
envelope는 error(code, message, request_id, retryable, details)를 사용한다.

Cross-origin Front 연결은 API 정본의 CORS 정책을 따른다. 모든 origin을 `*`로 허용하며
별도 origin allowlist를 설정하지 않는다. 허용 request header는 `X-User-Id`,
`X-Request-Id`, `Idempotency-Key`, `Last-Event-ID`, `Content-Type`이고 credentials
인증은 사용하지 않는다. same-origin proxy를 선택하면 proxy가 동일 header와
`text/event-stream` 응답을 전달한다.

### 공개·관리자 API

~~~text
POST /api/v1/games
GET  /api/v1/games
GET  /api/v1/games/{game_id}
POST /api/v1/games/{game_id}/commands
GET  /api/v1/games/{game_id}/sync
GET  /api/v1/games/{game_id}/events
POST /api/v1/feedback
GET  /api/v1/admin/games
GET  /api/v1/admin/games/{game_id}
GET  /api/v1/admin/metrics
~~~

게임 생성 request는 player_count, ruleset_version, scenario_version만 받는다.
scenario는 client가 고르지 않고 Backend가 seed와 직전 성공 게임 제외 규칙으로 정한다.
생성 후 snapshot_url을 반환하고 첫날 토론은 별도 BEGIN_GAME command로 연다.

관리자 API는 ADMIN_USER_IDS allowlist를 통과한 UUID만 사용할 수 있다. allowlist가
비어 있거나 잘못되면 전부 403 ADMIN_ACCESS_DENIED이고, 관리자 기능은 read-only다.
진행 중 role, 개인 fact, 개별 행동·투표, seed와 Agent private context는 반환하지 않는다.

### 단일 command API

~~~text
POST /api/v1/games/{game_id}/commands
~~~

모든 명령은 type과 expected_state_version을 사용한다.

~~~text
BEGIN_GAME
SPEAK
PASS
SUBMIT_NIGHT_ACTION
SUBMIT_VOTE
SAVE_AND_EXIT
RESUME
FAST_FORWARD
~~~

성공 data에는 command_id, command_type, accepted_state_version,
result_state_version, sync_url을 넣는다. command_id는 Idempotency-Key와 같은 UUID다.
응답에 snapshot을 넣지 않고 Front가 sync_url 또는 game GET으로 현재 상태를 확인한다.

SUBMIT_NIGHT_ACTION은 client가 role이나 subtype을 보내지 않고 target만 보낸다.
Backend가 저장 role로 ATTACK·INVESTIGATE·PROTECT를 결정한다. SPEAK는 1~200자,
투표 target은 valid_targets에 있고 자기 자신이 아니어야 한다.

### Sync·SSE

sync는 after_state_version, after_sequence를 받는다.

`after_state_version`과 `after_sequence`는 polling cursor이며, SSE의
`Last-Event-ID`는 동일한 `after_sequence`를 가리키는 마지막 Front sequence다. 두
transport는 동일한 Front-visible sequence와 완전한 operation batch를 사용하고 별도
cursor를 만들지 않는다.

- mode=DELTA: snapshot=null, 완전한 operation batch 배열
- mode=SNAPSHOT: operations=[], authoritative snapshot
- 변경 없음: 200, mode=DELTA, operations=[]
- sequence/index gap 또는 보존 범위 밖: 일부 적용 없이 snapshot 재요청
- Front dedup key: game_id, front_sequence, operation_index

SSE는 text/event-stream이며 하나의 event에 한 front_sequence의 전체 operation을
index 순서로 담는다. Last-Event-ID 다음부터 재개하고 보존 범위 밖이면 SNAPSHOT event를
보낸다. heartbeat는 comment이며 operation이 아니다. 연결이 끊겨도 서버 deadline은
계속되고 Front는 polling으로 전환한다.

### 오류 코드

~~~text
400 MISSING_USER_ID, INVALID_REQUEST
403 ADMIN_ACCESS_DENIED, PLAYER_DEAD, ACTION_NOT_ALLOWED
404 GAME_NOT_FOUND, RESOURCE_NOT_FOUND
409 STALE_STATE_VERSION, IDEMPOTENCY_KEY_REUSED, ACTION_ALREADY_SUBMITTED,
    WINDOW_CLOSED, INVALID_PHASE, GAME_BUSY, GAME_ALREADY_ENDED, GAME_NOT_SAVED,
    FEEDBACK_ALREADY_SUBMITTED
422 VALIDATION_ERROR
429 RATE_LIMITED
503 DEPENDENCY_UNAVAILABLE
~~~

## 7. AI·MCP 내부 계약

내부 API:

~~~text
GET  /internal/v1/agent-context?scope=public|me|turn|persona|gm-guide
POST /internal/v1/mcp-bootstrap/consume
POST /internal/v1/agent-proposals
~~~

Engine 요청은 X-Engine-Timestamp, X-Engine-Nonce, X-Engine-Signature,
X-Agent-Capability를 사용한다. signature canonical 형식은 METHOD, PATH,
CANONICAL_QUERY, SHA256_HEX(RAW_BODY), TIMESTAMP, NONCE를 줄바꿈으로 연결한다.
timestamp 허용 범위는 ±60초이며 nonce는 PostgreSQL 원장에 먼저 기록한다.

Agent proposal은 body의 proposal_id를 idempotency key로 사용하고 허용 type은 SPEAK,
PASS, NIGHT_ACTION, VOTE다. MCP Tool input에는 game_id, agent_id, role, phase,
version을 넣지 않는다.

Backend는 MCP 세션 개설 토큰을 MCP_SERVER_AUTH_SECRET으로 만들고, MCP가 Backend를
호출할 때는 별도의 ENGINE_INTERNAL_API_SECRET을 사용한다. MCP runtime은 token을
opaque 값으로만 전달하고 DB·Redis에 직접 접근하지 않는다.

AI context audience:

- public: 공개 scenario·player·phase·사건
- me: 자기 role·fact·private event
- turn: 현재 자기 차례와 허용 대상
- persona: 서버 등록 persona
- gm-guide: 공개 정보와 고정 진행 지침

GM에는 role, 공격자, 보호 대상, 조사 결과와 개별 투표를 전달하지 않는다.
AI 발언 실패는 PASS, 행동·투표 실패는 규칙 기반 자동 처리, GM 실패는 고정 한국어
문장이다. Provider 장애 시 자동 Provider 전환을 하지 않는다.

## 8. WU 실행 순서와 완료 기준

### WU-B1 — identity/OIDC API 제거와 UUID user context

- 범위: X-User-Id UUID v4 검증, 최초 쓰기 user upsert, game ownership
- DB: users만 사용하고 OAuth/profile 컬럼을 읽거나 쓰지 않음
- API: identity route 미등록, 조회에서 알 수 없는 UUID 자동 생성 금지
- 실패: UUID 누락·형식 오류, 소유권 위반, 다른 게임 존재 노출
- 테스트: UUID, ownership, 최초 쓰기 idempotency, legacy route 부재

### WU-B2 — Migration·Seed·시나리오 콘텐츠

- 범위: 19개 canonical table, index·constraint, scenario·persona seed
- DB: AI_MAFIA_DB_DESIGN.md의 컬럼명·자료형·NULL·FK를 1:1 구현
- 데이터: 5 scenario, 각 scenario ALIBI 9개 이상·OBSERVATION 9개 이상
- 실패: content hash 오류, 승인되지 않은 scenario, 중복 seed
- 테스트: 빈 DB, 기존 DB upgrade, Migration 재실행, 정적 콘텐츠 검증

### WU-B3 — Repository·Transaction·Redis

- 범위: table repository, game row lock, receipt, outbox, Redis lock/cache/stream
- DB: 상태·version·event·receipt·outbox를 command Transaction에서 동시 확정
- 실패: duplicate, stale version, concurrent create/command, Redis 장애
- 테스트: 동시 요청 1개 성공, rollback 후 재시도, Redis 중단 후 DB 원본 복구

### WU-B4 — 순수 게임 엔진·결정적 RNG

- 범위: phase 전이, 역할, 낮, 밤, 투표, 승패, save/resume, fast-forward
- 규칙: NIGHT_RESOLUTION은 내부 단계이며 저장 phase enum에 추가하지 않음
- 실패: 잘못된 actor/role/target, window 만료, death, tie
- 테스트: 6~9명 table-driven, 고정 seed property test, 다섯 번째 밤, 전체 replay

### WU-B6 — Agent Manager·LLM adapter

- 범위: reservation, 40초 lease, capability, context, proposal normalization, fallback
- DB: agent_jobs, agent_capabilities와 fencing token 사용
- Provider: 환경으로 선택된 단일 Provider, 자동 failover 없음
- 실패: Provider/MCP 오류, schema 오류, lease 만료, stale version
- 테스트: dummy/fake transport, private context 비간섭, 늦은 결과 무시

### WU-B7 — Internal Engine API·Outbox·SSE

- 범위: HMAC, nonce, MCP 세션 개설 토큰, agent proposal, publisher, SSE reconnect
- DB: nonce ledger와 append-only event 사용
- 실패: signature·nonce·capability 거부, sequence gap, outbox 중복
- 테스트: HMAC replay, stale capability, complete batch, polling/SSE dedup

### WU-B5 — 공개 game·sync·feedback API

- 범위: 생성, 목록, snapshot, command, sync, SSE, feedback
- API: 공개 정본의 envelope·header·union·오류 코드 그대로 사용
- 화면 연계: countdown은 표시용이고 실제 마감은 Backend가 판단
- 실패: stale, duplicate, closed window, dead player, invalid phase
- 테스트: 생성부터 종료까지, save/resume, feedback unique, snapshot fallback

### WU-B8 — read-only 관리자·audit

- 범위: 관리자 목록·상세·metrics, allowlist, audit event
- DB: admin_audit_events 기록, private field redaction
- 실패: 비관리자 접근, 진행 중 private 정보 요청
- 테스트: allowlist, read-only, 관리자 응답 비공개 정보 누출 검사

### WU-B9 — 시뮬레이션·회귀·운영 보강

- 범위: 전체 회귀, heuristic bot, 장애 복구, 운영 검증
- 테스트: 100회·1000회 synthetic game, Redis/DB/LLM/MCP 장애
- 증거: Migration 결과, OpenAPI snapshot, 로그 redaction, runbook과 release evidence

## 9. Migration 원칙

- 기존 001, 002 Migration은 수정하지 않음
- 다음 번호의 순방향 Migration만 추가
- Backend가 Migration SQL 작성
- MCP·Data 담당자가 DB에 실행
- 빈 DB와 기존 DB 모두 검증
- Migration 재실행 시 중복 데이터 생성 금지
- 실제 DB와 정본이 다르면 schema diff 후 정본 기준 forward-only 반영
- 운영 DB에 직접 임의 수정하지 않음
- migration 계정과 runtime DML 계정의 권한을 분리
- MCP runtime에는 DB·Redis 자격증명을 주입하지 않음

## 10. 검증 계획

### DB·Migration

- 19개 테이블의 정확한 이름·컬럼·자료형·NULL 조건
- FK, 복합 FK, UNIQUE, partial unique index와 index
- 6~9명 역할 수와 HUMAN 정확히 1명
- scenario별 alibi·observation 9개 이상
- Migration 빈 DB·upgrade·재실행
- Redis flush 후 PostgreSQL에서 snapshot·event 재구성
- seed와 snapshot AES-256-GCM, checksum과 key 오류 처리

### 게임·API

- 모든 command의 성공·거부 matrix
- 잘못된 phase·actor·role·alive·target·deadline
- duplicate key와 stale state version
- 밤 자동 처리·동률·재투표·최종 고발
- 공개·인간 private·AI private·GM projection 비간섭
- DELTA/SNAPSHOT, no-change sync, SSE reconnect
- feedback union과 game별 unique
- /openapi.json의 path·union·enum·필수 header

### 장애·보안

- Redis 장애에서 새 Agent turn 중단과 DB 원본 복구
- Provider·MCP 오류 fallback
- 40초 lease·window deadline 만료와 fencing token
- Engine HMAC nonce·MCP 세션 개설 토큰의 nonce replay 거부
- capability 만료·폐기·allowlist 검사
- secret, prompt, raw response, private context, Chain of Thought 로그·DB 비저장
- 관리자 allowlist fail-closed

## 11. 구현자가 임의로 결정하면 안 되는 사항

- DB 테이블명·컬럼명·자료형·제약조건 변경
- NIGHT_RESOLUTION을 DB phase로 추가하는 것
- Front에서 role·승패·deadline을 재판정하는 것
- Provider 자동 failover
- LLM token·비용·timeout·예산 metric 추가
- MCP runtime의 DB·Redis 직접 연결
- 관리자 강제 종료·삭제 기능 추가
- 기존 001, 002 Migration 수정
- 계획서·코드·로그에 실제 DB URL·비밀번호·API key 기록

실제 운영 Provider와 model은 환경변수로 주입하되 자동화 테스트는 dummy 또는 fake
transport를 사용한다. agent_config_version의 MVP 값은 agent-config-v1로 고정한다.
실제 DB가 정본과 다른지는 MCP·Data 담당자가 schema diff로 확인하고, 차이는 정본 기준
순방향 Migration으로 반영한다.

## 12. 체크포인트와 최종 완료 조건

| 체크포인트 | Backend 통과 조건 |
|---|---|
| CP-0 | 5개 정본 링크·용어·schema·공통 envelope 확인 |
| CP-1 | B1 완료, UUID-only 요청과 ownership 테스트 |
| CP-2 | B2·B3 완료, Migration 재실행·Transaction·lock 테스트 |
| CP-3 | B4 완료, 규칙·결정성·불변식 회귀 |
| CP-4 | B6·B7 완료, Agent/MCP audience 격리와 fallback E2E |
| CP-5 | B5 완료, 생성→진행→저장→재개→종료→feedback E2E |
| CP-6 | B8·B9 완료, 관리자 거부·장애 복구·운영 증거 |

순서는 CP-M1A → WU-B2 Migration 산출물 → WU-M1B → CP-2를 따른다.
MCP 담당자는 Backend 소유 Migration SQL을 수정하지 않는다.

최종적으로 다음을 만족해야 한다.

- API가 /openapi.json에서 정본 path·union·enum·필수 header를 제공한다.
- Front와 MCP 없이도 synthetic 요청으로 게임 전체를 진행할 수 있다.
- 같은 seed로 같은 role·target·tie·winner 결과를 재현한다.
- Redis 장애 후에도 PostgreSQL 원본으로 복구하고 결과를 다시 추첨하지 않는다.
- 공개 snapshot·sync·SSE·log에 비공개 정보가 섞이지 않는다.
- AI·MCP·관리자 실패와 replay가 정해진 fallback 또는 fail-closed로 처리된다.
- 5개 정본과 이 계획서의 용어·필드·phase·오류 코드가 일치한다.
