# AI 마피아 개발 문서 안내

이 디렉터리는 AI 마피아의 제품 정본, 섹터별 설계, 구현·검증 보고서와 과거 자료를
한곳에서 관리한다. 문서의 우선순위는 `01_core`의 공통 정본, 섹터별 설계, 최신 보고서,
변경 기록, 과거 자료 순이다.

## 권장 읽기 순서

1. [공통 마스터플랜](01_core/AI_MAFIA_MASTER_PLAN.md)
2. [섹터 공통 형식 계약](01_core/AI_MAFIA_INDEPENDENT_CONTRACT.md)
3. [공개·내부·MCP API 명세](01_core/AI_MAFIA_API_SPEC.md)
4. 담당 섹터의 설계 문서
5. [현재 코드 상태](05_reports/AI_MAFIA_CURRENT_CODE_STATUS.md)와 관련 보고서

## 카테고리

### 01_core — 제품·공통 계약 정본

| 문서 | 역할 |
| --- | --- |
| [AI_MAFIA_MASTER_PLAN.md](01_core/AI_MAFIA_MASTER_PLAN.md) | 제품 규칙, 시나리오, 소유권, 작업 단위와 체크포인트 |
| [AI_MAFIA_INDEPENDENT_CONTRACT.md](01_core/AI_MAFIA_INDEPENDENT_CONTRACT.md) | Frontend·Backend·MCP 섹터 간 공통 형식과 경계 |
| [AI_MAFIA_API_SPEC.md](01_core/AI_MAFIA_API_SPEC.md) | 공개·관리자·내부 Engine API와 MCP 계약 |

### 02_backend_data — Backend·데이터·게임 엔진

| 문서 | 역할 |
| --- | --- |
| [AI_MAFIA_BACKEND_PLAN.md](02_backend_data/AI_MAFIA_BACKEND_PLAN.md) | Backend 구현 순서와 완료 기준 |
| [AI_MAFIA_DB_DESIGN.md](02_backend_data/AI_MAFIA_DB_DESIGN.md) | PostgreSQL·Redis·transaction·migration 정본 |
| [AI_MAFIA_GAME_ENGINE_STRATEGY_DRAFT.md](02_backend_data/AI_MAFIA_GAME_ENGINE_STRATEGY_DRAFT.md) | 게임 엔진과 Agent Manager 모듈화 초안 |

### 03_mcp_agent — MCP·Agent

| 문서 | 역할 |
| --- | --- |
| [AI_MAFIA_MCP_SERVER_DESIGN.md](03_mcp_agent/AI_MAFIA_MCP_SERVER_DESIGN.md) | MCP runtime, Tool·Resource, 보안과 실행 설계 |
| [AI_MAFIA_AGENT_ARCHITECTURE_DESIGN.md](03_mcp_agent/AI_MAFIA_AGENT_ARCHITECTURE_DESIGN.md) | Agent profile, runtime loop와 상태 설계 |

### 04_frontend — 화면·Frontend 연동

| 문서 | 역할 |
| --- | --- |
| [AI_MAFIA_SCREEN_FLOW.md](04_frontend/AI_MAFIA_SCREEN_FLOW.md) | 사용자·관리자 화면과 상태 전이 정본 |
| [AI_MAFIA_FRONTEND_TECHNICAL_DESIGN.md](04_frontend/AI_MAFIA_FRONTEND_TECHNICAL_DESIGN.md) | Streamlit Frontend 기술 설계와 WU-F1~F10 계획 |
| [AI_MAFIA_FRONTEND_BACKEND_HANDOFF.md](04_frontend/AI_MAFIA_FRONTEND_BACKEND_HANDOFF.md) | 공개 API·SSE·CORS·오류 처리 인계 계약 |

루트에 중복으로 있던 두 Frontend 문서는 이 카테고리의 최신본으로 통합했다.

### 05_reports — 구현 현황·검증 보고서

| 문서 | 역할 |
| --- | --- |
| [AI_MAFIA_CURRENT_CODE_STATUS.md](05_reports/AI_MAFIA_CURRENT_CODE_STATUS.md) | 현재 구현 구조와 알려진 제약 |
| [AI_MAFIA_CUSTOM_ROLE_MCP_TOOLS_SUMMARY.md](05_reports/AI_MAFIA_CUSTOM_ROLE_MCP_TOOLS_SUMMARY.md) | 사용자 전용 MCP Tool 구현·적용 준비 요약 |
| [AI_MAFIA_GAME_RUN_LOG_20260908.md](05_reports/AI_MAFIA_GAME_RUN_LOG_20260908.md) | 실제 게임 실행 로그 보고서 |
| [AI_MAFIA_GAME_TEST_GAP_REPORT.md](05_reports/AI_MAFIA_GAME_TEST_GAP_REPORT.md) | 게임 검증 공백과 준비 상태 |
| [AI_MAFIA_PARALLEL_VOTE_BUG_REPORT.md](05_reports/AI_MAFIA_PARALLEL_VOTE_BUG_REPORT.md) | 자동·병렬 투표 문제 해결 기록 |
| [AI_MAFIA_UI_UX_PLAYTEST_REPORT.md](05_reports/AI_MAFIA_UI_UX_PLAYTEST_REPORT.md) | 실제 게임 UI·UX 점검 결과 |

### 90_history — 날짜별 변경 기록

[변경 기록 안내](90_history/README.md)와 날짜별 구현·검증 기록을 보관한다. 현재 계약을
판단할 때는 먼저 `01_core`과 담당 섹터 설계를 확인한다.

### 99_archive — 과거 임시 자료

[과거 자료 안내](99_archive/README.md)에 명시된 특정 시점의 구조도·검토 문서다. 삭제된
구현 경로나 과거 계약을 포함할 수 있으므로 현재 정본으로 사용하지 않는다.

## 문서 관리 규칙

- 공통 제품·API 계약은 `01_core`에서만 정의한다.
- 섹터 문서는 공통 정본을 참조하고 같은 schema를 중복 정의하지 않는다.
- 실행 결과와 조사 기록은 `05_reports`, 날짜별 변경 내역은 `90_history`에 둔다.
- 더 이상 현재 구현을 설명하지 않는 자료는 `99_archive`로 이동하고 사유를 표시한다.
- 파일을 이동하거나 카테고리를 추가하면 이 문서, 루트 `README.md`, `AGENTS.MD`와
  관련 상대 링크를 함께 갱신한다.
