# AI 마피아 프로젝트 수행과정 보고서

## 1. 보고서 개요

이 문서는 AI 마피아 프로젝트가 문제 정의와 MVP 범위 설정에서 출발하여 게임 엔진 구현, Agent·MCP 연동, 오류 개선, 실제 게임 검증과 문서화까지 진행된 과정을 정리한다.

이 보고서는 기능 목록을 나열하는 문서가 아니라, 주요 의사결정과 구현 상태의 변화를 코드·커밋·테스트 근거와 연결하는 것을 목적으로 한다.

### 1.1 기준 정보

| 항목 | 내용 |
|---|---|
| 프로젝트 | AI 마피아 |
| 저장소 | `C:\\phase2\\Team4_Proj_0831` |
| 주요 개발 브랜치 | `ik-2` |
| 문서 기준 시점 | 2026-09-09 |
| 문서화 기준 커밋 | `31593b6` |
| 기준 상태 | 커밋된 구현과 현재 작업 중인 arrangement 문서를 구분하여 기록 |

`31593b6` 이후의 arrangement 문서 수정은 최종 발표본에 반영할 때 별도의 최종 기준 커밋으로 갱신한다.

## 2. 프로젝트 수행의 전체 흐름

프로젝트는 다음 순서로 진행되었다.

```text
문제와 MVP 범위 정의
        ↓
게임 엔진과 기본 사용자 흐름 구현
        ↓
Agent 책임 경계와 실행 구조 설계
        ↓
Actor Context·MCP·Tool 연동
        ↓
Prompt·Persona·관리자 관찰성 개선
        ↓
실제 게임에서 오류 발견 및 수정
        ↓
커스텀 역할·Tool capability 확장
        ↓
전체 시스템 통합 실행과 문서화
```

이 흐름에서 중요한 원칙은 게임 규칙과 최종 상태 변경을 Backend Game Engine이 책임지고, Agent는 허용된 정보와 Tool을 기반으로 행동을 제안하도록 분리한 것이다.

## 3. 주요 상태 전환 요약

| 단계 | 기준 커밋 | 상태 변화 | 주요 근거 |
|---|---|---|---|
| 1. MVP 기반 구축 | `c077c43` | 게임의 핵심 기능과 최소 실행 범위 마련 | `backend/app/game_engine/`, `frontend_user/` |
| 2. 게임 흐름 완성 | `b29fb6b` | 생성부터 결과까지의 게임 lifecycle 연결 | 게임 흐름 테스트, PostgreSQL smoke 검증 |
| 3. Agent 구조 정리 | `a644aa6` | Agent 아키텍처와 책임 경계 구체화 | Agent 설계 문서, Agent 관련 모듈 |
| 4. Context·Orchestrator 연동 | `766f5c8` | Actor별 Context와 Agent 실행 경로 연결 | `orchestrator.py`, `projections.py`, MCP client |
| 5. Prompt·Persona·관찰성 개선 | `e50abd9`, `54e0693` | AI 행동 품질과 관리자 확인 가능성 개선 | Prompt·Persona, Agent activity, 관리자 API |
| 6. 실제 오류 개선 | 관련 수정 커밋 및 버그 보고서 | 병렬 투표·재개·동시성·UI 문제 수정 | 게임 테스트 및 플레이테스트 보고서 |
| 7. 역할·Tool 확장 | `de00426` | 커스텀 역할과 역할별 Tool capability 지원 | migration, MCP registry, custom role test |
| 8. 설계 문서 정리 | `31593b6` | 기획·설계·구현 계획 문서 체계화 | `docs/arrangement/` |

커밋 메시지가 짧거나 병합 커밋인 경우에는 커밋 제목만으로 성과를 판단하지 않고, 변경 파일·테스트·실행 결과를 함께 근거로 사용한다.

## 4. 단계별 수행 과정

### 4.1 문제 정의와 MVP 범위 설정

#### 출발점

사람이 충분히 모이지 않아도 소셜 디덕션 게임을 진행할 수 있고, AI 플레이어가 제한된 정보 안에서 발언과 행동을 수행하도록 하는 것을 프로젝트 목표로 설정했다.

#### 주요 결정

- 게임 규칙과 승패는 AI가 아니라 Backend Game Engine이 결정한다.
- AI는 인간과 동일한 게임 규칙 검증 경계를 통과한다.
- MVP에서는 핵심 게임 lifecycle과 Agent 실행 경계를 우선한다.
- 확장 기능은 기본 게임 흐름과 검증 기반이 마련된 뒤 추가한다.

