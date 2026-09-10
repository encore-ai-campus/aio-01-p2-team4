# AI 마피아 에이전트 행동 유효성 시험 결과 보고서

시험 기준일: 2026-09-09 (기존 2026-09-08 기록은 별도 보존)

보고서 작성일: 2026-09-09  
시험 대상: AI Player Agent의 게임 상태별 행동 선택·제출·검증 결과

## 1. 실험 목적

본 실험은 Agent가 현재 게임 상태에서 허용되지 않은 행동을 선택하거나 잘못된
대상을 제출하는지 확인하는 것을 목적으로 한다. Agent의 자연어 표현력이나 인간과
비교한 추론 능력을 평가하지 않고, 게임의 확정 원장과 Agent 실행 기록을 비교하여
행동의 유효성과 상태 정합성을 측정한다.

핵심 질문은 다음과 같다.

- 현재 phase와 action window에 맞는 행동을 선택했는가?
- actor에게 허용된 Context와 행동 범위만 사용했는가?
- 선택한 대상과 파라미터가 유효한가?
- 오래된 상태나 중복 요청을 잘못 반영하지 않았는가?
- 오류가 발생했을 때 fallback 또는 안전한 실패로 종료했는가?

## 2. 실험 기준과 정답 원장

AI Agent의 행동 1회를 다음 단위로 정의한다.

```text
Agent turn = game_id + actor_player_id + window_id + state_version
```

각 turn의 판정은 다음 정보를 기준으로 한다.


| 확인 정보 | 기준 데이터                                     | 판정 내용                                      |
| ----- | ------------------------------------------ | ------------------------------------------ |
| 게임 상태 | `games`, snapshot·runtime 상태               | 현재 phase·round·state version               |
| 행동 창  | `action_windows`                           | window 종류·차례·마감·허용 상황                      |
| AI 작업 | `agent_jobs`                               | job 종류·예약 version·최종 상태·failure code       |
| 행동 제출 | `action_submissions`                       | action type·actor·target·source·관찰 version |
| 확정 결과 | `action_window_resolutions`, `game_events` | 집계·상태 전이·최종 반영 결과                          |
| 실행 기록 | Agent activity·progress log                | 선택·fallback·실패 단계와 순서                      |


`action_submissions`와 Game Engine의 확정 결과를 게임 상태의 정답 원장으로 본다.
단, 검증 전에 거부된 proposal은 submission 행으로 저장되지 않을 수 있으므로,
거부 시도까지 포함한 오류율은 `agent_jobs`의 terminal 상태와 Agent activity/log를
함께 사용한다.

## 3. 오류 정의

### 3.1 Agent 행동 오류

다음 항목을 Agent 행동 오류율에 포함한다.


| 오류 코드                     | 판정 기준                                         |
| ------------------------- | --------------------------------------------- |
| `INVALID_ACTION`          | 현재 phase·window·role에서 허용되지 않은 action type 선택 |
| `INVALID_TARGET`          | 사망자·자기 자신·다른 게임·권한 밖 대상 선택                    |
| `MISSING_PARAMETER`       | 필수 target·message·ability 등 누락                |
| `FORBIDDEN_TOOL`          | 현재 actor 또는 window에 허용되지 않은 Tool/행동 선택        |
| `CONTEXT_SCOPE_VIOLATION` | actor가 볼 수 없는 private Context 사용 또는 전달        |


### 3.2 Agent 오류와 분리할 운영 오류

다음은 Agent의 게임 판단 오류와 분리하여 별도 집계한다.


| 오류 코드              | 의미                                 |
| ------------------ | ---------------------------------- |
| `STALE_STATE`      | 판단 이후 state version 또는 window가 변경됨 |
| `DUPLICATE`        | 이미 처리된 행동의 재제출                     |
| `PROVIDER_ERROR`   | Provider 응답 실패 또는 timeout          |
| `MCP_ERROR`        | MCP Resource·Tool 연동 실패            |
| `FALLBACK_APPLIED` | 오류 후 결정적 fallback으로 처리 성공          |
| `FAILED`           | 재시도·fallback 이후 안전하게 실패 종료         |


