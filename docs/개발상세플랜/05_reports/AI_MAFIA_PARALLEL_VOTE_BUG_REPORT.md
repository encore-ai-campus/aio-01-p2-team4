# AI 자동 투표 문제와 병렬 투표 개선 기록

- 작성일: 2026-09-07
- 범위: WU-B6, 일반 투표·재투표·최종 지목의 AI 실행과 저장
- 사용자 요청: 인간의 첫 투표를 기다리지 않고 모든 AI가 투표 시작부터 병렬로 판단·제출
- 검증 방침: 사용자 요청에 따라 자동 테스트·lint·전체 회귀를 실행하지 않고 실제 로컬 실행을 확인
- 상태: 구현 및 실제 로컬 9인 게임의 두 투표 window 확인 완료

## 1. 증상과 재현 조건

9인 완료 게임의 투표 원장을 조사한 결과 AI 45표 중 28표가 `AUTO`, 17표가
`AGENT`였다. 발언 39건은 모델 생성에 성공했으므로 모든 AI가 판단을 하지 못하는
Provider 장애로 설명할 수 없었다.

| 조건 | 관찰 결과 |
|---|---|
| 첫 일반·재투표에서 인간이 마감까지 제출하지 않음 | AI job을 생성하지 않은 채 AI 16표 모두 AUTO |
| 세 번째 일반·재투표에서 인간이 늦게 제출 | 일부 job이 마감 전에 성공했지만 AI 12표 모두 AUTO |
| 다른 투표에서 인간이 비교적 일찍 제출 | AI 17표가 AGENT로 저장됨 |

실제 사용자 발언 원문·소유자 식별자·접속 자격 증명은 이 문서에 복사하지 않는다.

## 2. 원인 조사

### 2.1 인간의 첫 투표를 AI 시작 조건으로 사용

`backend/app/repositories/action_repository.py`의 `list_ai_vote_turns`는 인간이
살아 있으면 해당 인간의 `VOTE` 제출이 존재할 때만 AI를 조회했다. 따라서 인간이
마감까지 고민하면 AI도 판단을 시작하지 못하고 전원 자동 선택으로 넘어갔다.

전원 제출 여부는 엔진이 별도로 확인하므로 AI 시작을 인간 뒤로 미룰 필요가 없었다.

### 2.2 순차 생성 후 전체 batch 저장

`backend/app/services/game/postgres_runtime.py`의 `_run_agent_batch`는 AI마다
`await`한 뒤 모든 선택을 한 번에 제출했다. 한 AI가 `STALE` 또는 `DUPLICATE`이면
그 전에 완료된 선택도 저장하지 않았다. 30초 안에 모든 호출이 순서대로 끝나야 하는
구조였으며, 실제 기록에서도 마감 전에 끝난 모델 결과가 제출 원장에 반영되지 않았다.

### 2.3 개별 제출이 다른 AI 판단의 상태 버전을 무효화

단순히 호출만 병렬화하면 첫 AI 표 저장 시 `state_version`이 증가해 나머지 판단이
stale로 거부된다. 사용자 투표가 중간에 들어와도 같은 문제가 생긴다. 따라서 호출
방식과 함께 비공개 표의 저장·버전 검증 경계를 수정해야 했다.

### 2.4 중앙 worker의 직렬 대기

기존 worker는 발언·밤·투표 호출을 순서대로 기다렸다. 다른 게임의 긴 LLM 호출도
새 투표의 조회와 마감 처리를 늦출 수 있었다.

## 3. 해결 과정과 최종 동작

1. 인간 제출 대기 조건을 제거했다. 열린 투표의 생존·미제출 AI를 즉시 조회한다.
2. 투표 전용 scheduler를 분리했다. command commit이 polling을 깨우며, 진행 중
   발언·밤 LLM 호출을 기다리지 않고 새 window와 마감을 계속 관찰한다.
3. 같은 window의 모든 AI 판단을 `asyncio.gather`로 시작하고, 각 판단이 끝나면
   별도 transaction으로 표를 저장한다. 다른 AI의 실패는 이미 저장한 표에 영향을 주지 않는다.
4. 미해소 AI 표는 제출 원장·receipt만 기록한다. 공개 상태 버전·event·득표수는
   바꾸지 않는다. 인간은 기존 화면 버전으로 계속 투표할 수 있다.
5. 인간의 같은 window 첫 표가 만든 한 버전 증가만 제출 원장의
   `observed_state_version`으로 증명해 허용한다. AI context client는 같은 phase·window의
   한 버전 증가만 받아들이며, 완료·저장 시 DB가 원인을 다시 확인한다.