#### 관련 문서

- [AI 마피아 프로젝트 기획서](00_AI_MAFIA_PROJECT_PROPOSAL.md)
- [AI 마피아 구현 계획서](AI_MAFIA_IMPLEMENTATION_PLAN.md)
- [게임 엔진·시나리오 설계서](04_GAME_ENGINE_SCENARIO_DESIGN.md)

### 4.2 게임 엔진과 기본 사용자 흐름 구현

#### 목표

Agent를 연결하기 전에 게임 상태 전이와 사용자 게임 흐름을 검증할 수 있는 최소 실행 기반을 구축했다.

#### 구현 내용

- 게임 생성과 참가자 구성
- 역할 공개
- 낮 토론과 발언
- 밤 행동
- 투표와 재투표
- 승패 판정
- 결과 화면
- 저장 후 재개와 종료 흐름

#### 근거

- 기준 커밋: `c077c43`, `b29fb6b`
- 코드: `backend/app/game_engine/`, `backend/app/services/game/`, `frontend_user/app_pages/`
- 검증: 게임 lifecycle 테스트, PostgreSQL smoke test, 실제 게임 완주 확인

#### 의미

이 단계에서 게임 규칙과 상태 전이를 Backend가 소유하도록 하여, 이후 Agent의 판단 결과가 실제 게임 규칙을 우회하지 않도록 기반을 마련했다.

### 4.3 Agent 책임 경계와 아키텍처 정립

#### 문제

AI가 게임 상태나 승패를 직접 결정하게 되면 모델 출력 오류가 곧 게임 데이터 오류로 이어질 수 있고, AI에게 다른 플레이어의 비공개 정보가 전달될 위험이 있었다.

#### 주요 결정

- Agent는 게임 DB를 직접 변경하지 않는다.
- Agent는 Actor별로 필터링된 Context만 받는다.
- Agent는 허용된 행동을 구조화된 제안으로 반환한다.
- Backend와 Game Engine이 권한, 차례, 대상, 상태 버전을 최종 검증한다.

#### 근거

- 기준 커밋: `a644aa6`, `766f5c8`
- 코드: `backend/app/agent/orchestrator.py`, `backend/app/agent/projections.py`, `backend/app/mcp/client.py`
- 설계: [에이전트 아키텍처 설계서](06_AGENT_ARCHITECTURE_DESIGN.md)

#### 최종 실행 흐름

```text
현재 게임 상태 조회
→ Actor별 Context Projection
→ Agent 판단
→ 허용된 Tool 선택
→ 행동 제안 생성
→ Backend 검증
→ Game Engine 반영
```

이 구조는 여러 AI 플레이어가 존재하더라도 각 AI가 독립적으로 게임 상태를 변경하는 멀티 에이전트 구조가 아니라, 하나의 공통 Agent Workflow를 Actor별 Context에 반복 적용하는 구조로 정의한다.

### 4.4 Context·MCP·Tool 연동

#### 목표

Agent가 단순히 자연어를 생성하는 것을 넘어, 현재 차례와 권한에 따라 사용할 수 있는 행동을 판단하도록 했다.

#### 구현 내용

- 공개 정보와 Actor 개인 정보 분리
- 현재 action window와 허용 행동 확인
- MCP Resource 기반 Context 조회
- 발언·투표·PASS 등 행동 제안 경로 연결
- Tool 결과와 제출 파라미터 검증
- 잘못된 행동과 오래된 상태 버전 차단

#### 근거

- `backend/app/agent/projections.py`
- `backend/app/agent/orchestrator.py`
- `backend/app/routers/mcp_registry_router.py`
- `mcp_server/mafia_game/api/tools/registry.py`
- [API 설계서](02_API_DESIGN.md)
- [MCP 설계서](03_MCP_DESIGN.md)

#### 의미

Agent의 능력을 모델의 자연어 출력에만 의존하지 않고, Context와 Tool capability라는 시스템 경계로 제한했다. 이로써 모델이 잘못 판단하더라도 Backend가 최종 방어선으로 동작할 수 있게 했다.

### 4.5 Prompt·Persona·관리자 관찰성 개선

#### 문제

기본 Agent 경로가 동작한 뒤에는 AI의 발언과 행동이 게임의 역할·성향에 맞는지 확인하고, 운영 중 발생한 Agent 실행 상태를 관찰할 필요가 있었다.

#### 개선 내용

