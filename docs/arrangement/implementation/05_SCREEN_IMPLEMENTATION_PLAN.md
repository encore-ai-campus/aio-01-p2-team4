# AI 마피아 화면 세부 구현 계획서

상위 계획: [AI_MAFIA_IMPLEMENTATION_PLAN.md](../AI_MAFIA_IMPLEMENTATION_PLAN.md)  
참조 설계: [화면 설계서](../05_SCREEN_DESIGN.md)

## 1. 목표와 범위

빈 디렉터리에서 User Frontend와 Admin Frontend를 Backend 계약에 연결해 현재
구현된 게임 진행·동기화·결과·관리자 조회 화면까지 구축한다.

화면은 규칙·승패·AI 판단을 계산하지 않는다. 화면 구성과 상태 표시는 화면
설계서가, API 응답은 API 설계서가, Agent activity의 의미는 Agent 설계서가 정본이다.

## 2. 상위 작업 연결

| 단계 | 상위 작업 | 결과 |
|---:|---|---|
| 1 | IP-07 | Backend 공개·관리자 API |
| 2 | IP-11 | AI activity·sync 데이터 |
| 3 | IP-12 | User/Admin Frontend |
| 4 | IP-13 | 브라우저·E2E 검증 |

## 3. User Frontend 구현 순서

1. UUID 기반 사용자 식별과 session 복구를 구현한다.
2. 홈과 게임 생성 화면을 구현한다.
3. 역할 공개 화면을 구현한다.
4. 공통 game shell과 snapshot 상태 표시를 구현한다.
5. 토론·발언·투표·밤 행동 panel을 구현한다.
6. AI activity와 대기 상태를 표시한다.
7. sync polling/SSE와 재연결을 구현한다.
8. 관전·결과·feedback·설정 화면을 연결한다.

## 4. Admin Frontend 구현 순서

1. 관리자 식별과 allowlist 거부 화면을 구현한다.
2. dashboard와 게임 목록을 구현한다.
3. 게임 상세·지표·feedback·audit 화면을 구현한다.
4. speech analytics와 insight query 화면을 연결한다.
5. empty·loading·error·권한 오류 상태를 추가한다.

## 5. 화면 상태 처리 기준

| 상태 | 화면 처리 |
|---|---|
| loading | 진행 중 표시, 중복 제출 방지 |
| empty | 데이터 없음 안내 |
| error | 재시도 또는 안전한 종료 안내 |
| stale | authoritative snapshot 재조회 |
| completed | 입력을 닫고 결과 표시 |
| AI running | 현재 단계와 activity 표시 |
| AI fallback/failed | 내부 오류 세부정보 없이 제한된 상태 표시 |

화면은 Backend가 반환한 `legal_actions`, `valid_targets`, `action_window`를
표시할 뿐 자체적으로 행동 가능 여부를 계산하지 않는다.

## 6. 동기화·보안 기준

- SSE는 `Last-Event-ID`를 사용해 끊긴 지점 이후를 재요청한다.
- sequence 또는 state version이 뒤처지면 부분 상태를 적용하지 않는다.
- private role은 해당 사용자 화면에만 표시한다.
- Agent activity에는 공개 가능한 stage와 결과만 표시한다.
- 관리자 화면은 Backend allowlist와 redaction 결과를 그대로 사용한다.
- API 실패 시 사용자가 중복 command를 다시 제출하지 않도록 상태를 갱신한다.

## 7. 검증 계획

- 사용자 UUID 생성·복구 확인
- 게임 생성부터 역할 공개·완료까지 브라우저 흐름 확인
- 각 phase 입력과 잘못된 입력 표시 확인
- AI 대기·반영·fallback·실패 activity 확인
- SSE 재연결과 stale snapshot 복구 확인
- 결과·feedback 제출 확인
- 관리자 접근 거부·목록·상세·지표·audit 확인

## 8. 완료 조건

- 실제 Backend API만으로 User/Admin Frontend가 동작한다.
- 화면이 게임 규칙이나 AI 행동을 자체 계산하지 않는다.
- 재접속·중복 제출·stale 상태에서 안전하게 복구된다.
- private 정보와 내부 Agent 정보가 잘못 노출되지 않는다.
- 사용자 대표 시나리오와 관리자 조회 시나리오의 브라우저 검증 결과가 기록된다.
