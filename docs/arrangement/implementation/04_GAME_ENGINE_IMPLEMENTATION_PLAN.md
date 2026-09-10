# AI 마피아 게임 엔진 세부 구현 계획서

상위 계획: [AI_MAFIA_IMPLEMENTATION_PLAN.md](../AI_MAFIA_IMPLEMENTATION_PLAN.md)  
참조 설계: [게임 엔진·시나리오 설계서](../04_GAME_ENGINE_SCENARIO_DESIGN.md)

## 1. 목표와 범위

빈 디렉터리에서 외부 서비스 없이 결정적으로 게임을 생성·진행·저장·재개할 수
있는 현재 Game Engine과 Game Runtime까지 구축한다.

게임의 phase, 역할, 승패, 대상 검증은 게임 엔진 설서가 정본이다. Agent는 엔진에
proposal을 제공할 뿐이며, API·DB 저장 방식은 각각의 설계서를 참조한다.

## 2. 상위 작업 연결

| 단계 | 상위 작업 | 결과 |
|---:|---|---|
| 1 | IP-01 | phase·action·오류 타입 |
| 2 | IP-04 | 순수 Game Engine |
| 3 | IP-05 | Game Runtime·transaction 조정 |
| 4 | IP-06 | lock·cache·stream 연결 |
| 5 | IP-13 | 게임 전체 통합 검증 |

## 3. 구현 순서

1. game state, phase, action, result 타입을 정의한다.
2. 역할 배정과 생존자 상태를 구현한다.
3. `new_game`, `begin_game`, `save`, `resume`, `replay`를 구현한다.
4. 발언·pass·토론 종료를 구현한다.
5. 밤 행동 제출과 밤 결과 해소를 구현한다.
6. 투표·재투표·투표 결과 해소를 구현한다.
7. 최종 토론·최종 고발·승패·완료를 구현한다.
8. Game Runtime에서 command·receipt·event·snapshot을 transaction으로 연결한다.
9. AI 작업 생성과 열린 action window 진행을 연결한다.

## 4. 기능별 완료 기준

| 영역 | 완료 기준 |
|---|---|
| 생성 | 6~9명 구성과 역할 배정이 재현 가능함 |
| 토론 | 생존 AI·인간의 차례와 발언이 정확히 처리됨 |
| 밤 | 역할별 허용 행동과 대상 검증이 적용됨 |
| 투표 | 일반 투표·동률·재투표가 처리됨 |
| 종료 | 승패 조건과 최종 고발이 결정됨 |
| 복구 | 저장된 상태에서 재개·replay가 가능함 |
| AI 연결 | proposal이 Engine 검증을 거쳐서만 반영됨 |
| 원장 | 상태·event·receipt가 원자적으로 저장됨 |

## 5. 불변식

- 종료된 게임은 새로운 action을 받을 수 없다.
- 죽은 플레이어는 행동 주체나 유효 대상이 될 수 없다.
- 한 행동 창에서 동일 플레이어의 동일 행동을 중복 반영하지 않는다.
- 현재 phase에 속하지 않는 command를 적용하지 않는다.
- Engine은 LLM·HTTP·DB·Redis에 의존하지 않는다.
- RNG가 필요한 경우 seed와 후보 순서가 결과를 결정한다.

## 6. 검증 계획

- 6·8·9명 게임 생성 확인
- 모든 phase 전이와 대표 승패 시나리오 확인
- 잘못된 phase·target·role action 확인
- 투표 동률과 재투표 확인
- 밤 행동 취합과 결과 해소 확인
- 저장·재개·replay 결과 비교
- 동일 receipt·stale version·동시 command 확인
- 외부 Provider·MCP 없이 순수 Engine 테스트 실행

## 7. 완료 조건

- 대표 게임이 역할 공개부터 완료까지 진행된다.
- Engine이 모든 게임 규칙의 최종 판정자다.
- Agent proposal과 인간 command가 동일한 최종 검증 경계를 통과한다.
- Runtime과 Repository 연결 후 부분 저장이 발생하지 않는다.
- Engine focused test와 Team DB 대표 게임 검증 결과가 기록된다.