- Prompt와 Persona의 표현·행동 성향 조정
- Agent 실행 활동과 상태 기록 보강
- 관리자 화면에 Agent 관련 지표 추가
- 실제 AI 처리 진행을 확인할 수 있는 표시 개선

#### 근거

- 기준 커밋: `e50abd9`, `54e0693`
- 코드: `backend/app/agent/orchestrator.py`, `backend/app/routers/admin_router.py`, `backend/app/services/admin_service.py`
- 관련 문서: `docs/fix/2026-09-08-persona-and-prompts.md`

#### 의미

Agent 품질 개선을 Prompt 변경만으로 설명하지 않고, 실행 활동과 결과를 관찰하고 비교할 수 있는 평가 기반으로 확장했다.

### 4.6 실제 오류 발견과 개선

실제 실행과 통합 과정에서 발견한 문제는 기능 추가와 분리하여 개선 과정으로 기록했다.

#### 주요 사례

| 문제 | 원인 또는 위험 | 개선 방향 | 검증 |
|---|---|---|---|
| AI 병렬 투표 처리 | 개별 제출과 전체 집계의 상태 관리 불일치 | 모든 유효 표 수집 후 해소, 상태 버전 검증 | 병렬 투표·재투표 테스트 |
| AI Context 정보 혼입 가능성 | Actor별 projection 경계가 중요함 | 공개·본인·차례·Persona Context 분리 | Actor context test |
| 저장 후 재개 | 진행 중 window와 제출 원장 복원 필요 | PostgreSQL 원장과 snapshot 기반 복원 | 저장·재개 smoke test |
| Tool 또는 Provider 실패 | 외부 호출 실패가 게임 진행을 멈출 수 있음 | retry 상한, fallback, 안전한 종료 | Agent focused test |
| UI 진행 상태 혼동 | 실제 처리 상태와 화면 표시 차이 | Agent activity와 Front sync 보완 | 브라우저 실게임 확인 |

#### 관련 근거

- [병렬 투표 버그 보고서](../AI_MAFIA_PARALLEL_VOTE_BUG_REPORT.md)
- [게임 테스트 공백 보고서](../AI_MAFIA_GAME_TEST_GAP_REPORT.md)
- [UI·UX 플레이테스트 보고서](../AI_MAFIA_UI_UX_PLAYTEST_REPORT.md)

#### 개선 과정의 공통 패턴

```text
문제 재현
→ 원인 분석
→ 설계 또는 코드 수정
→ focused test
→ 실제 게임 재실행
→ 남은 한계 기록
```

### 4.7 커스텀 역할과 Tool capability 확장

#### 목표

기본 역할만 고정하는 대신, 역할별 능력과 허용 Tool을 조합할 수 있는 확장 구조를 마련했다.

#### 구현 내용

- 커스텀 역할 DB migration
- 역할별 Tool capability 저장
- MCP registry와 게임 엔진 연동
- 역할별 특수 행동의 허용·검증 경계 반영
- 관련 테스트 추가

#### 근거

- 기준 커밋: `de00426`
- migration: `backend/migrations/010_add_custom_role.sql`, `backend/migrations/011_add_custom_role_tool_abilities.sql`
- 테스트: `backend/tests/test_b16_custom_role.py`
- 요약: `docs/AI_MAFIA_CUSTOM_ROLE_MCP_TOOLS_SUMMARY.md`

#### 의미

이 확장은 단순한 역할 추가가 아니라, Agent가 사용할 수 있는 능력을 데이터와 Tool capability로 관리할 수 있도록 시스템의 확장 지점을 만든 작업이다.

### 4.8 통합 실행과 최종 문서화

#### 통합 대상

- User Frontend
- Admin Frontend
- Backend API
- Game Engine
- PostgreSQL
- Redis
- Agent Worker
- MCP Server
- LLM 또는 Fake Provider

#### 최종 확인 항목

- 게임 생성부터 결과까지 완주
- AI 발언·밤 행동·투표 처리
- 정보 격리와 허용 Tool 검증
- 저장 후 재개
- 오류와 fallback
- 관리자 Agent 활동 확인
- 커스텀 역할과 Tool capability
- 설계·구현 문서와 실제 코드의 일치 여부

#### 문서화 기준

`31593b6`에서 기획서, 전체 시스템 설계서, 영역별 설계서, Agent 아키텍처 설계서, Agent 시험 결과 보고서, 구현 계획서를 arrangement 문서 체계로 정리했다. 수행과정 보고서는 이 문서들이 계획·설계·평가의 근거라면, 실제 프로젝트가 그 계획을 어떻게 거쳐 왔는지를 연결하는 문서다.

