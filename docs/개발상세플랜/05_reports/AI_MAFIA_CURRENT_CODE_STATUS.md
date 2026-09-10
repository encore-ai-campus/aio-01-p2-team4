# AI 마피아 현재 코드 상태

**기준일:** 2026-09-07  
**기준 브랜치:** `Hwanseok`, merge `3157f17`

**상태:** merge 이후 가상환경·의존성 준비와 재점검 완료; 게임 전체 통합은 미검증

이 문서는 여러 임시 계획 문서를 대신해 현재 저장소에 실제로 존재하는 구현,
실행 경로, 검증 결과와 남은 제약을 기록한다. 제품 규칙과 공개 API의 규범적
계약은 `docs/개발상세플랜/` 아래의 정본 문서를 따른다.

## 1. 현재 구현 요약

- 로그인·OAuth 없이 브라우저가 생성한 UUID v4를 사용자 식별자로 사용한다.
- Frontend는 Streamlit 사용자 앱과 관리자 앱으로 분리되어 있다.
- Backend는 FastAPI 공개 API, 게임 규칙 판정, PostgreSQL 영속화와 AI 진행 worker를 소유한다.
- 게임 상태 변경은 PostgreSQL transaction과 `expected_state_version`으로 보호된다.
- 게임 이벤트는 `game_events`에 기록하고 Frontend 동기화용 operation envelope로 변환한다.
- MCP 서버는 FastMCP Resource·Prompt·Tool을 등록하고 Backend 내부 API를 호출한다.
- LLM provider는 `dummy`, `local`, `openai`, `gemini` 중 하나를 선택하며 테스트는
  fake 또는 mock transport를 사용한다.

## 2. 게임 실행 흐름

```text
게임 생성 -> ROLE_REVEAL -> BEGIN_GAME -> DAY_DISCUSSION -> NIGHT_ACTION
-> DAY_DISCUSSION -> DAY_VOTE -> REVOTE(동률) -> NIGHT_ACTION 반복
-> FINAL_DISCUSSION / FINAL_ACCUSATION -> COMPLETED 또는 FAILED
```

- 게임 생성은 `POST /api/v1/games`에서 6~9명과 `mystery-v1`·`scenario-v1`을 검증한다.
- 생성 직후 역할 공개 snapshot을 반환하고 `BEGIN_GAME`이 첫날 토론을 연다.
- 낮 토론은 좌석 순서에 따른 `SPEAK` 또는 `PASS`다.
- 밤에는 마피아·탐정·의사만 `SUBMIT_NIGHT_ACTION`을 제출하고 시민은 Backend가 자동 처리한다.
- 투표·재투표·최종 지목은 `SUBMIT_VOTE`로 처리한다.
- Backend가 phase 전이, deadline, 대상, 생존 상태, 승패를 최종 판정한다.
- 인간 플레이어가 사망하면 Frontend는 관전 모드로 전환한다.
- `SAVE_AND_EXIT`과 `RESUME`은 action window와 남은 시간을 PostgreSQL에 보존·복원한다.

## 3. Backend 구조

- `backend/app/game_engine/`: 순수 규칙, phase 전이, 투표·밤 행동·승패와 deterministic fallback
- `backend/app/services/game/creation_service.py`: 게임·시나리오·플레이어 생성
- `backend/app/services/game/lifecycle_service.py`: BEGIN, SAVE, RESUME transaction
- `backend/app/services/game/discussion_command.py`: 인간·AI 토론 command
- `backend/app/services/game/action_command.py`: 밤 행동·투표·빠른 진행 command
- `backend/app/services/game/game_read_service.py`: 목록·snapshot·공개 projection
- `backend/app/services/game/event_sync_service.py`: game event와 sync envelope 변환
- `backend/app/services/game/postgres_runtime.py`: service와 repository 조합 facade
- `backend/app/services/game/ai_progress_worker.py`: 열린 AI window 비동기 진행
- `backend/app/repositories/`: game, player, action, event, receipt, feedback 저장소
- `backend/app/routers/game_router.py`: 공개 게임·sync·SSE·feedback API
- `backend/app/routers/mcp_registry_router.py`: 최소 MCP 내부 연결 API

운영 runtime은 `app.state.game_runtime`에 주입된다. 기존 scaffold와 legacy migration
구조는 호환을 위해 일부 남아 있지만 canonical 게임 실행은 PostgreSQL 경로를 사용한다.

## 4. Frontend 구조

- `frontend_user/app.py`: UUID 초기화와 화면 dispatcher
- `frontend_user/app_pages/game_create_page.py`: 6~9명 게임 생성
- `frontend_user/app_pages/role_reveal_page.py`: 본인 역할·단서 표시와 BEGIN
- `frontend_user/app_pages/game_page.py`: 진행 중 게임·관전 shell
- `frontend_user/components/action_panel.py`: 토론·밤 행동·투표 입력
- `frontend_user/core/api_client.py`: UUID header 기반 Backend client
- `frontend_user/core/commands.py`: Front UX guard와 command body 구성
- `frontend_user/core/sync.py`: SSE·polling operation 검증·원자 적용
- `frontend_user/components/browser_components/sync/`: fetch streaming SSE
- `frontend_user/app_pages/result_page.py`: Backend 확정 결과 표시
- `frontend_user/app_pages/feedback_page.py`: 일반·게임별 feedback 제출

