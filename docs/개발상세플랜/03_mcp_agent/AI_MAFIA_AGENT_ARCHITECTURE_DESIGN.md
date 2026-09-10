# AI 마피아 Agent 아키텍처 설계서

## 1. 문서 목적

이 문서는 현재 저장소의 AI 마피아 규칙과 `mini_agent_07_human_approval` 수업
프로젝트의 Agent 실행 방식을 결합해 Agent의 책임·상태·Tool·정상 및 비정상 흐름을
정의한다.

첨부된 게임 규칙·시나리오 문서는 제품 요구사항으로 참고하고, 수업 샘플은 다음
구조의 참고 기준으로 사용한다.

- `AgentProfile`
- 공통 `Agent Runtime Loop`
- `MCP tools/list`와 `tools/call`
- LLM Function Call과 Tool Result 재전달
- 실행 State Store
- 진행 상태와 Trace
- 오류·최대 단계·재개 처리

실제 게임 규칙·DB·HTTP·MCP 계약은 `AI_MAFIA_MASTER_PLAN.md`,
`AI_MAFIA_DB_DESIGN.md`, `AI_MAFIA_API_SPEC.md`, `AI_MAFIA_BACKEND_PLAN.md`,
`AI_MAFIA_MCP_SERVER_DESIGN.md`를 우선한다. 본 문서는 설계 문서이며 구현은 포함하지 않는다.

## 2. 확정된 설계 결정

| 항목 | 결정 |
|---|---|
| Agent Profile | `AI Player`, `AI GM` 두 개 |
| 실행 단위 | AI 플레이어별 독립 Run, 게임당 AI GM Run 1개 |
| Agent 연결 | Backend Orchestrator가 독립 실행·조정 |
| Agent 직접 통신 | 없음 |
| AI 행동 승인 | 사용자 승인 없음, Backend Policy·Game Engine 검증 |
| Agent Runtime | Backend에 공통 Runtime 하나 사용 |
| Tool 실행 | Function Call Loop, Tool 1개씩 직렬 실행 |
| Provider | 기존 Provider abstraction 확장 |
| 최대 반복 | `MAX_AGENT_STEPS = 5` |
| Agent State | 수업과 같은 메모리 State Store |
| 사용자 저장 | 사용자가 `SAVE_AND_EXIT` 직접 실행 |
| 저장 후 Run | Agent Run State 유지, MCP session·capability 재생성 |
| 진행 상태 | 별도 Agent progress API 없이 게임 sync/SSE에 통합 |
| 오류 메시지 | 오류·fallback은 Backend, 정상 게임 narration은 AI GM |
| 서버 재시작 | 기존 Run 실패 처리 후 Backend fallback과 새 Run 생성 |

메모리 State와 저장 후 Run 유지 결정은 현재 DB 정본의 Agent 영속 설계와 다르다.
이 차이는 구현 전에 팀에서 검토해야 하며, 기존 정본 문서는 수정하지 않는다.

## 3. 전체 Agent 구조

```text
사용자
  ↓ 게임 command 또는 저장 command
Frontend
  ↓ HTTP
Backend Game API
  ↓
Backend Game Service
  ↓
Backend Agent Orchestrator
  ├─ AI Player Agent Run × AI 플레이어 수
  └─ AI GM Agent Run × 1
        ↓
공통 Agent Runtime
  ├─ AgentProfile
  ├─ 메모리 AgentState
  ├─ LLM Provider
  ├─ MCP Client
  └─ Policy 검증
        ↓
MCP Server
        ↓ Backend Internal Engine API
        ↓ Backend Game Engine
```

1. 사용자의 command는 Frontend가 Backend Game API로 전달한다.
2. Backend가 사용자·게임·phase·state version을 먼저 검증한다.
3. AI 차례가 필요하면 Backend Orchestrator가 AI Player Run을 생성한다.
4. AI Player는 MCP Resource와 Tool을 사용해 행동 proposal을 만든다.
5. Backend Game Engine이 proposal을 재검증하고 게임 상태에 반영한다.
6. 공개 event가 생성되면 Backend가 AI GM Run을 생성한다.
7. AI GM은 공개 event를 narration으로 변환한다.
8. Frontend는 게임 상태와 narration을 sync/SSE로 받는다.