## 4. 평가 지표

### 4.1 허용되지 않은 행동률

```text
(INVALID_ACTION + FORBIDDEN_TOOL) turn 수 ÷ 전체 Agent turn 수 × 100
```

### 4.2 잘못된 대상·파라미터 오류율

```text
(INVALID_TARGET + MISSING_PARAMETER) turn 수
÷ 대상 또는 파라미터가 필요한 전체 turn 수 × 100
```

### 4.3 Context scope 위반율

```text
CONTEXT_SCOPE_VIOLATION turn 수 ÷ Context가 생성된 전체 turn 수 × 100
```

### 4.4 정상 반영률

```text
검증된 Agent action이 APPLIED 된 turn 수 ÷ 전체 Agent turn 수 × 100
```

### 4.5 오류 처리율

```text
(FALLBACK_APPLIED + 안전한 FAILED) turn 수
÷ Provider·MCP·상태 오류가 발생한 전체 turn 수 × 100
```

`STALE`과 `DUPLICATE`는 정상적인 방어 결과일 수 있으므로 정상 반영률에서 제외하고,
잘못 반영된 경우만 실패로 판정한다.

## 5. 시험 시나리오


| ID      | 시험 상황                        | 기대 결과                        |
| ------- | ---------------------------- | ---------------------------- |
| AGT-001 | DAY_DISCUSSION에서 SPEAK 선택    | 유효 proposal 및 제출             |
| AGT-002 | DAY_DISCUSSION에서 PASS 선택     | 허용 조건이면 제출                   |
| AGT-003 | DAY_VOTE에서 생존자 투표            | 유효 target 제출                 |
| AGT-004 | NIGHT_ACTION에서 역할에 맞는 행동     | role·target 검증 후 제출          |
| AGT-005 | 토론 중 VOTE 또는 NIGHT_ACTION 선택 | `INVALID_ACTION` 거부          |
| AGT-006 | 사망자·자기 자신을 target으로 선택       | `INVALID_TARGET` 거부          |
| AGT-007 | 필수 target·message 누락         | `MISSING_PARAMETER` 거부 또는 교정 |
| AGT-008 | actor가 볼 수 없는 Context 접근     | scope 거부·미반영                 |
| AGT-009 | 이전 state version으로 제출        | `STALE`, 상태 미변경              |
| AGT-010 | 같은 window·actor의 재제출         | `DUPLICATE`, 중복 미반영          |
| AGT-011 | MCP 제출 중 오류                  | 제한 재시도 후 fallback 또는 실패      |
| AGT-012 | 저장 후 응답 유실                   | 새 window에 잘못된 재적용 금지         |


위 오류명은 시험 보고서의 **평가 분류**이며 실제 API·Engine·Agent의 오류 코드와
일대일로 일치하지 않는다. 예를 들어 잘못된 phase는 Engine의 `INVALID_PHASE`,
사망 대상은 `TARGET_DEAD`, 금지된 자기 대상은 `SELF_TARGET_INVALID`,
proposal 형식 오류는 `LLM_RESPONSE_ERROR` 또는 최종 `PROPOSAL_INVALID`로 관측한다.
테스트는 해당 계층의 실제 코드와 거부 후 상태를 검사한다.

AGT-002의 PASS 허용 조건은 첫날 낮 이후의 토론이다. 첫날에는 PASS를 거부하거나
SPEAK로 교정해야 한다. AGT-006의 자기 대상 금지는 투표·공격·조사에 적용하며,
의사의 자기 보호는 허용되는 별도 정상 사례다. AGT-011의 현재 구현은 MCP 전송
1회가 실패하면 최초 window·version에 고정한 직접 service fallback을 1회 시도한다.
MCP HTTP 전송 자체를 여러 번 반복하는 재시도 루프가 있다는 뜻은 아니다.

## 6. 현재 시험 결과

