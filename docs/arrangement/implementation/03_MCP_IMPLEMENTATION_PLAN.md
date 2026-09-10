# AI 마피아 MCP 세부 구현 계획서

상위 계획: [AI_MAFIA_IMPLEMENTATION_PLAN.md](../AI_MAFIA_IMPLEMENTATION_PLAN.md)  
참조 설계: [MCP 설계서](../03_MCP_DESIGN.md)

## 1. 목표와 범위

빈 디렉터리에서 Streamable HTTP MCP Server와 Backend adapter를 구성해 Agent가
Context를 읽고 게임 action을 제출할 수 있는 현재 MCP runtime까지 구축한다.

MCP는 DB·Redis를 직접 접근하지 않는다. Resource·Prompt·Tool의 상세 protocol과
Schema는 MCP 설계서가 소유하며, Agent의 판단 순서는 Agent 계획서가 소유한다.

## 2. 상위 작업 연결

| 단계 | 상위 작업 | 결과 |
|---:|---|---|
| 1 | IP-07 | Backend internal Context·Action API |
| 2 | IP-08 | Context·proposal 계약 |
| 3 | IP-10 | MCP session·Resource·Prompt·Tool |
| 4 | IP-11 | Agent worker 왕복·관찰성 |
| 5 | IP-13 | MCP 통합 검증 |

## 3. 구현 순서

1. MCP Server application과 FastMCP SDK Streamable HTTP session lifecycle을 구성한다.
2. Context Resource URI와 scope handler를 연결한다.
3. `agent_instruction` Prompt를 Backend Context와 연결한다.
4. `submit_action` Tool을 내부 action API와 연결한다.
5. `manipulate_vote`, `inspect_special_roles` Tool을 역할 조건과 연결한다.
6. 입력·출력 Schema, typed error, receipt 결과를 검증한다.
7. Backend HTTP adapter와 timeout·재시도·redaction을 구성한다.
8. session·request·action metadata를 감사 기록으로 연결한다.

## 4. 기능별 구현 기준

| 기능 | 구현 내용 | 완료 기준 |
|---|---|---|
| Session | streamable HTTP session 관리 | 정상 연결·종료·재연결 |
| Resource | current/scoped Context 제공 | actor scope 외 정보가 제거됨 |
| Prompt | 게임 단계별 Agent 지침 제공 | Context와 허용 행동이 일치함 |
| submit_action | AI action 제출 | 내부 API receipt를 그대로 검증·반환 |
| manipulate_vote | 특수 투표 기능 | 역할·phase·사용 가능 여부 재검증 |
| inspect_special_roles | 특수 역할 조사 | 권한 없는 요청이 거부됨 |
| Adapter | Backend HTTP 왕복 | DB·Redis 직접 접근 없음 |

## 5. 오류와 보안 처리

- 잘못된 Tool 입력은 MCP 경계에서 거부한다.
- 권한·phase·target·window 검증은 Backend에서 다시 수행한다.
- 응답이 불명확하면 action을 새로 생성하지 않고 receipt 확인으로 연결한다.
- private role과 capability 원문을 public Resource·로그로 노출하지 않는다.
- 현재 MCP wire 요청에는 capability header를 전달하지 않는다. capability 만료·재사용은
  Agent 실행 경계에서 검증하고, MCP session-level capability binding은 운영 보강
  항목으로 관리한다.
- MCP Server 장애와 Backend 오류를 구분해 Agent가 retry/fallback을 선택할 수 있게 한다.

## 6. 검증 계획

- `tools/list`, Resource read, Prompt get, `tools/call` 왕복 확인
- scope별 정보 격리 확인
- Tool schema 오류와 권한 오류 확인
- stale window·state version action 거부 확인
- 동일 idempotency key receipt replay 확인
- MCP timeout·Backend 4xx/5xx 처리 확인
- FastMCP session 재연결과 감사 metadata redaction 확인
- capability를 MCP session에 연결할 경우 만료·폐기·scope 검증 추가

## 7. 완료 조건

- Agent가 MCP를 통해 Context 조회와 action 제출을 수행한다.
- MCP Server는 PostgreSQL·Redis에 직접 접근하지 않는다.
- 외부 MCP 표면과 내부 Backend 처리 단계가 구분된다.
- Tool별 권한·부작용·실패 결과가 검증된다.
- MCP focused test와 Backend 왕복 결과가 기록된다.