Front는 규칙·승패·자동 선택을 계산하지 않는다. snapshot의 `legal_actions`,
`action_window`, `valid_targets`를 표시하고 command 결과 후 Backend snapshot을 다시 읽는다.

## 5. 공개 API와 동기화

공개 API prefix는 `/api/v1`이다.

| 기능 | 경로 |
|---|---|
| 게임 생성 | `POST /api/v1/games` |
| 게임 목록 | `GET /api/v1/games` |
| snapshot | `GET /api/v1/games/{game_id}` |
| command | `POST /api/v1/games/{game_id}/commands` |
| polling sync | `GET /api/v1/games/{game_id}/sync` |
| SSE sync | `GET /api/v1/games/{game_id}/events` |
| feedback | `POST /api/v1/feedback` |

변경 요청에는 UUID v4 `Idempotency-Key`, 게임 command에는 `expected_state_version`이 필요하다.
사용자 식별은 `X-User-Id`, 요청 추적은 `X-Request-Id`를 사용한다.

Polling과 SSE는 같은 `game_sync` envelope를 사용한다. sequence/version 불일치 시 전체
snapshot을 반환하고, Front는 부분 operation을 적용하지 않은 채 authoritative snapshot을
재조회한다. 활성 timed window의 `remaining_ms`는 Backend deadline에서 계산한다.

SSE browser fetch를 위해 Backend는 모든 origin의 preflight와 `X-User-Id`,
`X-Request-Id`, `Last-Event-ID` header를 허용한다. origin별 환경 설정은 사용하지 않고
credentials는 허용하지 않는다.

## 6. 저장소와 설정

- PostgreSQL migration은 `backend/migrations/001~004` 순서로 적용한다.
- canonical game schema는 games, game_players, action_windows, action_submissions,
  game_events, receipts와 scenario/fact 데이터를 사용한다.
- seed와 snapshot 암호화 keyring은 저장소 외부 설정을 사용한다.
- Redis client·lock·stream 코드는 Backend에 있으나 canonical 이벤트 원본은 PostgreSQL이다.
- Backend는 `DATABASE_URL`, `DATABASE_NAME`, `REDIS_URL`, `MCP_SERVER_URL`과 선택한
  LLM 설정을 사용한다.
- MCP process는 `BACKEND_API_URL`, `MCP_LISTEN_HOST`, `MCP_LISTEN_PORT`를 사용한다.

실제 비밀번호, API key, token, 사용자 데이터는 문서·로그·fixture에 기록하지 않는다.

## 7. merge 이후 로컬 검증 상태

2026-09-07 macOS/Python 3.12.11 환경에서 실행했다. 루트·MCP 기존 가상환경을
재사용하고 Backend·사용자 Front·관리자 Front 환경을 준비했다. 다섯 환경의
의존성 호환 검사와 root/MCP lock 확인을 마쳤으며 pytest-asyncio 미설치 문제는
해소했다.

| 범위 | 결과 |
|---|---|
| Backend, 실제 DB 테스트 2파일 제외 | 128 passed |
| 사용자 Front | 34 passed |
| 관리자 Front | 3 passed |
| MCP fake·ASGI 4파일 | 6 passed |
| 합계 | 171 passed, 실패 0 |

정확한 재실행 명령은 [README](../../../README.md)의 테스트 절에 있다. 기존 55 passed,
161 passed/12 failed 기록은 merge 전 환경의 기록이며 이번 실행 결과와 합산하지
않는다. 실제 DB 테스트가 추가되었으므로 전체 테스트가 fake라는 과거 설명은 더
이상 맞지 않는다.

## 8. 현재 제약과 다음 통합 확인

- 실제 DB 쓰기·삭제를 수행하는 B5·Postgres game flow·MCP process roundtrip 세
  파일은 이번에 제외했다. 전용 DB·Redis 대상과 migration/seed를 확인한 뒤 실행한다.
- 현재 로컬 설정은 외부 DB와 OpenAI Provider를 선택한다. 실제 연결·유료 호출은
  하지 않았고 `.env`와 비밀값을 변경하거나 출력하지 않았다. 테스트는 우선 dummy
  Provider와 격리 데이터를 사용한다.
- keyring 미설정이면 runtime은 legacy plaintext 경로를 사용한다. 항상 암호화된
  저장 상태라고 가정하지 말고 실제 게임용 keyring을 준비해야 한다.
- AI context에 인간 private snapshot을 재사용하는 경로, PUBLIC 행동 이벤트의
  개별 target 기록, deadline 만료 처리, 2명 마피아·재투표·최종 판정 공백이 남았다.
- Front의 RESUME 화면·UUID 복구 persistence·지속 polling·실시간 countdown·조사
  결과·홈·피드백 동선은 후속 보완 대상이다. 단순 SSE 재연결과 snapshot 재조회는
  merge에서 추가되었다.
- 실제 브라우저의 생성→진행→저장·재개→관전→종료·feedback 전체 E2E는 미검증이다.

해결된 항목과 남은 코드 근거는
[merge 이후 게임 테스트 준비·재점검](AI_MAFIA_GAME_TEST_GAP_REPORT.md)에 정리했다.