### 6.1 2026-09-09 반복 검증 방법과 실행 환경

**AGT-001~012의 83개 변형과 보강 시험 44개 변형을 각각 50회 실행했다.**
총 **6,350회 중 6,296회 통과, 54회 실패, 오류 0회, 건너뜀 0회**이며 pytest 종료
코드는 `1`이다. 실패 54회는 모두 아래 6.3절의 **9인 전원 생존 의사 후보 상한 충돌**이다.
통과로 기대값을 바꾸거나 `xfail`·`skip`으로 제외하지 않았다.


| 항목             | 이번 실행의 기준                                                                              |
| -------------- | -------------------------------------------------------------------------------------- |
| 실행 시각          | 2026-09-09 15:20:52~~15:21:01 KST (06:20:52~~06:21:01 UTC)                             |
| 실행 코드 기준       | `b114078967caff59cea499ed15605431d1d01019`의 런타임, 이번에 추가한 테스트 두 파일                      |
| 환경             | macOS 26.5.2 arm64, Python 3.12.11, pytest 8.4.2, httpx 0.28.1, pydantic 2.13.5        |
| 실행 방식          | pytest 프로세스 1회, `AGENT_REPORT_SAMPLES=50`, 127개 변형 × 샘플 0~49                           |
| 시간             | pytest 보고 9.27초, 실행 프로세스 측정 9.671초; 서비스 성능 측정값은 아님                                     |
| AGT-001~008    | [행동·권한 검증 코드](../../backend/tests/test_agent_report_behavior.py), 46개 변형 × 50 = 2,300회 |
| AGT-009~012·보강 | [오류 회복 검증 코드](../../backend/tests/test_agent_report_recovery.py), 81개 변형 × 50 = 4,050회 |
| 분담             | `run_9d2e2090c49f`에서 두 작업자가 테스트 작성, coordinator가 9인 고정 조건 추가·최종 실행·집계                  |


반복 1회는 **새 fixture로 실제 테스트 함수를 실행한 pytest 항목 1개**다. 하나의
assert 결과를 50배로 늘린 수치가 아니며, 50개 서버 프로세스나 실제 게임 50판을
뜻하지도 않는다. JUnit의 모든 testcase를 읽어 12개 ID의 존재와 각 변형의 샘플
0~49가 정확히 한 번씩 실행됐음을 검산했다. 개발 중 샘플 1개로 실행한 결과와
실패 원인 확인용 단일 진단은 이 6,350회에 합산하지 않았다.

행동 시험은 인원수 6~9명, AI 좌석, 날짜, 생존 후보, 버전, seed, 발언 길이·Unicode와
페르소나 수치를 바꾼다. 9인 의사 고정 재현은 첫날 밤·전원 생존 조건을 유지한다.
회복 시험은 6인 합성 상태의 식별자·seed·버전을 바꾸고 오류 종류·행동·실패 지점을
교차한다. 각 변형의 입력은 통제된 합성 자료이며 독립적인 실제 LLM 응답 표본이 아니다.

실제 실행하는 검증 경계는 다음과 같다.

- proposal 정규화, `AgentOrchestrator`, Context projection·수신자 필터,
`FastMcpGameContextClient`의 binding·Tool allowlist·응답 검증, `GameEngine`.
- 회복 시험의 `PostgresGameRuntime`, 발언·밤·투표 command service,
`TransactionManager`, 기존 제출 복원, receipt 비교와 `AgentActivity`.
- Provider 출력·HTTP 전송·저장소 행·시계·로그 sink는 합성 대역이다. 행동 시험의
제출 목록은 Engine 성공 후 기록한 메모리 증거이며, 회복 시험은 실제 service가
쓰는 행을 메모리에 보관하고 예외 시 복원한다. PostgreSQL SQL·잠금·영속성 자체를
검증한 것은 아니다. 실제 DB·Redis·MCP 서버·유료 LLM 호출은 하지 않았다.

### 6.2 시나리오별 실측 결과

