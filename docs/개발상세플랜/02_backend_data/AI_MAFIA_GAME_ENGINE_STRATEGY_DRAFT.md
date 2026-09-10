# AI 마피아 게임 엔진 전략 초안

**문서 상태:** 임시 초안
**작성일:** 2026-09-04

이 문서는 게임 엔진을 짧고 독립적인 모듈로 관리하기 위한 임시 전략이다. 공개 API,
DB schema, MCP wire 계약을 변경하는 정본이 아니며, 구현 착수 전에 관련 정본과 팀
합의를 먼저 갱신해야 한다.

## 1. 책임 경계

```text
Agent Manager: job 예약 → context 조립 → MCP/LLM 호출 → 출력 검증 → proposal 제출
Game Engine: command/proposal 검증 → 규칙 계산 → next state와 event 결과 반환
Backend: transaction 저장 → event_outbox 기록 → Redis fan-out
```

Agent와 LLM은 게임 상태를 직접 변경하거나 승패를 결정하지 않는다. MCP runtime도
게임 판정자가 아니며 Backend 내부 Engine API만 호출한다.

## 2. Agent Manager Workflow

오케스트레이터는 전체 순서만 조정하고 각 단계는 작은 함수 또는 모듈로 유지한다.

```text
reserve_job → build_context → open_mcp_session → invoke_agent
→ validate_output → submit_proposal → reconcile_result → release_job
```

권장 분리 대상은 workflow state, context builder, proposal validator, provider/MCP
adapter, fallback, projection이다. 외부 호출 중에는 PostgreSQL transaction과 Redis
game lock을 유지하지 않으며, lease와 fencing token으로 늦은 결과를 무시한다.

## 3. Game Engine 모듈화

`game_engine.py`는 외부 진입점(Facade)으로 축소하고, 규칙은 phase 전환, action,
vote, night, victory, role 제약으로 분리한다. 엔진의 외부 계약은 다음 형태를
목표로 한다.

```python
result = engine.apply(state, command)
```

결과는 DB를 직접 변경하지 않고 `next_state`, `events`, `errors`, `state_version`을
반환한다. 우선 기존 `state_machine.py`, `game_engine/rng.py`, `fallback.py`를 활용해 분리하고,
추가 디렉터리가 필요해질 때만 정본 문서와 합의 후 도입한다.

## 4. Application Service 분리

현재 가장 큰 `game_service.py`는 테이블별이 아니라 유스케이스별로 분리한다.

```text
game_lifecycle_service: 생성·시작·종료·재개
command_service: SPEAK·PASS·NIGHT_ACTION·VOTE
window_service: action window 생성·해소
sync_service: snapshot·event·SSE/polling
agent_turn_service: Agent job 실행 연결
```

각 서비스의 흐름은 입력 검증 → 소유권/상태 확인 → repository 조회 → engine 실행
→ transaction 저장 → event_outbox 기록으로 고정한다.

## 5. 유지해야 할 금지 경계

- Game Engine은 FastAPI, PostgreSQL, Redis, LLM을 직접 호출하지 않는다.
- Router는 SQL과 Repository를 직접 호출하지 않는다.
- Agent와 MCP runtime은 게임 DB를 직접 수정하지 않는다.
- Frontend는 게임 승패나 규칙을 재계산하지 않는다.
- Redis는 원본 상태가 아니며 PostgreSQL에서 재구성 가능한 cache/fan-out만 담당한다.

## 6. 적용 순서

1. `game_service.py`를 lifecycle/command/window/sync 유스케이스로 나눈다.
2. `game_engine.py`의 규칙을 기존 모듈로 이동하고 Facade를 축소한다.
3. `orchestrator.py`를 명시적 Agent Workflow로 축소한다.
4. typed proposal/result 계약과 실패·stale·timeout 테스트를 고정한다.
5. 실제 섹터 간 계약 통합은 Backend OpenAPI와 정본 문서를 기준으로 수행한다.
