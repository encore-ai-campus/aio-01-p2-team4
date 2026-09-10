# AI 마피아 에이전트 세부 구현 계획서

상위 계획: [AI_MAFIA_IMPLEMENTATION_PLAN.md](../AI_MAFIA_IMPLEMENTATION_PLAN.md)  
참조 설계: [에이전트 아키텍처 설계서](../06_AGENT_ARCHITECTURE_DESIGN.md)

## 1. 목표와 범위

빈 디렉터리에서 actor별 Agent가 제한된 Context를 읽고, Provider proposal을 만들고,
검증된 행동을 MCP 또는 Backend action 경계로 제출하며, 결과와 Trace를 남기는 현재
구현 상태까지 구축한다.

Agent는 게임 규칙을 직접 구현하지 않는다. 상세 규칙은 게임 엔진 설계서, MCP
protocol은 MCP 설계서, Job·Receipt 저장은 DB·Redis 설계서를 참조한다.

## 2. 상위 작업 연결

| 단계 | 상위 작업 | 결과 |
|---:|---|---|
| 1 | IP-04·IP-05 | Agent가 호출할 게임 실행 경계 |
| 2 | IP-08 | Context·proposal·policy |
| 3 | IP-09 | Provider·Orchestrator |
| 4 | IP-10 | MCP Client와 action 제출 |
| 5 | IP-11 | AI worker·Activity·Trace |
| 6 | IP-13 | Agent 통합·실패 검증 |

## 3. 구현 순서

1. Agent status, Job spec, proposal, result, error 타입을 정의한다.
2. public/me/turn/persona Context projection을 구현한다.
3. SPEAK·PASS·VOTE·NIGHT_ACTION proposal Schema와 policy를 구현한다.
4. Fake·Dummy·외부 Provider interface와 factory를 구현한다.
5. Agent Job reservation·lease·capability·complete/revoke를 연결한다.
6. Orchestrator의 Context→Provider→검증→결과 처리 Loop를 구현한다.
7. MCP Client의 Resource 조회와 `submit_action` 제출을 연결한다.
8. Context의 `agent_instruction`을 Provider 요청에 연결한다. MCP Prompt 직접
   호출은 현재 구현 범위에 포함하지 않는다.
9. state version·window·actor binding과 사용자 API idempotency 처리를 연결한다.
10. Agent 내부 action은 새 UUID 제출과 Job·window·state·Engine 중복 검증을
    연결한다. 안정적인 Agent key 재사용은 보강 범위로 기록한다.
11. invalid proposal 교정·retry·fallback·stale 처리를 구현한다.
12. AI worker가 열린 action window의 Job을 실행하도록 연결한다.
13. Agent Activity와 Trace를 기록하고 공개 결과를 redaction한다.
14. 게임 결과·feedback과 Agent 실행 결과를 평가 입력으로 연결한다.

## 4. Agent 판단 계약

| 단계 | Agent 책임 | 위임 대상 |
|---|---|---|
| Context | 필요한 scope만 읽고 해석 | Context Projection·MCP |
| 판단 | 다음 행동 proposal 생성 | LLM Provider |
| 1차 검증 | 형식·필수값·허용 행동 확인 | Orchestrator |
| 최종 검증 | phase·role·target·상태 적용 가능성 확인 | Backend·Game Engine |
| 적용 | 확정 결과 확인 | Game Runtime·Repository |
| 기록 | 실행 stage와 결과 기록 | Activity·DB |

## 5. Tool·행동 구현 기준

| 논리적 행동 | 현재 제출 경로 | 조건 |
|---|---|---|
| `propose_speech` | `submit_action` | 발언 단계와 발언 차례 |
| `propose_pass` | `submit_action` | 현재 행동 창이 pass 허용 |
| `propose_vote` | Backend batch action service | 투표 단계와 유효 대상 |
| `propose_night_action` | Backend batch action service | 역할·능력·대상 조건 |
| 특수 투표 조작 | `manipulate_vote` | 현재 사용자 전용 기능 |
| 특수 역할 조사 | `inspect_special_roles` | 현재 사용자 전용 기능 |