6. 표 저장 직전 job의 lease token·상태·만료와 window·deadline·actor·대상을 확인한다.
   저장·재개로 변경된 버전이나 다른 window의 결과를 옮기지 않는다. 재개 후 미제출
   job은 이전 lease 만료 후 과거 결과를 버리고 새 기준으로 다시 판단한다.
7. 동기 Agent DB 호출과 표 저장은 thread로 넘겨 API event loop를 막지 않는다.

전원 제출 또는 30초 마감에서 기존 규칙으로 투표를 해소한다. 마감 시 이미 제출된
표는 유지하고 미제출자만 AUTO로 채운다. 역할·개별 표·현재 득표수는 종료 전 공개하지
않는다. 밤 행동과 승패 판정 규칙 자체는 이번 수정 대상이 아니다.

## 4. 검증 결과

로컬 Backend `18000`·MCP `18100`·Frontend `18501`·실제 설정된 LLM을 사용해
9인 게임을 생성했다. 별도 Chromium에서 실제 게임 화면을 열고 공개 command API로
게임을 진행했다. 첫 밤 사망 때문에 첫 투표의 AI는 7명, 둘째 투표는 6명이었다.

시간은 각 window의 DB `opened_at`을 기준으로 측정했다.

| 관찰 항목 | 첫 일반 투표 | 두 번째 일반 투표 |
|---|---:|---:|
| 생존 AI | 7명 | 6명 |
| AI 전체 job 시작 시각의 간격 | 0.141초 | 0.105초 |
| 첫 AI job 시작 | 0.076초 | 0.082초 |
| 첫 AI 표 저장 | 1.801초 | 2.253초 |
| 마지막 AI 표 저장 | 3.517초 | 4.928초 |
| 인간 표 저장 | 3.635초 | 1.645초 |
| 인간 표 직전에 저장된 AI 표 | 7표 | 0표 |
| 최종 AI AGENT / AUTO | 7 / 0 | 6 / 0 |
| 모델 job SUCCEEDED | 7건 | 6건 |

- 첫 투표: 인간이 제출하기 전에 AI 전원이 정상 제출했다. 공개 버전은 20으로
  유지됐으며 인간이 마지막 표를 제출한 뒤 21로 올라 다음 밤으로 전환했다.
- 두 번째 투표: AI 6명이 모두 판단 중일 때 인간이 제출했다. 버전이 30에서
  31로 증가한 뒤에도 원래 버전 30의 AI 표 6건이 정상 저장됐고 마지막 표에서
  32로 증가하며 다음 밤으로 전환했다.
- 첫 AI 표는 마지막 AI 판단 완료 전에 저장됐다. 단순한 병렬 생성 후 일괄 저장이
  아니라 응답 완료별 개별 commit임을 `submitted_at`과 `completed_at`으로 확인했다.
- 두 투표 합계 AI 13표가 모두 AGENT였고 AUTO는 0표였다. 확인 후 게임은
  `SAVED`로 저장했으며 브라우저에서도 저장·시간 정지 안내를 확인했다.
- 자동 테스트·lint·전체 회귀는 사용자 요청에 따라 실행하지 않았다. 재투표·최종 지목,
  여러 게임 동시 진행, Provider 장애·lease 만료·저장/재개 중 판단 취소는 코드 경계를
  검토했으나 이번 실게임에서 별도로 재현하지 않았다. 모든 장애에서 AUTO가 없어지는
  변경은 아니며 마감 시 미제출 자동 선택은 유지한다.

## 5. 변경 파일과 운영 반영

- 조회·버전 증명: `backend/app/repositories/action_repository.py`
- 예약·완료·재개 복구: `backend/app/repositories/agent_repository.py`
- 개별 저장·최종 해소: `backend/app/services/game/action_command.py`
- 병렬 판단·개별 결과 적용: `backend/app/services/game/postgres_runtime.py`
- 투표 scheduler: `backend/app/services/game/ai_progress_worker.py`
- 비동기 DB 호출: `backend/app/agent/orchestrator.py`
- 투표 context·receipt 검증: `backend/app/mcp/client.py`

수정 반영에는 Backend 재시작이 필요하다. 새 환경 변수·DB migration은 필요하지 않다.
같은 게임 DB를 사용하는 Backend가 여러 개면 모두 같은 버전이어야 한다. 기존 로컬
Redis·토큰 8192 설정과 페르소나 파라미터는 그대로 사용한다.

관련 계약: [마스터플랜](../01_core/AI_MAFIA_MASTER_PLAN.md),
[DB 설계](../02_backend_data/AI_MAFIA_DB_DESIGN.md),
[API 명세](../01_core/AI_MAFIA_API_SPEC.md).
