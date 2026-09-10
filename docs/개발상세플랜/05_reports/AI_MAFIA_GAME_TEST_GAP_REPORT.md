# AI 마피아 merge 이후 게임 테스트 준비·재점검

> **최신 수정 기록:** [8절](#8-수정권고-반영과-ai-진행-표시)을 참고하세요. [7절](#7-2026-09-07-브라우저-실게임-1회-테스트와-수정-착수)은 최초 브라우저 1회 완주 기록이며 1~6절은 이전 준비 기록입니다.

작성일: **2026-09-07** · 기준: **Hwanseok / merge `3157f17`**

이 문서는 이전 `5292c2a` 기준의 31개 미완료 항목을 새 merge 코드와 대조한 결과다.
착수 시 Git 작업 트리는 깨끗했다. 이번에는 의존성·가상환경·로컬 터미널 설정과
문서만 변경했으며 게임 기능은 수정하지 않았다.

**Python 테스트 환경은 준비되었고 외부 서비스 없는 테스트 171개가 통과했다.**
PostgreSQL 기본 실행 경로·AI worker·최소 FastMCP 연결은 이전보다 진행되었지만,
정보 격리·일부 규칙·마감 처리·Front 재개 공백 때문에 실제 게임 전체 테스트의
완료를 선언할 수는 없다. 아래 코드 판정과 실제 실행한 검증을 구분한다.

## 1. 이번 merge로 바뀐 판정

현재 기준은 [마스터플랜](../01_core/AI_MAFIA_MASTER_PLAN.md) 상단의
**MVP 단순화·최소 FastMCP 프로파일**이다. custom bootstrap/HMAC/capability/session
registry, 복잡한 reconnect/backoff, Redis publisher 자동 실행은 현 MVP 요구사항에서
제외한다. 기존 M2~M5 복원을 미구현 과제로 다시 올리지 않는다.

| 이전 항목 | merge 이후 판정 | 현재 근거·한계 |
|---|---|---|
| D02 · 공개 게임 메모리 저장 | **기본 연결 해결** | [main.py](../../../backend/app/main.py) L115의 PostgreSQL runtime이 생성·목록·snapshot·저장·재개·행동·feedback을 담당한다. 관리자도 PostgreSQL을 사용한다. 실제 재시작·다중 프로세스 복구는 이번에 실행하지 않았다. |
| G11 · 카탈로그·개인 단서 미연결 | **기본 연결 해결** | [creation_service.py](../../../backend/app/services/game/creation_service.py) L122~178에서 직전 시나리오 제외·seed 선택·persona·좌석별 단서를 만든다. 제품 콘텐츠 승인은 별도 확인 사항이다. |
| D01 · 정상 seed도 실패하는 SQL | **코드 수정 확인** | [004 seed SQL](../../../backend/migrations/004_seed_scenarios_and_personas.sql) L361~379가 `count FILTER`로 바뀌었다. 실제 migration 최초·재실행은 미검증이다. |
| G01 · AI worker·실제 호출 없음 | **부분 해결** | [main.py](../../../backend/app/main.py) L48~59에서 worker를 관리하고 [postgres_runtime.py](../../../backend/app/services/game/postgres_runtime.py) L184~210, L247~293에서 MCP·Provider를 호출한다. GM 진행과 아래 AI 정보 격리는 남았다. |
| G02 · 조회마다 deadline 재설정 | **시간 계산·저장/재개 개선** | [action_timer_service.py](../../../backend/app/services/game/action_timer_service.py)의 밤 30초·투표 30초와 DB deadline 기반 잔여 시간·pause/resume을 사용한다. 만료 검증·해소 공백은 아래 표 참조. |
| G05 · 최종 토론 진입 불가 | **토론 경로 연결** | [discussion_transaction.py](../../../backend/app/services/game/discussion_transaction.py) L55~78에 최종 토론을 연결했다. 최종 지목은 여전히 첫 한 표로 판정한다. |
| F03 · SSE 1회 종료·재접속 없음 | **부분 해결** | Backend 지속 stream, Front 1초 재연결·변경 후 GET·sync 실패 시 GET 복구가 추가됐다. 지속 polling·visibility 복귀·중복 제거 등은 남았다. |
| M01~M05 · 구 MCP 계약 | **기존 프로파일 기준 판정 폐기** | 실제 FastMCP Resource template·Prompt·Tool·HTTP adapter가 있다. 현 문제는 actor context·응답 envelope·운영 Tool 연결이며 구 bootstrap 5-field 복구가 아니다. |
| D04~D05 · 운영 감사 sink·배포 TLS | **현 최소 프로파일 필수 범위에서 제외** | loopback 개발 프로파일이다. 사설망/운영 배포 범위 확대 시 별도 계약으로 다룬다. |
| 나머지 Front·규칙·정보 항목 | **대체로 잔존** | 특히 RESUME 화면, UUID 복구 저장, 조사·결과 상세, 2명 마피아·재투표·최종 판정은 아래 표에 갱신했다. |

## 2. 실제 게임 테스트 전 우선 확인할 공백

P0는 핵심 진행·판정·비공개 정보 경계를 막는 항목, P1은 주요 표시·복구·운영 준비
보완이다. 근거 행 번호는 merge 시점 기준이며, 테스트에서 해당 결함을 재현했다는
표시가 없는 행은 **정적 코드 조사 결과**다.

| ID·우선 | 테스트 장면 | 현재 남은 문제 | 근거·담당 |
|---|---|---|---|
| N01 · P0 | AI가 자신의 역할·단서만 받아 추론 | MCP가 인간 소유자 snapshot을 반환하고 Orchestrator가 같은 응답을 public/me/turn/persona에 재사용한다. 인간 `me.role/alibi/observation`이 AI Provider 입력에 들어가는 데이터 흐름이 있다. actor별 projection을 분리해야 한다. 실제 Provider 호출로 검증하지 않았다. | [mcp_registry_router.py](../../../backend/app/routers/mcp_registry_router.py) L39~40; [orchestrator.py](../../../backend/app/agent/orchestrator.py) L109~118, L175; [game_read_service.py](../../../backend/app/services/game/game_read_service.py) L330~337 · Backend/MCP |
| N02 · P0 | 밤 행동·개별 투표를 종료 전 비공개로 유지 | 인간 행동 제출 직후 `ACTION_RESOLVED`를 PUBLIC으로 기록하면서 `target_player_id`를 포함하고 sync에 그대로 전달한다. 해소 전 개별 선택이 공개 이벤트에 실리는 경로를 수정해야 한다. | [action_command.py](../../../backend/app/services/game/action_command.py) L165, L581~590; [event_sync_service.py](../../../backend/app/services/game/event_sync_service.py) L46~55 · Backend |
| N03 · P0 | 실제 Resource 조회 후 `submit_action` Tool로 행동 승인 | Backend는 `{status,source,context:snapshot}`을 반환하지만 client는 최상위 game/action_window를 찾는다. version/window가 빠질 구조다. Tool·Prompt는 등록됐으나 운영 worker는 Resource→Provider→Backend 직접 실행 경로를 주로 사용한다. Tool 미구현과 운영 미연결을 구분해야 한다. | [client.py](../../../backend/app/mcp/client.py) L132~171; [postgres_runtime.py](../../../backend/app/services/game/postgres_runtime.py) L269~289 · Backend/MCP |
| N04 · P0 | 마감 후 제출 거부·무응답 투표 자동 해소 | deadline 계산은 있으나 window 검증에 현재 시각 비교가 없고 worker에 투표 만료 해소가 없다. 밤 만료 해소는 잠금 뒤 deadline 재검사와 기존 제출 복원이 빠져 이미 제출한 선택을 무시할 수 있다. | [window_service.py](../../../backend/app/services/game/window_service.py) L54~83; [ai_progress_worker.py](../../../backend/app/services/game/ai_progress_worker.py) L57~153; [action_command.py](../../../backend/app/services/game/action_command.py) L285~310 · Backend |
| N05 · P0 | 마피아 2명 공격·동률 재투표·전원 최종 지목 | 두 번째 마피아 공격 거부, 재투표 후보 집합 미보존, 첫 한 명의 최종 선택으로 즉시 승패를 정하는 규칙이 남았다. 최종 토론의 공개 연결은 개선됐지만 최종 다수결·동률 RNG는 별개다. | [night.py](../../../backend/app/game_engine/phases/night.py) L41~44; [vote.py](../../../backend/app/game_engine/phases/vote.py) L51~56; [final_accusation.py](../../../backend/app/game_engine/phases/final_accusation.py) L19~35 · Backend |
| N06 · P0 | 저장 게임을 화면에서 재개 | Backend RESUME는 연결됐고 Front command enum도 있지만, SAVED 전용 화면·RESUME 제출 UI는 없다. 홈의 계속하기는 game 화면 이동만 수행한다. | [app.py](../../../frontend_user/app.py) L91; [home_page.py](../../../frontend_user/app_pages/home_page.py) L159; [commands.py](../../../frontend_user/core/commands.py) L34 · Front |
| N07 · P1 | 탐정 조사·사망/처형·대화 이력·종료 복기 | snapshot private_events는 빈 배열이고 조회 시 공개 이벤트 이력을 복원하지 않는다. 탈락 원인은 해소 후 phase를 기록하며 result는 기본 승패·역할 위주다. Front도 조사 상세·득표수·개별 행동/발언 복기가 불완전하다. | [game_read_service.py](../../../backend/app/services/game/game_read_service.py) L108~170, L337; [result_service.py](../../../backend/app/services/game/result_service.py) L16~29; [game_page.py](../../../frontend_user/app_pages/game_page.py) L464, L566, L605; [result_page.py](../../../frontend_user/app_pages/result_page.py) L201~248 · Backend/Front |
| N08 · P1 | 무응답 fallback·관전 빠른 진행 | 의사 자동 보호 후보에 본인을 포함하며 자동투표는 숨겨진 역할로 비마피아를 우선한다. 빠른 진행은 선택 상태 저장 대신 즉시 전체 진행, enabled는 인간 사망 여부로 표시한다. 사망 뒤 worker 진행 경로 자체는 추가됐다. | [fallback.py](../../../backend/app/game_engine/fallback.py) L17~19, L39~43; [action_command.py](../../../backend/app/services/game/action_command.py) L484; [game_read_service.py](../../../backend/app/services/game/game_read_service.py) L325 · Backend |
| N09 · P1 | SSE 장애·백그라운드 복귀·같은 batch 재수신 | 단순 재연결은 추가됐으나 지속 polling·visibility 처리가 없고 reducer가 마지막 sequence/index 0을 재적용할 수 있다. schema_version 검사도 없다. Backend SSE `id:`도 없어 Front의 cursor 처리와 함께 검증해야 한다. | [sync/index.js](../../../frontend_user/components/browser_components/sync/index.js) L19~67; [sync.py](../../../frontend_user/core/sync.py) L51~61, L139; [game_router.py](../../../backend/app/routers/game_router.py) L154~178 · Front/Backend |
| N10 · P1 | UUID 복구·홈 목록·countdown·응답 유실 재시도 | UUID 교체는 session만 바꾸고 localStorage는 갱신하지 않는다. 홈 cache/완료 목록/탭·최대 두 카드 제한, 정적 countdown, 생성·시작·저장 결과 불명 요청의 key 보존 공백이 남았다. | [settings_page.py](../../../frontend_user/app_pages/settings_page.py) L35; [session.py](../../../frontend_user/core/session.py) L30; [home_page.py](../../../frontend_user/app_pages/home_page.py) L58~143; [action_panel.py](../../../frontend_user/components/action_panel.py) L451, L513; [game_page.py](../../../frontend_user/app_pages/game_page.py) L760 · Front |
| N11 · P1 | 일반 피드백·관리자 조작·생성 참가자 표시 | 일반 피드백 폼 진입 UI, 관리자 UUID 입력·필터·주소 전달, 실제 참가자 이름 연결이 남았다. 관리자는 README의 개발자 도구 UUID→allowlist 등록으로 수동 접근할 수 있으므로 접근 자체가 불가능한 것은 아니다. | [home_page.py](../../../frontend_user/app_pages/home_page.py) L75; [frontend_admin/app.py](../../../frontend_admin/app.py) L34~65; [creation_complete_page.py](../../../frontend_user/app_pages/creation_complete_page.py) L8~38 · Front |
| N12 · P1 | Prompt 기본 인자·MCP 행동 성공 검사 | Prompt 생략 인자를 빈 문자열 UUID query로 보내므로 실제 Backend 422가 예상된다. process 통합 테스트는 Tool 오류 문자열도 통과시켜 실제 행동 승인 증거가 부족하다. | [MCP prompt](../../../mcp_server/mafia_game/api/prompts/__init__.py) L14~19; [engine_http.py](../../../mcp_server/mafia_game/integrations/engine_http.py) L86~92; 삭제 전 `mcp_server/tests/test_process_backend_roundtrip.py` L170~193 기록 · MCP/Backend |
| N13 · P1 | migration 계정·암호화 설정 확인 | runner는 여전히 runtime effective DSN을 사용한다. keyring이 없으면 runtime은 legacy_plaintext를 선택한다. 테스트 전 전용 DB·DDL/DML 대상과 keyring 준비를 확인해야 하며 항상 암호화된다고 가정하면 안 된다. | [migrations.py](../../../backend/app/infrastructure/migrations.py) L38; [postgres_runtime.py](../../../backend/app/services/game/postgres_runtime.py) L58~62; [game_repository.py](../../../backend/app/repositories/game_repository.py) L54~63 · Backend/Data |

<a id="frontend-text-contrast"></a>

### N14 · P1 · Frontend 수정 요청: 검은 버튼·텍스트 영역의 글자 가독성

**등록일:** 2026-09-07 · **최초 상태:** 사용자 제보 접수, 미수정 (현재 반영 결과는 8절) · **담당:** Frontend

| 항목 | 전달 내용 |
|---|---|
| 사용자 제보 | 검은색 버튼과 텍스트 영역에서 글자가 보이지 않거나 읽기 어렵다. Frontend에서 해당 색상 조합을 수정하고 유사 영역도 확인한다. |
| 대표 위치 | 사용자 앱 `http://127.0.0.1:8501/` → 게임별 피드백 완료/이미 제출 안내 → **결과 화면으로** 버튼. [feedback_page.py](../../../frontend_user/app_pages/feedback_page.py)의 `_render_terminal` 참고. |
| 제공된 브라우저 근거 | `.st-key-feedback-terminal` 내부 버튼의 label `div`에 텍스트가 존재하며 `font-size: 16px`, `color: rgb(23, 32, 51)`(`#172033`)로 계산된다. 사용자는 버튼 배경이 검다고 보고했다. 첨부 정보에는 실제 버튼 배경색과 textarea의 computed style이 없어 색상 대비 수치·모든 발생 위치는 아직 확정하지 않았다. |
| 요소 식별 | `.st-key-feedback-terminal [data-testid="stButton"] button` 안의 **결과 화면으로** 텍스트. 생성된 `st-emotion-cache-*` 클래스보다 화면 key·testid·버튼 문구로 위치를 찾는다. |
| 원인 점검 후보 | [feedback_page.py](../../../frontend_user/app_pages/feedback_page.py)의 `--feedback-ink`가 label 색과 일치한다. terminal 컨테이너만 흰 배경이고 기본 버튼 자체의 배경·글자색 조합은 지정되지 않았다. [theme.py](../../../frontend_user/components/theme.py)의 공통 버튼·textarea 스타일, 페이지 CSS 상속, Streamlit 밝은/어두운 테마의 우선순위를 함께 확인한다. **원인 확정 전 점검 후보**다. |
| 수정 범위 | 검은 배경의 버튼 label과 텍스트/입력 영역에서 글자가 구별되도록 배경색·글자색을 함께 정리한다. 피드백 입력 textarea의 입력문자·placeholder·커서·label 및 같은 공통 스타일을 사용하는 다른 사용자 화면도 확인한다. |
| 완료 기준 | 밝은/어두운 테마에서 버튼의 기본·hover·focus·disabled 상태와 텍스트 영역의 일반·focus·disabled 상태를 직접 확인한다. 입력값·placeholder가 읽히고 focus가 구별되어야 한다. 피드백 성공/중복 안내와 **결과 화면으로** 이동 동작을 유지한다. |
| 검증 증거 | 수정 전후 같은 화면·테마의 캡처와 실제 버튼 배경/label, textarea 배경/글자 computed style을 남긴다. 사용자 제보 위치 외 유사 영역의 확인 결과도 기록한다. |

이번 추가 요청은 **수정 지시를 문서에 남기는 범위**로 처리했다. 첨부 DOM과 관련
스타일 코드·[화면 정본의 접근성 원칙](../04_frontend/AI_MAFIA_SCREEN_FLOW.md#18-접근성반응형)을
대조했으며 Frontend 코드 변경·브라우저 재현·자동 테스트는 수행하지 않았다.
아래 171개 통과 기록은 이전 환경 준비 결과이며 이 시각 결함의 해결 증거가 아니다.

## 3. 가상환경·의존성 준비 결과

| 환경 | 상태 | 확인 |
|---|---|---|
| 루트 `.venv` | 기존 Python 3.12.11 재사용, `uv sync --locked --dev` | merge 후 stale lock을 갱신하고 루트 dev에 Backend TestClient용 httpx2 추가. 75개 설치 패키지 호환 검사 통과 |
| `backend/.venv` | Python 3.12.11 생성, Backend requirements 설치 | 58개 패키지, pytest 8.4.2·pytest-asyncio 1.4.0·httpx2 2.12.0, 호환 검사 통과 |
| `frontend_user/.venv` | Python 3.12.11 생성, 사용자 requirements-dev 설치 | 39개 패키지, Streamlit 1.63.0·pytest 8.4.2, 호환 검사 통과 |
| `frontend_admin/.venv` | Python 3.12.11 생성, 관리자 requirements와 pytest 설치 | 39개 패키지, Streamlit 1.63.0·pytest 8.4.2, 호환 검사 통과 |
| `mcp_server/.venv` | 기존 Python 3.12.11 재사용, 독립 locked dev 설치 | 36개 패키지, MCP SDK 1.29.1, 호환 검사 통과 |
| macOS 터미널 | 로컬 `.vscode`의 zsh profile·router 준비 | 새 interactive terminal의 루트/Backend 시작, 모든 컴포넌트와 하위 폴더 이동, 루트 복귀 및 저장소 밖 해제 확인 |

루트와 MCP lock은 `uv lock --check`로 확인했다. requirements 기반 컴포넌트는 범위
설치이므로 루트 lock과 일부 패치 버전이 다르다. `.vscode/`·`.venv/`는 Git 제외
대상이며 기존 사용자 shell 설정을 먼저 읽는다. 새 VS Code 터미널에서 적용되고
외부 터미널에는 자동 적용되지 않는다. 설치·활성화 명령은 [README](../../../README.md)의
로컬 가상환경 절을 따른다.

## 4. 이번에 직접 실행한 테스트

| 범위 | 결과 | 실행 경계 |
|---|---|---|
| Backend | **128 passed** | 실제 DB 테스트 2파일 제외, synthetic DSN·dummy Provider, pytest-asyncio·AnyIO plugin 명시 |
| 사용자 Front | **34 passed** | fake HTTP/순수 함수/JS 소스 검사, 실제 브라우저 실행 아님 |
| 관리자 Front | **3 passed** | fake HTTP·응답 경계 검사 |
| MCP | **6 passed** | 4파일의 fake·MockTransport·ASGI 왕복, 실제 프로세스 DB 테스트 제외 |
| 합계 | **171 passed, 실패 0** | 외부 서비스 없는 선정 범위의 결과이며 전체 통합 회귀 결과는 아님 |

Backend의 과거 async plugin 미설치 상태는 해소했다. 각 범위는 해당 컴포넌트의
Python으로 한 번 실행했고, 전체 lint나 같은 테스트의 반복 실행은 하지 않았다.
실행 가능한 정확한 명령과 제외 파일은 [README 테스트 절](../../../README.md#테스트와-정적-검사)에 기록했다.

## 5. 실제 DB·브라우저 게임 테스트 준비 상태

현재 설정 파일을 값 노출 없이 점검한 결과 `.env`는 존재하고 설정 파싱은 성공했다.
**외부 TEAM_DATABASE_URL 우선 경로와 OpenAI Provider가 선택되어 있고 keyring은
설정되어 있지 않다.** 실제 주소·계정·비밀번호·API key는 출력하거나 문서에 복사하지
않았고 `.env`·실제 secrets는 변경하지 않았다. DB·Redis 연결, migration, Provider 호출은
실행하지 않았다.

| 다음 테스트 | 이번에 실행하지 않은 이유·필요한 준비 |
|---|---|
| `backend/tests/test_b5_game_api.py` | 이제 메모리 테스트가 아니다. 실제 DB에 쓰고 autouse cleanup에서 삭제한다. 전용 테스트 DB와 migration/seed 준비가 필요하다. |
| `backend/tests/test_postgres_game_flow.py` | 실제 PostgreSQL 쓰기·삭제와 Redis cleanup을 수행한다. 공유 게임 데이터와 분리한 DB·Redis 대상을 확인해야 한다. |
| `mcp_server/tests/test_process_backend_roundtrip.py` | 실제 Backend/MCP subprocess·DB 생성/삭제를 수행한다. 기존 환경과 worker가 활성화되므로 전용 DB 및 dummy Provider가 필요하다. MCP 독립 환경에는 Backend 의존성이 없어서 루트 환경·PYTHONPATH로 실행해야 한다. |
| 전체 게임 UI | 위 데이터 준비 후 Backend→MCP→사용자/관리자 Front 순으로 기동하고 생성·낮/밤·투표·저장/재개·관전·종료·feedback을 확인한다. N01/N02 정보 경계와 N04~N06 핵심 진행 문제를 먼저 해결해야 한다. |

실제 DB 테스트 세 파일에 자동 skip/opt-in guard가 없으므로 `pytest` 또는 MCP
`pytest tests`를 전체 실행하면 실제 환경에 접근할 수 있다. `TEAM_DATABASE_URL`은
`DATABASE_URL`보다 우선한다. 운영 DSN이 남은 상태에서 로컬 DATABASE_URL만 바꾸어
격리됐다고 판단하지 않는다. Provider는 우선 `dummy`로 검증하며 유료 호출은 이번
준비 범위에 포함하지 않았다.

## 6. 변경·검증 범위

- 변경: 루트 dev 의존성·lock, README, 본 점검표, 현재 코드 상태 문서, 로컬 가상환경과 `.vscode`.
- 확인: 171개 선정 테스트, 5개 환경 의존성 호환, 2개 lock 정합성, zsh 전환·설정 문법, 문서 링크·diff.
- 생략: 실제 DB/Redis 통합·migration·유료 Provider·브라우저 E2E, 기능 미변경에 따른 전체 lint.
- 게임 기능·DB·실제 비밀 설정을 변경하지 않았으며 커밋·푸시도 하지 않았다.

## 7. 2026-09-07 브라우저 실게임 1회 테스트와 수정 착수

이 절은 위의 과거 준비·정적 조사 기록과 구분되는 **실행 결과**다. 기준 commit은
`888ad7c`이며 시작 시 `README.md`에 서버 종료 기록 변경이 있었다. 해당 변경을 보존한다.

### 7.1 실행 환경과 완주 결과

- 09:42 KST에 Backend 8000, FastMCP 8100, 사용자 Front 8501, 관리자 Front 8502를 loopback으로 기동했다.
- Backend `/health`·`/ready`, 두 Front `/_stcore/health`가 HTTP 200이고 PostgreSQL·Redis가 정상이다. MCP SDK initialize와 Resource template·Prompt·Tool 목록 조회도 성공했다.
- 기존 `.env`·secrets·migration을 변경하지 않고 프로세스 환경에 `LLM_PROVIDER=dummy`, `MCP_SERVER_URL=http://127.0.0.1:8100`을 적용했다. 유료 LLM 호출은 없다.
- 기동 전 기존 진행 게임은 ROLE_REVEAL 1건이었다. 새 QA 게임과 생성 사실이 확인된 게임만 조회했으며 기존 데이터 삭제·정리는 하지 않았다.
- Orca 내장 브라우저에서 첫 생성 시도 후 탭이 닫혔다. 입력 이벤트 전달의 불확실성이 있어 **최종 플레이 증거는 전용 Chrome 탭의 실제 UI 조작**으로 확보했다. 앞선 8인 게임의 설정과 UUID 변화 원인은 제품 결함으로 단정하지 않는다.
- 완주 게임: `e3915109-2ad0-4883-b02a-cfae308be1a3`, **6인·폐관 직전의 박물관·인간 시민**.
- UI 순서: 생성 → 역할 공개 → 시작 → 첫날 발언 → AI 발언 → 첫 밤/둘째 날 → PASS → 플레이어 3 투표 → 인간 사망/관전 → 결과 → 게임별 피드백.
- 09:49:25 KST에 **COMPLETED / ENDED / round=2 / winner=MAFIA / MAFIA_PARITY**, 최종 생존 2명을 결과 화면과 Backend GET에서 각각 확인했다.
- QA 표시가 있는 synthetic 의견과 2점 평가를 입력해 피드백 제출 완료 안내를 확인했다.
- **완주 성공은 모든 게임 규칙·정보 격리·LLM 추론 품질의 통과를 의미하지 않는다.** 아래 결함을 동반한 1회 진행 결과다.

### 7.2 직접 관찰한 수정 필요·권고 사항

| ID / 우선순위 | 관찰·재현 | 영향과 조치 / WU | 상태 |
|---|---|---|---|
| E01 / P0 | 첫날 발언 성공 후 타임라인이 빈 안내로 돌아옴. 관전에서도 공개 기록 없음. 완료 GET의 `public_events=[]`. | 공개 발언·시작 안내를 DB event에서 소유자 snapshot에 복원하고 새 GET·재접속에도 유지. 비공개 행동 payload를 포함하지 않는다. **WU-B5** | 수정·재검증 완료 |
| E02 / P1 | Chrome에서도 생성 성공 뒤 설정 화면에 머물고 6명 선택을 다시 누르면 완료 화면으로 이동. | `game_create_page.py` 성공 terminal에서 navigation만 설정하고 rerun하지 않음. 성공 즉시 화면 전환. WU-F2 | 미수정 |
| E03 / P1 | 생성 완료에는 민수·철수 등 이름, 실제 역할/게임에는 플레이어 1~6. | `creation_complete_page.py`의 정적 `PLAYER_NAMES`를 실제 생성 snapshot의 참가자와 연결. WU-F2 | 미수정 |
| E04 / P1 | 첫 진입마다 SESSION_ONLY 경고. UUID 교체 후 설정의 scope와 홈의 disabled UUID/빈 목록이 일치하지 않음. 후속 게임 저장 후에도 홈은 빈 목록. | identity 초기 비동기 상태와 실제 저장소 오류를 구분하고 복구 시 localStorage·홈 cache·표시를 함께 갱신. WU-F1 | 미수정 |
| E05 / P1 | 인간 플레이어 1이 자기 자신을 투표 후보로 선택할 수 있게 표시됨. 실제 테스트 표는 플레이어 3에 정상 제출. | Backend `valid_targets`에서 자기 자신 제외. 엔진 거부와 UI 후보의 불일치 해소. WU-B5 | 미수정 |
| E06 / P1 | 밤 사망/투표 후 생존자 수는 바뀌지만 공개 결과 설명 없음. 결과 화면은 밤별·투표별 확정 기록 없음. | 확정 이벤트 생성·조회 및 결과 모델을 연결. E01만으로 미생성 NIGHT/VOTE 결과를 복원했다고 주장하지 않는다. WU-B7/B5 | 미수정 |
| E07 / P1 | 사망 직후 누르지 않은 빠른 진행이 켜짐·disabled이고 ‘켜졌습니다’ 안내 표시. | `fast_forward_enabled`를 인간 사망 여부로 대체하는 조회를 실제 저장 상태와 분리. WU-B5/F6 | 미수정 |
| E08 / P1 | 역할 공개의 파란 시작 버튼, 게임 저장 버튼, 피드백 완료의 검은 ‘결과 화면으로’ 버튼 글자가 어둡다. 성공 안내의 연두 글자도 낮은 대비. | 공통/페이지 CSS의 배경·글자색을 함께 정리. N14 제보 위치는 이번 Chrome 화면에서 재현. 밝은/어두운 테마와 상태별 검증 필요. Front 관련 WU로 분리 | 미수정 |
| E09 / P2 | 투표 카운트다운이 화면 rerun 시 갱신되며, 결과 완료 시간은 UTC 원문과 소수점이 그대로 표시됨. | 연속 countdown 및 KST 등 사용자 시간 표시. 화면 시간은 판정 권한을 갖지 않도록 유지. WU-F4/F6 | 권고 |
| E10 / P1 | 완료 결과의 새 게임 → 설정 → 만들기에서 이전 게임 ID의 생성 완료 화면으로 복귀. | `result_page.py`가 navigation만 바꾸고 기존 `game.create_pending=SUCCEEDED`를 비우지 않음. 새 생성 흐름 진입 시 이전 완료 상태 초기화. WU-F2 | 미수정 |

E01 추가 근거: 해당 QA 게임만 read-only로 집계했을 때 DB에는 `GAME_BEGAN` 1건,
`PLAYER_SPOKE` 1건, `PLAYER_PASSED` 13건이 존재했다. 기록 생성과 조회 누락을
구분했으며 `ACTION_RESOLVED` 5건은 공개 이력 복원 대상에 포함하지 않는다.

E04의 입력 거부는 Orca 자동화에서만 관찰되어 확정 결함으로 추가하지 않았다.
Chrome에서는 유효 UUID 입력·교체 확인이 동작했다. E08은 스크린샷 육안 재현이며
아직 모든 상태의 computed style·색 대비 수치를 측정한 것은 아니다.

### 7.3 정적 검토에서 남은 고위험 항목

Orca Run `run_c5a016c07955` / Task `task_603b89cb9855` /
Dispatch `ctx_a14a14254451`로 읽기 전용 검토를 별도 수행했다.

- **N01/N02 정보 격리**: MCP가 인간 snapshot을 AI context로 재사용하고 `ACTION_RESOLVED` PUBLIC payload에 개별 target을 넣는 경로. 이번 dummy 완주로 해결 여부를 증명하지 못한다.
- **N04 밤 제출 원장**: 인간 특수 역할 제출 후 AI batch가 전체 required actor와 맞지 않고, 만료 해소에서 저장된 밤 선택을 복원하지 않는 경로. 이번 인간은 시민이어서 해당 경로 미검증. WU-B3 후속 우선 후보다.
- **N04 무응답 투표**: 인간 표 없이 deadline 경과 시 AI 조회 조건과 만료 투표 worker 공백으로 정지 가능. 이번에는 정상 투표했으므로 실게임 재현 아님.
- **N05 판정**: 2인 마피아, 재투표 후보, 최종 지목 전원 집계는 별도 규칙 회귀가 필요. 이번 6인·2라운드 종료로는 검증하지 못했다.
- **N06 저장/재개**, 탐정 private 결과, GM narration 연결도 이번 플레이 범위 밖이다. 기존 표의 파일 근거를 후속 작업에 사용한다.

### 7.4 이번 수정 범위와 검증 계획

저장소의 세션당 WU 1개 규칙에 따라 **WU-B5의 E01 공개 대화 snapshot 복원**만
구현한다. 기존 파일 안에서 수정하고 공개 schema·DB migration·게임 규칙·Front CSS를
함께 변경하지 않는다. API 정본 6절의 PublicEvent allowlist를 기준으로 시작 안내·발언·
PASS 등 승인된 공개 기록만 복원하고, legacy 행동 대상·PRIVATE/PLAYER/INTERNAL
이벤트와 알 수 없는 필드는 노출하지 않는다.

구현 전후 fake 기반 focused test로 소유권·순서·재조회·공개 필드 경계를 검증하고,
완료 직전 외부 서비스 없는 기존 회귀 범위를 한 번 실행한다. 이후 같은 완료 게임의
GET과 브라우저를 다시 확인한다. 유료 Provider, 공유 DB 삭제를 포함하는 통합 테스트,
7~9인 전체 규칙 시뮬레이션은 이번 범위에서 생략한다. 최종 결과는 아래에 추가한다.


### 7.5 수정 완료와 최종 검증

**E01 수정 완료.** `game_read_service.py`에서 소유자 확인 후 동일 게임의 공개 이력을
복원하고 `event_repository.py`에서 snapshot 시점의 내부 sequence·Front sequence·
state version 상한 안의 `PUBLIC` / `APPEND_PUBLIC_EVENT` / schema 1 행을 읽는다.
API에 공개 가능한 필드만 새 object로 구성하고 순서·참가자 UUID·시각·값 범위를 검증한다.
비표준 `ACTION_RESOLVED`와 다른 audience·미승인 필드는 제외하며 500건에서 잘리지 않는다.
기존 파일 3개(위 두 파일과 `backend/tests/test_b3_infrastructure.py`)만 변경했다.

| 검증 | 결과 |
|---|---|
| 수정 전 fake 재현 | 빈 이력 반환과 이력 저장소 오류 미감지 경로를 새 테스트로 재현 |
| focused | infrastructure·repository 경계 87 passed, 마지막 제외 사례 보강 후 관련 34 passed. 서로 겹치는 범위로 합산하지 않음 |
| 수정 완료 후 회귀 1회 | **Backend 192 / 사용자 Front 34 / 관리자 Front 3 / MCP 6 = 235 passed, 실패 0** |
| 기존 완료 QA 게임 재조회 | 재기동 후 시작 안내 1 + 발언 1 + PASS 13 = **15건**, 두 번 GET에서 동일 순서·내용. 비표준 ACTION_RESOLVED와 target/role 필드 미포함 |
| Chrome 새 발언 검증 | 추가 부분 게임에서 시작 안내·인간 발언·AI PASS 5건이 화면 갱신과 다음 낮까지 유지됨 |
| 부분 게임 저장 후 재조회 | `e74f1ff4-25a0-4e02-8f3e-78c2b915af68`은 **SAVED / DAY_DISCUSSION**. 시작·발언·PASS 5·저장 안내 총 8건과 발언 본문 유지 |
| 문서·Git 점검 | README/보고서 링크와 diff 공백 검사 통과. 새 파일·디렉터리 없음. 커밋·푸시 없음 |

구현은 Orca Task `task_c066556e8ef1` / Dispatch `ctx_eb9d535765c4`로 수행했다.
완료 보고를 수신하고 작업자 종료를 확인했다. 최초 읽기 전용 작업자의 release는
Orca가 `user_takeover`로 유지 처리해 강제로 닫지 않았다. 네 서버는 실행 상태로 남긴다.

검증 한계: 이번에는 게임 1회 완주 뒤 대화 복원만 부분 재검증했다. 브라우저 전체
새로고침은 기존 UUID 지속성/홈 cache 문제와 분리되지 않아, 수정 후에는 SSE에 따른
화면 재렌더·Backend 재조회·저장 후 조회로 이력 유지를 확인했다. E02~E10은 수정하지
않았다. 미생성 밤·투표 결과와 private 결과, 기존 sync의 N02 정보 노출 경로도 남아 있다.
`VOTE_RESOLVED`는 정본의 `tied` 세부 타입이 불명확하고 실제 생성 경로가 없어 이번
snapshot 복원에서는 제외했다. 후속 확정 이벤트 구현 시 계약과 함께 연결해야 한다.

생략한 검증: 실제 DB 삭제/cleanup을 수행하는 통합 테스트 3파일, 유료 Provider,
7~9인·모든 역할·무응답 마감·최종 지목 전체 시뮬레이션, 전체 lint. 현재 WU-B5 수정에는
fake 회귀와 명시적으로 생성한 QA 게임의 수동 검증을 적용했고 공유 데이터 삭제는
필요하지 않았다. 실제 `.env`·secrets·DB schema는 변경하지 않았다.

## 8. 수정·권고 반영과 AI 진행 표시

사용자의 후속 요청으로 E02~E10과 N01~N14의 관련 구현을 작업 단위별로 나누어
반영한다. Orca Run `run_31def9b852c8`에서 새 작업자 세션마다 WU 하나만 할당하고
조정자가 정본·README·보고서와 통합 검증을 담당한다. 커밋·푸시는 하지 않는다.

### 8.1 확정한 표시·로그 경계

AI 진행은 공개 발언의 정보 확인·판단·행동 선택·적용 상태와 고정된 짧은 설명으로
표시한다. 모델 내부 추론 원문을 표시하거나 저장하지 않는다. 밤·투표는 공통 비공개
단계 안내를 사용하며 역할·대상·밤 actor의 응답 여부를 노출하지 않는다. 터미널과
순환 로그 파일에는 같은 순서 번호와 서버 실행 ID를 사용하고 성공 적용은 DB 성공
반환 뒤 기록한다. 자세한 계약은 API 2.4.1절과 마스터 1.3.1절에 추가했다.

### 8.2 작업별 검증 기록

| 작업 | 현재 확인한 결과 |
|---|---|
| F1 UUID 초기화·복구 | 초기 None을 저장소 실패로 오해한 경로, localStorage 복구 미반영, home.* 잔존 수정. 실제 Chrome에서 UUID 교체 후 홈 식별자·목록 갱신과 새로고침 지속성 확인. 30초 cache 만료 시 첫 클릭 유실을 AppTest로 재현·수정하고 후속 focused 26개 통과. 18501 실브라우저에서도 30초 이상 대기 후 첫 새 게임 클릭 성공. 후속 카드 첫 클릭 유실도 재현해 기존 카드 렌더 후 cache 갱신으로 수정하고 F1/F2 focused 67개 통과. |
| F2 생성·홈 목록 | E02/E03/E10 수정. 실제 이름 표시, 같은 요청 재시도, 최신 목록·일반 피드백 진입 관련 29개 통과. |
| F3 게임 화면·재개·대비 | 공개 AI별 현재/이전 단계, 접힌 50개 이력, 정확한 더미 표시, 비공개 단계 안내 추가. SAVED 재개와 시작/저장/재개 동일 요청 재시도·snapshot 복구, 공통 대비 수정. 초기 focused 54개, 조사 표시·거부 경계 포함 최종 F3 focused 140개 통과. 18501에서 저장→홈→재개 후 같은 낮·공개 이력 복원 확인. 같은 tick의 sync SNAPSHOT이 AI 기록을 지우던 경로를 GET 보강으로 수정하고 추가 게임에서 각 AI의 이전 처리와 접힌 5단계 이력 유지 확인. |
| F4 행동·countdown | 자기투표·사망자·잘못된 UUID·다른 게임 후보 방어, 서버 valid_targets 우선, 서버 시각 기준 1초 fragment·저장 동결·만료 잠금·동일 요청 재시도 보존. focused 47개 통과. 실제 투표 화면에서 본인 제외 후보 7명과 15초 이하 경고 확인. |
| F5 동기화 | schema/cursor/index·중복·gap 검증, 지속 polling·visibility 복귀·연결 실패 backoff·cleanup·AI 진행 tick 연결. Node mock-fetch 포함 focused 26개 통과. |
| F6 종료 복기 | 초 단위 KST 시간, 종료 후 새 게임 초기화, 실제 공격·조사·개별 투표·자동 선택과 result ID로 승인된 공개 timeline 복원. focused 38개 통과. 공개 result에 없는 최종 지목 대상은 추정하지 않음. 후속 결과 요약은 마지막 투표의 round/phase만 표시하고 기록 없음을 명시해 밤 종료 원인처럼 보이지 않게 수정(focused 39개). |
| F8 관리자 | UUID 입력·저장 ACK·403 복구, 실제 status/phase 필터와 game_id 상세 주소. 관리자 전체 18개 통과(fake HTTP/AppTest/Node). 기존 allowlist 유지. |
| B2 migration 설정 | 전용 DDL DSN 필수·runtime과 DB 경로 비교·query 우회 거부·repr/오류 원문 차단. 최종 설정 focused 73개 통과, 일반 runtime의 DDL 환경키 미조회·전용 migration loader 경계 포함. 격리 DB에서 기존 migration 4개 재실행 성공. 실제 운영 계정/권한·keyring 준비는 변경하지 않음. |
| B4 순수 규칙 | 마피아 전원 참여·동률 재투표·최종 전원 집계·역할을 보지 않는 자동투표·둘째 날 이후 추가 순환·5번째 밤 경계·빠른 진행 선택 보존 관련 50개 통과. |
| B5 행동·조회·원장 | 자기투표 후보 제외, 인간/AI 혼합 밤 제출 복원, 서버 마감 검사·만료 해소, 확정 공개/개인 이벤트, 종료 nights/votes, 실제 빠른 진행 bool 수정. mock 151개와 격리 PostgreSQL 10개 통과. |
| B7 actor context·sync | 실제 window와 AI 본인의 역할·단서·persona·조사만 scope별로 반환. 불완전/위험한 sync batch는 snapshot으로 복원하고 SSE에 Front sequence ID 사용. 서비스가 규칙 후보를 전달해 Agent→Engine 직접 의존을 제거. 후속 포함 focused 78개 통과. |
| B6 AI 진행·로그 | 단계별 고정 요약·순차 JSON 터미널/회전 파일·postcommit 적용, scoped MCP와 Tool 응답 검사, 만료 투표 worker 연결. focused 48개 통과. rollback 후 동일 미제출 job의 저장 proposal 재사용을 보완하고 후속 40개(격리 SQL 8개 포함) 통과. 실제 UTC +00:00 projection을 거부하던 client parser도 수정해 focused 47개 통과. 서버 재시작 후 실게임에서 정상 CONTEXT_READY/DECIDING/DECIDED/APPLIED 순서 확인. |
| M3 scoped adapter | actor별 URI·scope 전달, 빈 Prompt UUID 생략, 명시적 Tool 승인·process 성공 검사 보완. 실게임에서 발견한 Resource MIME 불일치는 application/json 명시로 수정. 최소 FastMCP 전체 5파일을 격리 DB의 실제 process 테스트까지 포함해 최종 **44 passed**. |
| B9 규칙 시뮬레이션 | 기존 harness를 전원 밤·재투표 후보·최종 전원 제출에 맞춰 갱신. focused 17개 및 6~9명 각각 100판, 총 400판 완주. 마피아 승률 62/54/68/69%, 최종 지목은 9인 4판. 단순 heuristic 결과로 실제 LLM·시나리오별 균형을 의미하지 않으며 60% 초과 구성은 후속 균형 검토 대상으로 유지. |
| 통합 환경 | 기존 데이터와 분리한 loopback 임시 PostgreSQL에 migration 4개 적용. Backend 510개·MCP 44개 전체 회귀와 8인 브라우저 완주 실행. |

이 절의 작업별 수는 각 작업자의 focused 결과이며 서로 중복될 수 있으므로 단순
합산하지 않는다. 최종 전체 회귀는 아래에 별도로 기록한다.

### 현재 항목별 판정

| 최초 항목 | 현재 반영 |
|---|---|
| N01/N02/N03/N12 | actor scope·개인 이벤트·Resource/Tool 승인·Prompt 기본값 수정 |
| N04/N05/N08 | deadline·전원 제출·재투표·최종 집계·자동 선택·빠른 진행 상태 수정 |
| N06/N09/N10 | 저장/재개·sync 복구·UUID·홈 TTL·countdown·같은 요청 재시도 수정 |
| N07/E01/E06 | 공개/개인 이력과 결과 원장 연결. 탐정의 canonical 조사 결과 표시·저장 재개 후 유지 확인 |
| N11/E02/E03/E10 | 일반 피드백·관리자 입력/필터·실제 참가자·새 게임 초기화 수정 |
| N13 | 전용 DDL loader와 대상 검사 수정. 실제 계정/권한·keyring 준비는 운영 확인 필요 |
| E04/E05/E07 | UUID 영속 복구·본인 제외 투표와 사망 후 꺼진 빠른 진행의 직접 활성화·완주 확인 |
| N14/E08/E09 | 버튼/입력 대비·실시간 countdown·결과 KST 반영. 테마별 검증 기록 아래 참조 |

### 8.3 수정 후 실게임·로그 검증

- 환경: 합성 자격증명의 임시 로컬 PostgreSQL(55432), 기존 로컬 Redis 15번 DB,
  Backend 18000, MCP 18100, 사용자 Front 18501. 실제 환경 파일·키·운영 계정과 schema는 변경하지 않았다. 기존 8000/8100 서버는
  기존 DB 설정과 dummy Provider로 수정 코드를 재기동했으며 대량 테스트는 격리 DB에서만 수행했다.
- 8인 게임 `197a3251-37d7-4adf-b2e4-27963be07dc7`: 인간 시민의 발언, 저장→홈→재개,
  둘째 날 추가 발언 순환, 본인을 제외한 7명 중 투표, 인간 처형 후 관전, 5번째 밤과
  낮 6일차 최종 지목까지 진행. `COMPLETED`/`ENDED`, 라운드 5, 최종 지목 실패로
  마피아 승리. 결과에는 참가자 8명·밤 5건·투표 5건·공개 이벤트 83건이 존재한다.
- 추가 6인 게임에서도 인간 투표→처형 뒤 빠른 진행 스위치가 처음에는 꺼져 있고
  조작 가능함을 확인했다. 직접 켠 뒤 Backend `fast_forward_enabled=true`와 정상 종료를
  확인했다(밤 4, 마피아/시민 동수, 11:06:24 KST). 관전에서도 본인의 조사 기록은 유지됐다.
  결과 재조회에서 “마지막 투표: 라운드 3 · 낮 투표”와 실제 종료 이유가 분리되어 표시됨을 확인했다.
- 결과 KST 시각과 이름별 복기, 피드백 제출 성공 및 결과 화면 복귀를 확인했다.
  결과의 새 게임에서 별도 6인 게임 `66aeb94b-f66a-45bc-b94c-a282cdf9272b`가 생성되어
  이전 완료 ID로 돌아가던 E10이 재현되지 않았다. 추가 게임의 인간 탐정으로 밤 조사를
  제출해 본인 영역의 “밤 1 조사 결과 · 플레이어 2: 마피아가 아닙니다.”와 저장·재개 후
  유지도 확인했다. 초기 제목만 표시된 문제는 canonical private event 파싱으로 수정했다.
- 초기 MIME/UTC 결함은 이 게임 도중 발견·수정했다. 수정 후 Backend 실행
  `36158811-a35d-449e-adc0-6eb257ac57d7`에서는 518개 로그의 sequence가 단조 증가하고,
  AI 89회 각각 STARTED/CONTEXT_READY/DECIDING/DECIDED/APPLIED가 기록됐다.
  해당 실행에는 FALLBACK/FAILED가 없었다. 터미널에서 읽을 수 있었던 최근 JSON 58개는
  로그 파일의 같은 항목과 모두 일치했다. 터미널 스크롤 범위를 넘어선 전체 518개의
  동일성까지 별도로 주장하지 않는다.
- 밤·투표 로그의 player_id/action은 null이며 원문 prompt·private context·모델 사고는
  기록하지 않는다. dummy 동작은 고정 행동으로 명시한다. 파일 시각은 UTC, 결과 UI는 KST다.
- 제보된 피드백 완료 버튼: 실제 배경 `rgb(255,255,255)`, 버튼/label 글자
  `rgb(21,34,56)`. 입력창도 같은 배경/글자이고 placeholder는 `rgb(88,104,128)`,
  focus는 파란 3px 테두리로 확인했다. `--theme.base dark`와 `light` 각각에서 저장·PASS·
  입력창은 같은 색상이고 disabled 발언 버튼은 배경 `rgb(229,234,242)`, 글자
  `rgb(83,97,121)`로 구별된다. 모든 hover 조합을 브라우저에서 전수 확인하지는 않았다.
- 관리자 18502에서 UUID 입력→확인→브라우저 저장→Backend 403 거부와 식별자 교체/
  재시도 UI를 확인했다. 실제 관리자 등록은 하지 않았다. 허용된 관리자 목록·필터는
  fake HTTP/AppTest로 검증했으며 실제 allowlist 계정의 브라우저 확인과 구분한다.

### 8.4 최종 회귀와 남은 검증 범위

네 컴포넌트의 최종 전체 회귀는 **총 903개 통과, 실패 0**이다.

| 범위 | 결과 | 조건 |
|---|---|---|
| Backend 전체 | **510 passed** | 격리 DB 실제 SQL 및 B6 opt-in 8개 포함. 최초 2개 낡은 window fake를 수정 후 재검증 |
| MCP 전체 | **44 passed** | 5파일, 실제 Backend/FastMCP process와 Tool 승인 포함 |
| 관리자 Front 전체 | **18 passed** | fake HTTP·AppTest·Node 저장소 mock |
| 사용자 Front 전체 | **331 passed** | F1/F3 실브라우저 후속·조사 표시 포함. 낡은 sync fixture/source 검사 2개 정합성 보완 후 재검증 |

실제 유료/Local Provider의 추론 품질, 시나리오별 장기 밸런스, 운영 DDL 계정·권한,
기존 데이터 암호화 전환과 운영 TLS는 실행하지 않았다. keyring 두 설정이 없으면
legacy 평문 경로가 유지되며 예제 placeholder가 암호화를 준비해 주지는 않는다.
전체 lint는 변경 위험도에 따라 생략했고 기존 config 긴 줄 Ruff 경고 1개는 남겼다.

최종 지목의 개별 표와 득표수는 복기할 수 있지만, 원장의 final_target_player_id는
현재 공개 result 계약에 없으므로 확정 지목 대상을 UI가 추정하지 않는다. 이를 직접
표시하는 계약 확장과 heuristic에서 마피아 승률 60%를 넘은 인원의 균형 조정은 후속
권고로 남긴다. 기존 게임에 없는 상세 원장은 만들어내지 않고 빈 기록으로 안내한다.

최종 기동 확인: 8000/18000 Backend `/ready`, 8501/8502/18501/18502 Front health는
모두 HTTP 200이며 8100/18100 MCP가 LISTEN 중이다. 마지막 확인 중 종료된 서버
프로세스들을 재기동했고 격리 DB의 완료 게임 두 개와 결과 화면이 복원됨을 확인했다.
AI 표시용 메모리는 재기동으로 비워지고 이후 새 처리부터 쌓이며 기존 파일 로그와
DB 이력은 보존된다. Orca 작업 28개가 완료됐고 작업자 터미널을 해제했다.
커밋·푸시는 수행하지 않았다. 최종 diff 공백 검사와 실제 환경 파일/키 미포함을 확인했다.