AI Player와 AI GM은 직접 handoff하지 않는다. 모든 전달은 Backend의 검증된 공개 event와
State를 통해서만 이루어진다.

## 4. Agent별 역할과 책임

### 4.1 AI Player Agent

현재 차례에 필요한 공개 정보와 자기 개인 정보를 읽고 발언·PASS·밤 행동·투표 중 하나를 제안한다.

책임:

- `public`, `me`, `turn`, `persona` Resource 조회
- 현재 role과 persona에 맞는 행동 판단
- MCP Tool Function Call 생성
- Tool Result를 읽고 다음 행동 판단
- 최종 canonical proposal 반환

하지 않는 일:

- phase 변경, 승패 판정, 다른 플레이어 role 조회
- 다른 AI Player 호출, DB·Redis 직접 접근
- 자동 fallback 결정, proposal 직접 반영

역할별 차이는 별도 Profile이 아니라 `role`, `valid_targets`, `persona`와 Backend 재검증으로 처리한다.

### 4.2 AI GM Agent

Backend가 확정한 공개 event와 고정 guide를 자연스러운 게임 진행 문장으로 표현한다.

책임:

- 사건 설명, 게임 시작 안내, 낮 진행 안내
- 밤 결과·투표 결과·최종 투표·게임 종료 안내

하지 않는 일:

- role·승패·생사 판정
- 공격자·보호자·조사 결과·개별 투표 공개
- phase 변경, 게임 행동 Tool 호출
- AI Player proposal 직접 수신

AI GM은 AI Player와 동일한 Runtime을 사용하지만 Tool Call 없이 narration 결과에서 종료한다.

## 5. MCP Resource와 Tool

### 5.1 Resource 권한

| Agent | 허용 Resource | 금지 Resource |
|---|---|---|
| AI Player | `public`, `me`, `turn`, `persona` | `gm-guide` |
| AI GM | `public`, `gm-guide` | `me`, `turn`, `persona` |

AI Player Resource는 시나리오·생존자·공개 event, 자기 role·alibi·observation·private event,
현재 window·deadline·valid target, 배정 persona로 구성한다.

AI GM은 공개 projection과 narration guide만 받는다. Backend는 GM context에 role, 공격자,
보호 대상, 조사 결과, 개별 투표와 내부 추론을 포함하지 않는다.

### 5.2 AI Player Tool

| Tool | 사용 상황 | 결과 |
|---|---|---|
| `propose_speech` | 자기 발언 차례 | 발언 proposal |
| `propose_pass` | 자기 발언 차례 | PASS proposal |
| `propose_night_action` | 특수 역할의 밤 | 공격·조사·보호 대상 proposal |
| `propose_vote` | 일반·재·최종 투표 | 투표 대상 proposal |

Tool 입력에는 `game_id`, `agent_id`, `role`, `phase`, `state_version`을 넣지 않는다. session과
Backend가 해당 값을 관리한다.

### 5.3 Proposal 계약

```json
{
  "type": "SPEAK | PASS | NIGHT_ACTION | VOTE",
  "target_player_id": "UUID 또는 null",
  "message": "1~200자 또는 null",
  "public_rationale": "최대 500자 또는 null"
}
```

검증은 다음 순서로 진행한다.

```text
MCP schema 검증
→ Agent Policy 검증
→ Backend Game Engine 검증
→ DB transaction 반영
```

## 6. 수업 기반 공통 Agent Runtime Loop

### 6.1 시작

```text
Agent Run 생성
→ AgentState 생성
→ status = queued
→ MCP tools/list
→ Profile에 필요한 Tool 존재 확인
→ status = running
→ 최초 LLM 호출
```

### 6.2 반복