변형별 반복 수는 모두 **50회**다. 표의 통과는 정상 행동의 성공 또는 의도적으로
주입한 잘못된 요청의 정확한 거부·교정·안전한 실패가 기대와 일치했다는 뜻이다.
시도한 잘못된 proposal 수나 실제 게임의 행동 오류율과는 다른 집계다.


| ID         | 검증 변형·핵심 판정                                                     | 변형 수   | 실행        | 통과        | 실패     |
| ---------- | --------------------------------------------------------------- | ------: | ---------: | ---------: | ------: |
| AGT-001    | 일반·1/199/200자·NFC·공백 정리 SPEAK의 실제 제출                            | 6      | 300       | 300       | 0      |
| AGT-002    | 둘째 날 이후 PASS 제출, 첫날 PASS 거부·미변경                                 | 2      | 100       | 100       | 0      |
| AGT-003    | 생존·자기 제외 후보 투표, 실제 표·operation·target 일치                        | 1      | 50        | 50        | 0      |
| AGT-004    | 마피아·탐정·의사 역할 행동 및 9인 의사 고정 재현                                   | 4      | 200       | 148       | **52** |
| AGT-005    | 토론 중 VOTE·NIGHT_ACTION을 proposal·MCP·Engine에서 거부                | 2      | 100       | 100       | 0      |
| AGT-006    | 투표·3개 밤 역할 × 사망·자기·외부 대상; 의사 자기 보호는 정상 기대                       | 12     | 600       | 598       | **2**  |
| AGT-007    | message 누락/null/공백, VOTE·NIGHT target 누락/null의 거부와 1회 교정        | 7      | 350       | 350       | 0      |
| AGT-008    | subject·scope 거부 6종, MCP Context 오염 3종, 3개 phase 비간섭성           | 12     | 600       | 600       | 0      |
| AGT-009    | 3개 제출 phase × version/window 변경, MCP stale Context 2종           | 8      | 400       | 400       | 0      |
| AGT-010    | 3개 행동 receipt 재응답, 투표·밤 행동의 새 key·같은/다른 대상 중복 거부                | 7      | 350       | 350       | 0      |
| AGT-011    | SPEAK/PASS × timeout/503/RPC 오류/잘못된 JSON × fallback 성공/rollback | 16     | 800       | 800       | 0      |
| AGT-012    | 첫날 SPEAK·이후 SPEAK/PASS × commit 후 timeout/잘못된 JSON 응답           | 6      | 300       | 300       | 0      |
| **AGT 합계** | **12개 시나리오**                                                    | **83** | **4,150** | **4,096** | **54** |


모든 행에서 pytest 오류와 건너뜀은 각각 0회다. 각 ID의 실제 테스트 함수는
해당 파일의 `test_agt_001_*`~`test_agt_012_*` 이름으로 연결된다.


| 기존 보고서의 보강 항목                         | 변형                                           | 실행        | 통과        | 실패    |
| ------------------------------------- | -------------------------------------------- | ---------: | ---------: | -----: |
| private batch rollback 후 `APPLIED` 방지 | 두 번째 제출 쓰기·receipt 쓰기 실패 2종                  | 100       | 100       | 0     |
| fallback 사유 보존·다음 시도와 격리              | 허용 사유 10종 × APPLIED/FAILED/SKIPPED           | 1,500     | 1,500     | 0     |
| 민감한 진단 문자열·타입 차단                      | 공개/비공개 phase × 문자열/URL/개행/list/mapping/bytes | 600       | 600       | 0     |
| **보강 합계**                             | **44개 변형 × 50회**                             | **2,200** | **2,200** | **0** |


추가로 확인된 해석상의 주의점은 다음과 같다.

