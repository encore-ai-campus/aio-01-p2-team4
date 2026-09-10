# AI 마피아 DB·Redis 세부 구현 계획서

상위 계획: [AI_MAFIA_IMPLEMENTATION_PLAN.md](../AI_MAFIA_IMPLEMENTATION_PLAN.md)  
참조 설계: [DB·Redis 설계서](../01_DB_REDIS_DESIGN.md)

## 1. 목표와 범위

빈 디렉터리에서 PostgreSQL을 확정 원장으로 사용하고 Redis를 lock·cache·stream
보조 계층으로 사용하는 현재 구현 상태까지 구축한다.

포함 범위는 migration, connection, transaction, repository, receipt, snapshot,
Agent Job 저장, Redis lock·cache·stream이다. 게임 규칙, HTTP API, MCP protocol,
화면 동작은 다른 계획서의 책임이다.

## 2. 상위 작업 연결

| 단계 | 상위 작업 | 결과 |
|---:|---|---|
| 1 | IP-01 | 공통 식별자·상태·오류 DTO |
| 2 | IP-02 | migration과 DB connection |
| 3 | IP-03 | repository와 transaction 경계 |
| 4 | IP-06 | Redis lock·cache·stream |
| 5 | IP-13 | DB·Redis 통합 검증 |

## 3. 구현 순서

1. 환경 변수와 DB 접속 설정을 정의한다.
2. 사용자·시나리오·역할·게임·플레이어 migration을 작성한다.
3. action window·submission·event·snapshot migration을 작성한다.
4. command receipt·Agent Job·capability migration을 작성한다.
5. feedback·audit·speech analysis·custom role migration을 추가한다.
6. migration runner와 재실행 확인을 구현한다.
7. game·player·action·event·receipt repository를 구현한다.
8. snapshot·feedback·admin·Agent repository를 구현한다.
9. transaction과 rollback 경계를 연결한다.
10. Redis lock·cache·stream을 추가하고 장애 시 축소 동작을 구현한다.

## 4. 작업별 구현 기준

| 작업 | 구현 내용 | 완료 기준 |
|---|---|---|
| DB 준비 | runtime·migration 접속 설정 분리 | 잘못된 설정이 기동 전에 거부됨 |
| Migration | 정렬된 additive SQL 실행 | 빈 DB에서 순서대로 적용·재실행 가능 |
| 원장 | 상태·event·receipt 저장 | 상태와 원장이 한 transaction으로 확정됨 |
| 멱등성 | receipt unique 조회·재사용 | 같은 키가 상태를 두 번 바꾸지 않음 |
| Agent 저장 | job·lease·fencing·capability 저장 | 오래된 Worker 결과가 차단됨 |
| Redis | lock·version cache·event stream | Redis 장애가 확정 원장을 대체하지 않음 |

## 5. 검증 계획

- 빈 DB migration과 schema version 확인
- migration 재실행과 부분 실패 후 재실행 확인
- game command transaction rollback 확인
- receipt 중복과 동일 키·다른 본문 거부 확인
- snapshot 저장·재개 확인
- 동시 game lock과 stale cache 거부 확인
- Redis 중단 후 PostgreSQL 기준 조회와 안전한 기능 축소 확인
- private role·capability 원문이 공개 cache에 저장되지 않는지 확인

## 6. 완료 조건

- PostgreSQL이 게임 상태·event·receipt의 확정 원본으로 동작한다.
- 모든 변경 경계가 transaction과 state version을 사용한다.
- Agent Job의 reservation·lease·fencing 상태를 저장할 수 있다.
- Redis는 보조 기능으로만 사용된다.
- 관련 테스트와 Team DB smoke 검증 결과가 상위 계획서에 기록된다.