```text
LLM response 확인
→ Function Call이 없는가?
  ├─ 예: 최종 proposal/narration 저장 후 completed
  └─ 아니오: 첫 번째 Function Call 선택
→ JSON arguments 검증
→ allowlist 검증
→ MCP Tool 실행
→ Tool Result를 다음 LLM 호출에 전달
→ llm_calls·tool_calls·next_step 갱신
→ MAX_AGENT_STEPS까지 반복
```

한 번에 첫 번째 Tool Call 하나만 처리한다. 병렬 Tool Call은 사용하지 않는다.

### 6.3 종료 상태

| 상태 | 의미 |
|---|---|
| `queued` | 실행 요청을 접수했으나 아직 시작하지 않음 |
| `running` | Context 조회 또는 LLM·Tool Loop 실행 중 |
| `completed` | 최종 proposal 또는 narration 생성 완료 |
| `fallback` | 외부 실패로 Backend 규칙 fallback 적용 |
| `failed` | 시작·상태 복원·구조화 처리 자체가 실패 |
| `stopped` | 최대 단계 초과 또는 명시적 안전 중단 |
| `stale` | 오래된 State·session·version 결과라 반영하지 않음 |

## 7. AgentState 설계

수업의 `RUNS`와 같은 메모리 State Store에 다음 실행 상태를 보관한다.

```text
AgentState
├─ run_id
├─ agent_id
├─ agent_name
├─ goal
├─ game_id
├─ window_id
├─ subject_type
├─ subject_id
├─ role
├─ phase
├─ state_version
├─ current_prompt
├─ allowed_resources
├─ allowed_tools
├─ context_summary
├─ response_id
├─ next_step
├─ pending_proposal
├─ pending_narration
├─ llm_calls
├─ tool_calls
├─ retry_count
├─ lease_expires_at
├─ status
├─ failure_code
├─ termination_reason
└─ trace
```

State 원칙:

- `response_id`와 `next_step`을 저장해 저장 후 Runtime 재개에 사용한다.
- normalized proposal과 narration은 저장할 수 있다.
- raw LLM response, raw private context와 내부 추론 전문은 저장하지 않는다.
- Trace에는 단계·주체·상태·오류 분류만 남긴다.
- AI Player Run은 하나의 `subject_id`, AI GM Run은 하나의 `game_id`에만 묶인다.

## 8. 정상 흐름

### 8.1 AI Player

```text
window 생성
→ AI Player Run queued
→ tools/list
→ public/me/turn/persona 조회
→ LLM Function Call
→ MCP Tool 1개 실행
→ Tool Result 재전달
→ 최종 SPEAK/PASS/NIGHT_ACTION/VOTE proposal
→ Backend Engine 검증
→ submission·event·state 반영
→ Run completed
```

### 8.2 AI GM

```text
Backend가 공개 event 확정
→ AI GM Run queued
→ public/gm-guide 조회
→ LLM narration 생성
→ source event·guide·길이·금지 정보 검증
→ 공개 narration 저장
→ Run completed
→ sync/SSE로 Frontend 전달
```

## 9. 비정상 흐름과 사용자 메시지

### 9.1 AI Player

MCP discovery, Tool 실행, Provider timeout 또는 repair 재실패가 발생하면 Run을 `fallback`으로
기록하고 Backend 규칙 기반 자동 선택을 확정한다. 사용자에게 raw 오류·retry 내용·내부 판단은
보여주지 않는다.

### 9.2 AI GM

timeout, private 사실 포함, guide 불일치가 발생하면 narration을 폐기하고 Backend 고정 한국어
문구를 사용한다. 게임 상태와 승패는 변경하지 않는다.

### 9.3 사용자 입력 오류

| 상황 | 결과 | 사용자 메시지 |
|---|---|---|
| 발언 차례 아님 | reject | 현재는 발언할 수 없습니다. |
| 이미 제출함 | reject/replay | 이미 제출한 행동이 있습니다. |
| 죽은 사용자 행동 | reject | 관전 모드에서는 행동할 수 없습니다. |
| 잘못된 대상 | reject | 현재 선택할 수 없는 플레이어입니다. |
| deadline 초과 | reject 또는 auto 처리 | 제한 시간이 지나 행동을 제출할 수 없습니다. |
| state version 충돌 | reject | 게임 상태가 변경되었습니다. 최신 상태를 확인해 주세요. |
| 저장 불가능한 resolving 상태 | reject | 현재 게임 처리가 끝난 뒤 저장할 수 있습니다. |