- AGT-009의 이전 버전은 `409 STALE_STATE_VERSION`, 이전 발언 창은
`409 ACTION_NOT_ALLOWED`, 이전 투표·밤 창은 `409 WINDOW_CLOSED`다.
MCP의 이전 Context binding은 `STALE/STALE_STATE_VERSION`으로 종료되고
Provider·Tool 호출 없이 `SKIPPED`를 남긴다.
- AGT-010의 같은 key·body는 첫 receipt와 `replayed=True`를 반환한다. 새 key의
같은 window·actor 재제출은 실제 Engine의 `DUPLICATE_ACTION`을 거쳐
`409 ACTION_ALREADY_SUBMITTED`가 되고 첫 target을 보존한다.
- AGT-011은 MCP 전송 1회와 직접 fallback 1회를 확인했다. fallback 성공 400회와
저장 실패 후 rollback·`FAILED` 400회가 모두 기대를 충족했다. 후자의 API 오류는
`503 DEPENDENCY_UNAVAILABLE`이며, 두 경로 모두 `MCP_SUBMISSION_FAILED` 사유를 보존했다.
- AGT-012는 **첫 제출이 commit됐어도 activity가 `FAILED`일 수 있음**을 300회
확인했다. 응답 유실 후 직접 fallback은 이전 버전에서 거부되고, submission·receipt는
각 1개만 남는다. 새 window에는 다시 적용하지 않으며 `APPLIED`를 추측해서 기록하지
않는다. 따라서 activity의 terminal 상태만으로 실제 적용 건수를 계산하면 안 된다.

### 6.3 실패 원인: 9인 전원 생존 의사의 유효 후보 상한 충돌

정상적인 **9인·첫날 밤·전원 생존·의사** 상태에서 Backend는 자기 자신을 포함한
유효 대상 9명을 만든다. 하지만
[`FastMcpGameContextClient`](../../backend/app/mcp/client.py)의 Context 검증은
`len(targets) > 8`을 거부한다. 마스터플랜의 의사 자기 보호 규칙 및
[`_actor_target_ids`](../../backend/app/services/game/actor_context.py)의 대상 산출과,
API 명세 8.2.3의 `valid_targets` 최대 8개 제한이 충돌한다.


| 재현 테스트                                                                 | 실행  | 통과  | 실패  | 조건                              |
| ---------------------------------------------------------------------- | ---: | ---: | ---: | ------------------------------- |
| `test_agt_004_nine_living_doctor_can_submit_self_protection`           | 50  | 0   | 50  | 모든 표본을 9인·첫날 밤·전원 생존·의사로 고정     |
| `test_agt_004_role_night_action_is_checked_and_submitted`의 DOCTOR      | 50  | 48  | 2   | `sample-15`, `sample-35`가 같은 조건 |
| `test_agt_006_target_rejection_and_doctor_self_exception`의 self-DOCTOR | 50  | 48  | 2   | `sample-15`, `sample-35`가 같은 조건 |


JUnit의 54개 실패 모두 정상 기대 `SUCCEEDED`와 실제 `FALLBACK`의 불일치다.
별도의 단일 원인 진단에서도 생존자 9명·후보 9명·자기 포함을 확인한 뒤 실제 client가
`MCP_CONTEXT_CONTRACT`를 반환했다. Orchestrator 결과는
`status=FALLBACK`, `failure_code=MCP_UNAVAILABLE`, `proposal=null`이었으며
Provider 호출·Tool 제출·합성 submission은 각각 0회였다.

이는 잘못된 모델 선택이 아니라 **정상 Context가 모델 호출 전에 거부되는 계약 문제**다.
이 결과로 전체 runtime의 후속 밤 fallback이나 실제 게임의 진행 불가까지 판정하지는
않는다. 이번 작업은 검증·보고이므로 런타임이나 API 상한을 수정하지 않았으며,
해당 실패를 남기는 테스트를 보존했다. 후속 수정에서는 제품 규칙·API 대상 상한·client
검증을 함께 일치시켜야 한다.

### 6.4 재현 명령과 증거

저장소 루트의 기존 `.venv`에서 실행한다. 테스트마다 새 상태를 만들며 추가 반복
plugin이나 DB 설정이 필요하지 않다. 이 코드 기준에서는 위 54회 실패로 종료 코드
`1`이 나오는 것이 이번에 관측한 결과다.