논리적 proposal 이름과 실제 MCP Tool 이름은 동일하지 않을 수 있다. Tool의 상세
입력·출력·실패 Schema는 [MCP 설계서](../03_MCP_DESIGN.md)를 따른다.

## 6. 멱등성·동시성 구현 기준

```text
Job 예약
→ action 제출 전 receipt 확인
→ 동일 key 결과 replay
→ 미처리 action만 제출
→ 응답 불명확 시 새 요청 금지
→ state version/window 재검증
→ 적용 결과와 trace 저장
```

사용자 API 행동은 game·actor·window·action type·idempotency key binding을 사용한다.
현재 Agent 내부 MCP·batch 제출은 새 UUID를 생성하므로, Lease 만료 Worker와 이전
fencing token 결과 차단, window·state·Engine 중복 검증이 중심이다. Agent action별
안정적인 key 재사용은 보강 대상이다. Receipt와 DB unique 제약의 상세 구현은
DB·Redis 계획서에 위임한다.

## 7. 오류·복구 구현 기준

| 오류 | 처리 |
|---|---|
| Provider timeout | 제한된 retry |
| 잘못된 proposal | 교정 1회 후 재검증 |
| 허용되지 않은 행동 | 차단 후 재판단 또는 종료 |
| MCP 오류 | 제한된 retry 후 fallback/실패 |
| stale binding | Context 갱신 또는 `STALE` |
| 중복 action | 기존 receipt replay |
| 적용 여부 불명 | receipt·원장 확인 |
| 최대 step 초과 | Agent 종료 |

Fallback은 임의 행동을 만들지 않고, 검증 가능한 대체 처리 또는 안전한 종료만
수행한다.

## 8. Trace·평가 구현 기준

Trace에는 `run_id`, `job_id`, `game_id`, `actor_id`, `phase`, `window_id`,
`state_version`, stage, action, attempt, status, error code, latency를 기록한다.

다음 결과를 구분한다.

- `DECIDED`: Provider가 proposal을 생성함
- `APPLIED`: Game Engine이 행동을 확정 반영함
- `FALLBACK`: 제한된 대체 경로를 사용함
- `STALE`: 오래된 상태로 거부됨
- `DUPLICATE`: 기존 receipt를 재사용함
- `FAILED`: 복구할 수 없는 오류로 종료됨

평가 시 규칙 준수, Tool 선택, 역할 준수, 정보 격리, stale·중복 방지, 승률·생존률,
발언 품질, 호출 수와 latency를 비교한다.

## 9. 검증 계획

- actor별 Context scope 격리
- 역할·phase별 허용 행동
- 정상 SPEAK·VOTE·NIGHT_ACTION proposal
- invalid JSON·invalid target·invalid phase
- Provider timeout·MCP timeout·fallback
- lease 만료와 늦은 결과 차단
- 동일 idempotency key 중복 제출
- state version·window 변경에 따른 stale 처리
- worker 재시작 후 열린 Job 복구
- Agent activity redaction과 Trace stage 순서
- fake Provider를 이용한 반복 가능한 평가 시나리오

## 10. 완료 조건

- Agent가 actor별 Context 범위 안에서만 판단한다.
- Provider 출력이 proposal 검증을 통과한 경우에만 실행된다.
- 최종 게임 상태 변경은 Backend·Game Engine을 거친다.
- 중복·stale·늦은 Worker 결과가 반영되지 않는다.
- MCP Resource 조회·발언 제출·Provider 장애에 retry 상한과 fallback이 적용된다.
- 투표·밤 행동은 proposal 생성과 Backend batch 반영을 구분한다.
- `DECIDED`와 `APPLIED`가 Trace에서 구분된다.
- 실행 결과를 게임 feedback과 결합해 개선할 수 있다.