## 10. 사용자 저장과 Agent Run 재개

### 저장

```text
사용자가 SAVE_AND_EXIT 클릭
→ Backend가 owner·status·state_version 검증
→ 안정 상태 확인
→ timed window 남은 시간 계산
→ 게임 status = SAVED
→ Agent Run State 메모리 유지
→ 기존 MCP session·capability 폐기
→ 저장 완료 event
→ Frontend 게임 화면 종료
```

진행 중인 resolution transaction은 중간 저장하지 않는다. 열린 timed window는 남은 시간을
저장하고, deadline이 없는 발언 window는 deadline 없이 저장한다.

### 재개

```text
RESUME
→ 게임 snapshot 복원
→ 유지된 AgentState 조회
→ 새 MCP session·capability 생성
→ response_id·next_step 기준 Runtime 재개
→ 현재 state_version·window 재검증
→ 유효하지 않으면 stale 처리 후 fallback
```

서버 재시작으로 AgentState가 사라지면 기존 Run은 `failed` 처리하고 Backend fallback 후 새 Run을 만든다.

## 11. 진행 상태와 Trace

별도 Agent progress API는 만들지 않고 게임 sync/SSE에 안전한 상태 event로 통합한다.

사용자에게 공개 가능한 상태는 `AGENT_QUEUED`, `AGENT_RUNNING`, `AGENT_FALLBACK`,
`AGENT_COMPLETED`다. 다음은 공개하지 않는다.

- prompt, raw model response, private context, 내부 추론 전문
- 다른 Agent의 role·target·action
- capability·bootstrap token·signature
- 상세 exception message와 stack

Trace owner는 `runtime`, `ai_agent`, `mcp`, `policy`, `backend`를 사용한다.

## 12. 테스트 기준

### 정상 케이스

- Profile 생성과 Agent별 독립 Run 생성
- Tool discovery 후 허용 Tool만 실행
- 발언, PASS, 밤 행동, 일반·재·최종 투표 proposal 완료
- Tool Result 재전달 후 최종 결과 생성
- AI GM의 공개 event narration 완료
- 5단계 이내 정상 종료
- 저장 후 AgentState 유지와 재개 시 새 MCP session 생성

### 비정상 케이스

- 필요한 MCP Tool 없음
- MCP Tool 실행 실패
- Provider timeout
- 잘못된 JSON과 repair 1회 후 재실패
- 허용되지 않은 Tool
- 잘못된 target·role·phase·state version
- MAX_AGENT_STEPS 초과
- lease 만료와 stale 결과
- 저장 후 기존 session·capability 재사용
- 서버 재시작으로 State 유실
- GM의 private 사실 포함 또는 guide 불일치
- 동일 proposal 재전송과 다른 body의 동일 ID 재사용

## 13. 현재 저장소 대응

| 수업 개념 | 현재 저장소 대응 |
|---|---|
| Agent Profile | `backend/app/agent/` 확장 대상 |
| Runtime Loop | `backend/app/agent/orchestrator.py` 확장 대상 |
| Game State | `backend/app/models/game_state.py` |
| Game Rule | `backend/app/agent/game_engine.py` |
| Fallback | `backend/app/agent/fallback.py` |
| Context projection | `backend/app/agent/projections.py` |
| Provider | `backend/app/llm_provider/` |
| MCP Client | `backend/app/mcp/` |
| Agent State | 수업 기준 메모리 State Store 신규 설계 대상 |
| 진행 전달 | `backend/app/services/sync_service.py`와 공개 event |

`mcp_server/mafia_game/`은 canonical MCP runtime 구현 영역이다. 이 문서 작성 시점에는 실행
가능한 MCP 서버 구현이나 게임 코드 구현을 추가하지 않는다.