```bash
AGENT_REPORT_SAMPLES=50 PYTHONPATH=. .venv/bin/python -m pytest \
  backend/tests/test_agent_report_behavior.py \
  backend/tests/test_agent_report_recovery.py \
  -q --tb=short --junitxml=/tmp/agent-report-results.xml
```

9인 의사 문제만 재현하는 명령은 다음과 같다. 이번 전체 실행에도 이 시험 50회가
포함돼 있으며 별도 반복 실행 수로 중복 계산하지 않았다.

```bash
AGENT_REPORT_SAMPLES=50 PYTHONPATH=. .venv/bin/python -m pytest \
  backend/tests/test_agent_report_behavior.py \
  -q -k nine_living_doctor
```

실제 실행의 JUnit·stdout·메타데이터·집계·실패 trace·원인 진단은 아래 로컬 임시
디렉터리에 보존했다. 임시 파일이 삭제되면 위 명령으로 다시 생성할 수 있으며,
저장소에는 테스트 소스와 이 보고서의 집계 결과를 보존한다.

```text
/var/folders/27/swbczwzn3375q7x_47v534zc0000gn/T/agent-report-validation-20260909-w1emxpwt/
  results.xml                 # 6,350개 testcase의 실제 결과
  pytest.log                  # pytest 출력과 실패 목록
  execution.json              # 실행 시각·명령·기준 commit·파일 hash
  summary.json                # AGT 및 테스트 함수별 결과
  variant-counts.json         # 127개 변형 각각 50회 검산 결과
  failures.json               # 실패한 세 테스트 함수와 각 traceback
  doctor-nine-diagnostic.json # 후보 9개 거부와 호출·제출 0회 확인
```


| 증거                              | SHA-256                                                            |
| ------------------------------- | ------------------------------------------------------------------ |
| `test_agent_report_behavior.py` | `a51126a7ff0d5bc042173ad2d1f570b82f80581da24b67334c91ca78ef225c7c` |
| `test_agent_report_recovery.py` | `b8ac405705bd0ac6f8cd32f9ce68d5abda4a0eb04736c0f358b69258792f166d` |
| `results.xml`                   | `49d034710050d638063563e6006ad1d572d1e5f70bc6222e979a9bee17d4762b` |


추가 정적 검증으로 새 두 파일의 Ruff `E9,F`를 통과했다. 문서·링크·diff도 확인했다.
외부 서비스 통합·실제 게임 완주·실제 DB turn 집계는 이번 합성 시험에서 수행하지
않았다. 삭제된 Backend·MCP 과거 전체 회귀와 무관한 Front 회귀도 생략했다.

### 6.5 기존 Agent focused 시험 기록 (이번 반복 수에 미포함)

이번 반복 검증 이전 기록상 B6 Agent 진행·로그·proposal·fallback 관련 focused 시험 48개가
통과했다. 이후 rollback 후 미제출 job의 저장 proposal 재사용과 격리 SQL을 포함한
후속 시험 40개도 통과했다. UTC Context projection parser 보완 후 관련 focused
시험 47개도 통과했다.

이 과거 수치는 구현 작업별 focused 결과이며 서로 중복될 수 있다. 따라서 Agent 행동
오류율의 분모·분자를 의미하는 실제 turn 집계와는 구분한다.

### 6.6 기존 행동 유효성·상태 방어 기록

다음은 기존 구현 작업의 판정이다. 이번 반복 검증의 판정은 6.2~6.3절을 우선하며,
아래의 과거 통과 기록으로 9인 의사 예외까지 통과했다고 해석하지 않는다.


