# AI 마피아 API 세부 구현 계획서

상위 계획: [AI_MAFIA_IMPLEMENTATION_PLAN.md](../AI_MAFIA_IMPLEMENTATION_PLAN.md)  
참조 설계: [API 설계서](../02_API_DESIGN.md)

## 1. 목표와 범위

빈 디렉터리에서 User Frontend, Admin Frontend, Agent/MCP runtime이 사용할 현재
FastAPI API 경계까지 구축한다.

API의 상세 Schema는 [API 설계서](../02_API_DESIGN.md)의 정본을 따른다. 게임 규칙은
Game Engine에, Agent 판단은 Agent 계획서에, MCP protocol은 MCP 계획서에 위임한다.

## 2. 상위 작업 연결

| 단계 | 상위 작업 | 결과 |
|---:|---|---|
| 1 | IP-01 | 공통 요청·응답·오류 Schema |
| 2 | IP-05 | Game Service 연결 |
| 3 | IP-07 | 공개·관리자·내부 API |
| 4 | IP-13 | API 통합 검증 |

## 3. 구현 순서

1. FastAPI application과 공통 middleware를 구성한다.
2. `/health`, `/ready`와 공통 오류 응답을 구현한다.
3. 게임 생성·목록·상세·삭제 API를 구현한다.
4. game command와 sync API를 구현한다.
5. SSE events endpoint와 `Last-Event-ID` 재연결을 구현한다.
6. feedback와 custom role ability 조회 API를 구현한다.
7. 관리자 게임·지표·feedback·audit API를 구현한다.
8. Agent Context·Prompt·Action 내부 API를 구현한다.
9. CORS·소유권·관리자 allowlist·redaction을 적용한다.

## 4. API 그룹별 구현 기준

| 그룹 | 주요 경로 | 완료 기준 |
|---|---|---|
| Health | `/health`, `/ready` | dependency 상태가 구분되어 반환됨 |
| Game | `/api/v1/games` | 생성·조회·삭제와 소유권 검증 |
| Command | `/api/v1/games/{game_id}/commands` | receipt·state version·오류 계약 적용 |
| Sync | `/sync`, `/events` | snapshot과 cursor 기반 재연결 |
| Feedback | `/api/v1/feedback` | 게임 소유권과 입력 검증 |
| Admin | `/api/v1/admin/*` | allowlist와 읽기 전용 조회 경계 |
| Internal | `/internal/mcp/*` | game·actor·window·version binding 검증 |

## 5. 공통 처리 순서

```text
header·body 검증
→ 식별자·소유권 확인
→ receipt 조회
→ Application Service 호출
→ 상태·event·receipt 결과 반환
```

`Idempotency-Key`, `X-Request-Id`, `Last-Event-ID`의 형식과 의미는 API 설계서를
따른다. API가 phase·승패·valid target을 직접 계산하지 않도록 한다.

## 6. 검증 계획

- 정상·잘못된 UUID·필수 필드 누락 확인
- 다른 사용자의 game 접근 거부 확인
- command 중복과 stale version 확인
- SSE 재연결과 이미 전송된 event cursor 확인
- 관리자 allowlist 거부와 redaction 확인
- 내부 MCP API의 actor·window binding 위반 확인
- CORS와 health/readiness 실패 응답 확인

## 7. 완료 조건

- 공개·관리자·내부 API가 설계서의 envelope과 오류 형식을 사용한다.
- 변경 API는 Game Service와 transaction을 통해서만 상태를 변경한다.
- Frontend와 MCP가 실제 API 계약으로 연결된다.
- API focused test와 대표 HTTP 왕복 검증 결과가 기록된다.