## 5. 계획 대비 실제 구현 변화

| 초기 방향 | 실제 구현 | 변경 이유 | 영향 |
|---|---|---|---|
| 기본 게임 lifecycle 우선 | 저장·재개·재투표·병렬 투표까지 보완 | 실제 실행에서 상태 복구와 동시성 문제가 발견됨 | 게임 상태 원장과 복구 로직 강화 |
| 기본 Agent 실행 | Actor별 Context·허용 Tool·제안 검증 구조 | 정보 격리와 모델 출력 방어가 필요함 | Agent·MCP·Backend 경계 구체화 |
| 고정 역할 중심 MVP | 커스텀 역할과 Tool capability 추가 | 역할 확장성과 사용자 선택성 확보 | migration·API·MCP 범위 확장 |
| 기본 로그 중심 | Agent activity·관리자 지표 추가 | 운영과 평가를 위해 실행 상태 관찰 필요 | 관리자 API·화면·추적 구조 보강 |

계획 변경은 구현 실패로만 해석하지 않고, 실제 실행과 검증을 통해 설계가 보완된 결과로 기록한다. 단, 초기 계획에 없던 확장으로 인해 검증 범위가 충분하지 않은 부분은 별도의 한계로 남긴다.

## 6. 최종 구현 상태와 한계

### 6.1 확인된 결과

- 기본 게임 lifecycle을 실제 실행으로 확인했다.
- AI 행동을 Backend의 규칙 검증 경계에 연결했다.
- Actor별 Context와 허용 Tool 경계를 적용했다.
- 저장·재개와 주요 동시성 문제를 보완했다.
- MCP capability 기반 커스텀 역할 확장 경로를 마련했다.
- Agent 실행 활동과 관리자 관찰 경로를 보강했다.

### 6.2 남은 한계

- 실제 유료 또는 Local LLM Provider의 추론 품질은 제한적으로 평가되었다.
- 한 번의 게임 완주는 장기 게임 밸런스와 다양한 시나리오의 품질을 보장하지 않는다.
- Prompt·Persona 변경 전후의 정량 비교는 별도 시험 데이터와 동일 조건으로 추가 측정해야 한다.
- 운영 환경의 보안·TLS·비용·장기 장애 대응은 MVP 범위를 넘어선다.

## 7. 근거 자료

### 7.1 설계·계획 문서

- [프로젝트 기획서](00_AI_MAFIA_PROJECT_PROPOSAL.md)
- [전체 시스템 아키텍처 설계서](AI_MAFIA_SYSTEM_ARCHITECTURE_DESIGN.md)
- [Agent 아키텍처 설계서](06_AGENT_ARCHITECTURE_DESIGN.md)
- [구현 계획서](AI_MAFIA_IMPLEMENTATION_PLAN.md)
- [Agent 시험 결과 보고서](07_AGENT_TEST_RESULT_REPORT.md)

### 7.2 구현·검증 문서

- [현재 코드 상태](../AI_MAFIA_CURRENT_CODE_STATUS.md)
- [게임 테스트 공백 보고서](../AI_MAFIA_GAME_TEST_GAP_REPORT.md)
- [병렬 투표 버그 보고서](../AI_MAFIA_PARALLEL_VOTE_BUG_REPORT.md)
- [UI·UX 플레이테스트 보고서](../AI_MAFIA_UI_UX_PLAYTEST_REPORT.md)
- [커스텀 역할 MCP Tool 요약](../AI_MAFIA_CUSTOM_ROLE_MCP_TOOLS_SUMMARY.md)

## 8. 발표용 요약 흐름

발표에서는 모든 커밋을 설명하지 않고 다음 흐름만 보여준다.

```text
1. 혼자서도 AI와 함께 게임할 수 있어야 한다는 문제
2. 게임 규칙과 상태를 먼저 Backend Game Engine으로 안정화
3. Agent는 제한된 Context에서 허용된 Tool을 선택
4. Backend가 Agent 제안을 최종 검증
5. 실제 게임에서 동시성·정보 격리·복구 문제 발견
6. 코드와 테스트로 개선
7. 실제 게임 완주와 Agent 평가 결과 제시
```

발표의 핵심 문장은 다음과 같다.

> 이 프로젝트는 AI가 게임을 임의로 진행하게 한 것이 아니라, 게임 엔진이 안전한 실행 경계를 제공하고 Agent가 제한된 정보와 Tool 안에서 판단하도록 만든 뒤, 실제 오류를 추적하고 개선한 프로젝트다.