| 평가 항목                     | 현재 판정 | 근거                                         |
| ------------------------- | ----- | ------------------------------------------ |
| proposal 형식·행동 검증         | 통과    | Agent proposal 및 action service focused 시험 |
| actor·game·window binding | 통과    | reservation·binding·scope 시험               |
| stale 상태 거부               | 통과    | state version·window 변경 시험                 |
| duplicate 처리              | 통과    | 동일 action 재처리 시험                           |
| MCP 제출 실패 fallback        | 통과    | synthetic MCP 실패 시험                        |
| 저장 후 응답 유실 방어             | 통과    | 새 window 오적용 방지 시험                         |
| rollback 후 `APPLIED` 방지   | 통과    | private batch rollback 시험                  |
| fallback 사유 보존            | 통과    | activity reason/source 시험                  |
| 민감한 진단 문자열 차단             | 통과    | activity 입력 검증 시험                          |


### 6.7 기존 실제 게임 실행 확인 (이번에 재실행하지 않음)

격리 환경의 Dummy Provider 기반 8인 게임에서 최종 지목까지 진행하여
`COMPLETED`/`ENDED` 상태에 도달했다. 해당 실행에서 AI 89회의 실행 기록에
`STARTED → CONTEXT_READY → DECIDING → DECIDED → APPLIED` 순서가 남았다.

이 결과는 정상 실행 경로와 게임 원장 연결을 확인한 것이다. 해당 실행에는
`FALLBACK`·`FAILED`가 없었으므로, fallback의 실제 게임 발생률을 의미하지 않는다.
fallback과 오류 회복은 synthetic focused 시험 결과로 별도 확인했다.

## 7. DB 결과 집계 방법

실제 오류율을 산출할 때는 게임별·window별·actor별로 다음 순서로 집계한다.

1. `agent_jobs`에서 AI Player job의 terminal 결과를 추출한다.
2. `game_id`, `player_id`, `window_id`, 예약 state version으로 당시 게임 상태와 연결한다.
3. `action_windows`에서 phase, window kind, turn과 마감 조건을 확인한다.
4. `normalized_result` 또는 activity에 기록된 action type·target을 확인한다.
5. `action_submissions`의 `source=AGENT` 행과 연결한다.
6. `game_events`·`action_window_resolutions`에서 실제 확정 반영 결과를 확인한다.
7. 기대 허용 행동·유효 대상과 Agent 결과를 비교한다.
8. 오류 코드를 분류하고 위 지표를 계산한다.

최소 연결 키는 다음과 같다.

```text
game_id + window_id + player_id + reserved_state_version
```

동일 키에 재시도·fallback이 여러 번 존재할 수 있으므로 attempt 또는 job ID를
함께 사용한다. 최종 상태만 보고 판단하지 않고, 첫 proposal이 잘못되었는지와
fallback 이후 최종 반영되었는지를 분리한다.

## 8. 결과 기록 표준

6.2절은 이번에 실행한 합성 테스트의 정량 결과다. 아래 표는 별도 모집단인 실제
DB의 Agent turn 지표이므로, 합성 시험의 통과·실패 수로 채우지 않는다. 이번 작업에서는
실제 DB turn을 조회·집계하지 않았으며 DB 집계를 완료한 뒤 이 표를 갱신한다.


| 지표                  | 오류·결과 건수 | 전체 건수 | 비율  | 산출 근거                             |
| ------------------- | --------: | -----: | ---: | --------------------------------- |
| 허용되지 않은 행동률         | 미집계      | 미집계   | 미집계 | `agent_jobs` + activity           |
| 잘못된 대상 오류율          | 미집계      | 미집계   | 미집계 | proposal + `action_submissions`   |
| 필수 파라미터 오류율         | 미집계      | 미집계   | 미집계 | proposal validation 결과            |
| Context scope 위반율   | 미집계      | 미집계   | 미집계 | Context projection trace          |
| 정상 반영률              | 미집계      | 미집계   | 미집계 | `action_submissions` + resolution |
| fallback 처리율        | 미집계      | 미집계   | 미집계 | `agent_jobs.status`               |
| stale·duplicate 방어율 | 미집계      | 미집계   | 미집계 | job status + receipt              |


현재 저장소는 재실행 가능한 반복 시험과 기존 focused·특정 게임 실행 결과를 보존하지만,
모든 실제 Agent turn을 위 지표로 자동 집계한 표본 리포트는 아직 생성하지 않았다.
따라서 위 표의 “미집계”를 임의의 성공률로 바꾸지 않는다.

## 9. 실험의 한계

- 127개 변형을 각각 50회 실행한 결과는 통제된 입력의 반복 증거다. 실제 서비스의
장애 발생률·LLM 오류율·통계적 독립성 또는 미시험 입력의 정확도를 나타내지 않는다.
- 이번 범위는 STANDARD의 DAY_DISCUSSION·DAY_VOTE·NIGHT_ACTION이다. 재투표·최종
지목·CUSTOM_ROLE 전체 조합이나 밤/투표 해소 이후의 게임 전체 완주를 시험하지 않았다.
- 합성 저장소의 rollback은 실제 service가 부분 성공을 표시하지 않는 경계를 검사한다.
실제 SQL fencing·unique 제약·다중 연결 경합·재시작 후 내구성의 검증을 대체하지 않는다.
- AGT-004·006의 9인 의사 경계는 실패 상태로 남아 있다. 한 가지 원인의 반복 실패를
서로 다른 54개 결함으로 세거나 실제 LLM 판단 오류 54건으로 해석하지 않는다.
- Fake·Dummy Provider 중심이므로 실제 LLM의 Tool 선택·자연어 추론 품질은 측정하지 않았다.
- 성찰 루프 적용 전후를 동일 데이터셋으로 비교한 baseline은 확보하지 않았다.
- 8인 게임 1회의 정상 완주는 장기 전략과 전체 서비스 안정성을 보장하지 않는다.
- `action_submissions`에 저장되지 않은 검증 전 proposal은 activity·job 기록이 없으면 DB만으로 복원할 수 없다.
- 오류율 산출을 위해서는 모든 Agent 시도에 안정적인 job·attempt·proposal 연결이 필요하다.

## 10. 결론

AGT-001~012 모두 최소 50회 이상 검증했으며, 보강 항목을 포함한 127개 변형을
각각 50회 실행했다. **총 6,350회 중 6,296회 통과·54회 실패**로, 9인 전원 생존
의사의 정상 Context가 대상 상한 때문에 거부되는 계약 충돌을 확인했다. 이 조건의
고정 시험은 50회 모두 실패했으므로 전체 통과로 판정할 수 없다.

시험한 stale·duplicate·MCP 제출 장애·응답 유실·rollback 경로에서는 중복 적용과
잘못된 성공 기록을 방지했다. 응답 유실 시 원장에는 적용됐어도 activity는 `FAILED`로
남을 수 있으므로 실제 지표는 `agent_jobs`, activity, `action_submissions`,
`game_events`를 함께 연결해야 한다. 실제 LLM의 추론 정확도와 실제 DB turn의
행동 오류율은 이번 합성 시험 수치로 단정하지 않는다.

## 11. 근거 문서

- [AGT-001~008 반복 검증 코드](../../backend/tests/test_agent_report_behavior.py)
- [AGT-009~012·보강 반복 검증 코드](../../backend/tests/test_agent_report_recovery.py)
- [제품 규칙·WU 마스터플랜](../개발상세플랜/01_core/AI_MAFIA_MASTER_PLAN.md)
- [API 명세: Context·행동 제출 계약](../개발상세플랜/01_core/AI_MAFIA_API_SPEC.md)
- [Agent 아키텍처 설계서](06_AGENT_ARCHITECTURE_DESIGN.md)
- [전체 시스템 아키텍처 설계서](AI_MAFIA_SYSTEM_ARCHITECTURE_DESIGN.md)
- [DB·Redis 설계서](01_DB_REDIS_DESIGN.md)
- [게임 테스트 공백·재점검 보고서](../개발상세플랜/05_reports/AI_MAFIA_GAME_TEST_GAP_REPORT.md)
- [병렬 투표 버그 보고서](../개발상세플랜/05_reports/AI_MAFIA_PARALLEL_VOTE_BUG_REPORT.md)

