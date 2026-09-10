# 게임 생애주기·투표·정리 변경 이력 (2026-09-07 ~ 2026-09-08)

루트 README의 변경 기록에서 옮긴 문서입니다. 저장·재개·수동 삭제·뒤로가기 흐름,
승패 원장 검토와 병렬 투표 수정, WU-B15 stale 게임 자동 정리(migration 007)를
다룹니다.

## 승패·투표 원장 검토 (완료 게임 복기)

같은 게임의 승패·투표 원장 검토 결과는 다음과 같습니다. 투표 실행 문제는 아래 후속
병렬 투표 수정에 반영했고, 승패·최종 처형 상태 문제는 검토만 했습니다.

- 마피아는 3·5번이었고, 다섯 번째 밤 이후 최종 지목에서 시민 7번이 선택되어
`MAFIA / FINAL_NON_MAFIA_SELECTED`로 종료됐습니다. 현재 최대 5밤 규칙과 일치합니다.
- **AI 투표 45표 중 28표가 AUTO**였습니다. 1라운드 일반·재투표는 AI 생성 작업 없이
자동 선택됐고, 3라운드 일반·재투표는 일부 모델 응답이 마감 전에 완성돼도 batch에
반영되지 않았습니다. 인간 표가 있어야 AI를 시작하는 조회 조건과 순차 생성 후 전체
batch 저장 구조가 원인이었습니다. 파라미터 상향과 별도로 실행 구조를 수정했습니다.
- 최종 지목은 7번의 `PLAYER_EXECUTED` 이벤트를 발행하지만 엔진이 생존 상태를 바꾸지
않아 DB의 `alive=true`와 처형 표시가 불일치합니다. 승리 진영 계산에는 영향이 없으나
결과 화면의 상태·생존자 수 정합성을 정리해야 하는 미수정 사항입니다.
- 9번의 ‘2라운드에 6번 투표’ 발언은 실제 3번 투표와 달랐습니다. 자기 과거 투표가
context에 없는데 발언으로 만들어 낸 사례여서, 공개 득표만으로 개인 표를 추정하지
않도록 지침을 보완했습니다. 5번은 실제 마피아이므로 의도적인 혼란 유도와 시민의
기억 오류를 같은 성향 수치로 평가하지 않습니다.

이번 조정은 자동 테스트·추가 유료 게임 없이 소스·완료 게임 원장·설정 저장값을
확인했습니다. 새 값의 실제 대사·승률 개선은 아직 측정하지 않았습니다.

## 일반·재·최종 투표 병렬화

일반 투표·재투표·최종 지목은 window 시작부터 모든 미제출 AI가 병렬로 판단하고,
완료된 표부터 개별 저장합니다. 사용자 투표를 기다리지 않으며 다른 AI의 실패로
이미 저장된 표를 취소하지 않습니다. 투표 scheduler는 발언·밤 호출과 분리했고,
command commit이 새 투표 조회를 깨웁니다. 미해소 AI 표는 공개 버전·event를 올리지
않으며 인간이 같은 window에 첫 표를 제출한 경우의 한 버전 증가만 원장으로 검증해
허용합니다. 마지막 제출·마감에서만 결과를 해소하고, deadline에는 미제출자만 자동
선택합니다. 적용에는 Backend 재시작이 필요하며 새 환경 변수·migration은 없습니다.
재현 조건·원인·해결 과정·실행 확인은
[AI 병렬 투표 버그 리포트](../05_reports/AI_MAFIA_PARALLEL_VOTE_BUG_REPORT.md)에 기록합니다.
실제 로컬 9인 게임의 두 일반 투표에서 AI 7명·6명이 각각 0.141초·0.105초 간격 안에
판단을 시작했습니다. 인간이 AI 전원 제출 뒤 투표한 경우와 AI 판단 도중 제출한 경우 모두
AI 합계 13표가 AGENT로 저장됐고 AUTO는 0표였습니다. Frontend 화면도 확인한 뒤
게임을 저장했습니다. 자동 테스트·lint·전체 회귀와 별도 장애 주입은 생략했습니다.

## snapshot·sync·worker 복원 구조

최종 토론 snapshot도 현재 speech 제출 원장과 함께 복원됩니다.
PostgreSQL sync의 공개 event와 action window payload도 Frontend 정본 구조로 변환됩니다.
worker는 한 게임의 진행 오류가 다른 게임의 AI 진행을 막지 않도록 격리합니다.
순수 규칙 엔진은 기존 `GameEngine` facade를 유지하면서 플레이어 검증·사망 처리·
표준 승패·토론 입력·밤 역할 판정·투표 집계·replay 분기를
`backend/app/game_engine/` 모듈로 이동했습니다. 실제 `GameEngine`, deterministic
fallback, phase 전이 구현은 해당 package가 소유합니다. 기존 `agent/game_engine.py`, `fallback.py`, `state_machine.py`, `agent/rules/`는
모든 호출부를 새 정본으로 전환한 뒤 제거했습니다.
게임 API runtime은 router 전역 변수가 아니라 앱별 `app.state.game_runtime`에
주입되며, 테스트 앱과 운영 앱의 상태가 서로 공유되지 않습니다. PostgreSQL 실행
계층의 phase별 다음 행동 순서는
`backend/app/services/game/turn_order_service.py`가, 행동 제한 시간과 deadline은
`backend/app/services/game/action_timer_service.py`가 각각 담당하도록 분리하는
구조를 사용합니다. `window_service.py`는 두 결과를 기존 `ActionWindowInsert`로
조합하는 얇은 adapter로만 유지합니다. DB/API의 기존 `action_windows` 명칭은 저장
계약 호환을 위해 유지합니다. 현재 실제 구현 상태와 실행 경로는
[AI_MAFIA_CURRENT_CODE_STATUS.md](../05_reports/AI_MAFIA_CURRENT_CODE_STATUS.md)에 기록합니다.
AI worker의 시작·종료는 FastAPI lifespan에서 앱별 runtime과 함께 관리합니다.
중앙 worker는 runtime facade의 AI 차례 조회·실행 메서드만 호출하며 PostgreSQL
transaction이나 Repository를 직접 소유하지 않습니다.
게임 실행 command의 공개 조합 경계는 `command_service.py`와
`lifecycle_service.py`, 실제 transaction은
`action_command.py`, `discussion_command.py`, `agent_discussion.py`, runtime 조합은
`postgres_runtime.py`가 담당합니다. 생성 transaction은
`services/game/creation_service.py`, 게임 목록·snapshot 조회와 순수 공개 projection은
`services/game/game_read_service.py`, DB row 변환은
`services/game/game_read_service.py`가 함께 담당합니다. event 조회·sync envelope와
event row의 Front operation 변환은 `services/game/event_sync_service.py`에 둡니다.
기존 `snapshot_service.py`와 `sync_service.py`는 전환 기간에만 호환 re-export로
유지할 수 있습니다. 별도 projection 파일은 만들지 않습니다.
`event_outbox`는 PostgreSQL event의 전달 원본으로 transaction에서 enqueue하며,
`services/outbox_service.py`의 publisher가 Redis fan-out을 담당합니다. 현재
publisher worker 자동 기동은 연결하지 않고, Redis 장애 시 DB 원본과 재처리 경계를
유지합니다.
MCP registry와 관리자 API 계약 테스트는 게임 실행 runtime과 분리된 synthetic
adapter를 사용하며, 실제 게임 흐름은 PostgreSQL 정본 경로를 사용합니다.
완료 게임 결과 projection은 `services/game/result_service.py`가 담당합니다. sync 조회와
snapshot 변환은 새 모듈로 이동했으며, 생성 seed·시나리오·persona·단서 조합은
`creation_service.py`, BEGIN_GAME·SAVE_AND_EXIT·RESUME transaction orchestration은
`lifecycle_service.py`가 담당합니다. 기존 API 호환을 위한 facade 클래스는
`game_service.py`에 유지합니다.
`FINAL_DISCUSSION` snapshot에서 발언용 `legal_actions`와 `SPEECH` window가 누락되어
마지막 토론이 멈추던 문제도 수정했으며, 서버를 종료한 상태의 PostgreSQL 전체 흐름
smoke 4개가 통과했습니다.
또한 밤 공격 후 메모리 상태만 변경되고 `game_players.alive`에 저장되지 않던 문제를
수정해, 마피아 공격 결과가 다음 snapshot에도 유지되도록 했습니다.
Frontend SSE bridge는 실제 변경이 있는 `envelope`와 제한된 진행 확인 tick을
Streamlit component state로 전달합니다. 현재 cursor를 그대로 돌려주는 no-op 응답은 폐기하며,
응답 stream이 종료되어도 마지막 `last_sequence`부터 자동 재연결해 phase 전환을
반영합니다. Backend `/events`는 연결을 유지하면서 변경 batch만 push하고 15초
간격 heartbeat만 보내므로, 변경 없는 stream 데이터가 페이지를 반복 rerun하지 않습니다.
Backend 중앙 AI worker는 만료된 밤·일반/재/최종 투표 window도 조회합니다.
이미 제출된 선택은 보존하고 무응답만 결정적 자동 선택으로 채워 해소합니다.
게임 command Front guard는 입력 형식만 정규화하고, 현재 phase·turn·window·대상
허용 여부는 Backend가 최신 transaction에서 최종 확인합니다.

## 수동 삭제·뒤로가기·저장 (WU-F 연계)

홈을 제외한 새 게임 설정·생성 완료·역할 공개·게임 진행·결과·일반 및 게임별 피드백
화면에는 공통 `뒤로가기` 버튼이 표시됩니다. 진행 중인 역할 공개·게임·관전 화면에서
누르면 `저장하고 나가기 / 게임 삭제 / 계속 플레이` 팝업이 자동으로 열립니다.
팝업을 닫거나 계속 플레이를 선택하면 게임 화면에 남으며, 화면 갱신 중에도 선택 전까지
팝업을 유지합니다. 저장은 `SAVE_AND_EXIT`로 서버의 마지막 확정 상태를 저장하고, 삭제는 해당 게임의
진행 상황과 기록을 복구할 수 없다는 안내 후 선택한 경우에만 실행합니다.

수동 삭제는 `DELETE /api/v1/games/{game_id}?expected_state_version=<확인한 버전>`을
사용합니다. Backend는 `X-User-Id` 소유권·버전·진행/저장 상태를 게임 행 잠금 안에서
검증하며, 기존 FK cascade로 종속 기록을 함께 삭제합니다. 새 migration은 없습니다.
성공 후 홈으로 이동하고 게임 cache와 목록을 새로 읽습니다. 실패·응답 유실은 화면에
남아 같은 대상·버전으로 재확인하며, 버전 변경은 최신 화면에서 다시 선택해야 합니다.
유실 뒤 같은 삭제 요청의 `GAME_NOT_FOUND`도 홈으로 이동합니다. 다른 사용자 게임과
완료·실패 게임은 삭제할 수 없습니다. 이 API를 사용하려면 Backend도 변경 코드로
실행해야 합니다.

저장은 화면의 상태 버전이 서버와 일치하지 않아도 진행합니다. 예를 들어 화면은 버전
27이고 서버에서 29까지 확정됐다면 29의 진행 상황을 저장하고 저장 결과 버전 30을
반환합니다. 확정된 발언·행동·결과는 보존하며, 작성 중인 입력이나 아직 처리 중인
AI 응답은 포함되지 않을 수 있습니다. 저장 후 도착한 이전 AI 응답은 적용하지 않습니다.
시간은 게임·행동 창 잠금을 얻은 뒤 계산하므로 잠금 대기 시간이 남은 시간에 더해지지
않습니다. 동일 요청 재시도는 최초 저장 결과를 유지합니다. 이 버전 일치 예외는 저장에만
적용하며 재개·발언·투표·삭제의 기존 검증은 유지합니다. 새 migration은 없습니다.

저장 버전 제약 완화 검증(2026-09-08): 관련 검사 7건이 통과했습니다. 합성 데이터만
사용한 임시 PostgreSQL에서 오래된 버전 저장, 확정 발언 보존, 늦은 AI 응답 거부,
잠금 대기 중 확정된 버전의 저장, 멱등 재전송·재개와 소유권 거부를 확인했습니다.
전체 회귀는 통합 가상환경의 Backend `848 passed / 14 failed / 11 skipped`, 사용자
Frontend `412 passed / 7 failed`입니다. 남은 실패는 기존 Agent 대역 누락 필드·MCP
응답·계층 경계 검사와 UI 문구·버튼 기대값 불일치이며 수정하지 않았습니다. 별도 QA
설정을 요구하는 11건과 유료 모델 검증은 생략했고, 검증용 임시 DB는 종료했습니다.

이미 저장된 게임·결과와 일반 화면의 뒤로가기는 검증된 앱 내부 방문 기록을 따르고
기록이 없으면 홈으로 이동합니다. 일반 홈 이동은 진행 게임·작성 중 입력과 결과 불명
요청을 보존하고 홈 목록 cache만 무효화합니다. 뒤로가기 버튼은 모바일에서도 유지됩니다.

2026-09-08 뒤로가기 팝업 검증: 추가 회귀 33건이 통과했습니다. Streamlit AppTest로
역할 공개·진행·관전의 팝업 유지·취소·저장·삭제·재시도·후속 404 복구를 확인했습니다.
별도 임시 PostgreSQL에는 합성 게임만 생성해 소유권·버전 거부, 실제 FK 연쇄 삭제,
다른 게임·사용자 보존, 게임 행 잠금 경쟁과 삭제 후 장애 rollback을 검증하고 정리했습니다.
전체 회귀는 Front `411 passed / 7 failed`, Backend `842 passed / 15 failed / 11 skipped`입니다.
Front 실패는 기존 타이머·최종 지목 문구·UUID 교체·결과 새 게임 버튼 기대값 불일치이며,
Backend 실패는 기존 Agent 대역의 누락 필드, MCP 응답·계층 경계 검사와 Backend
가상환경의 Streamlit 미설치입니다. 요청 범위 밖의 실패는 수정하지 않았습니다.
11건은 별도 QA 설정을 요구하는 기존 테스트이며, 유료 모델 호출과 실제 사용자 데이터
검증은 생략했습니다. 이번 변경의 주요 검증 파일은
`frontend_user/tests/test_view_models_f3.py`, `frontend_user/tests/test_api_client.py`,
`backend/tests/test_b3_infrastructure.py`, `backend/tests/test_b5_game_api.py`입니다.

## WU-B15: 15분 무동작 진행 게임 자동 정리 (migration 007)

성공한 USER command receipt 시각 또는 생성 시각으로 초기화합니다. 보정 중에는 같은 DDL
transaction에서 게임 갱신 트리거만 잠시 끄고 복구하여 기존 `updated_at`을 보존합니다.
Backend 새 코드를 기동하기
전에 007을 적용해야 하며, DML runtime 계정에는 `games.last_user_action_at` UPDATE와
`games` DELETE 권한이 필요합니다. 종속 테이블 직접 DELETE 권한은 요구하지 않고 FK
cascade를 사용합니다. 삭제된 게임의 command receipt도 정리되므로 해당 생성 요청의
`Idempotency-Key`는 게임이 삭제된 뒤에는 새 게임 생성으로 처리됩니다.

**팀 DB 적용(2026-09-08, WU-B15):** 사용자 요청에 따라 `TEAM_DATABASE_URL`의 `4team_db`에
007을 적용했습니다. 대상·소유권·DDL/DML 권한을 검증한 기존 계정으로 실행했으며, 권한이나
접속 설정은 변경하지 않았습니다. 적용 시점 게임 157개의 기존 모든 컬럼 값과 `updated_at`을
보존했고, 마지막 사용자 동작 시각 보정 불일치는 0건입니다. 재실행의 무변경성과 NOT NULL·
CHECK·부분 index·갱신 트리거 정상 상태를 확인했습니다. migration 자체는 게임을 삭제하지
않으며, 적용 직후 15분 무동작 진행 게임 후보는 66개였습니다.

팀 DB에서 새 합성 사용자·게임을 사용하는 생성·시작·저장·재개·AI PASS와 사용자 동작 시각
검증 5개가 통과했고, 해당 테스트 사용자·게임은 종료 시 삭제했습니다. 격리 PostgreSQL에서는
15분 경계·연쇄 삭제·잠금 경합·rollback·migration 재실행을 확인했습니다. 루트 가상환경의
Backend 전체 회귀는 **830 통과·기존 14 실패·11 건너뜀**입니다. 기존 실패는 Agent activity
대역의 설정·상태 누락, Agent/Redis/SQL 계층 경계와 MCP context 대역 문제입니다.
건너뛴 테스트는 명시적 QA 환경이 필요한 Agent SQL 8개와 발언 분석 통합 3개입니다.
Front·MCP 전체 회귀와 유료 모델 호출은 이번 DB 변경과 무관하여 생략했습니다.

팀 DB smoke 검증 명령(합성 테스트 데이터 생성·정리 포함):

```bash
LLM_PROVIDER=dummy SPEECH_ANALYSIS_ENABLED=false PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  .venv/bin/python -m pytest -p pytest_asyncio.plugin -p anyio.pytest_plugin \
  backend/tests/test_postgres_game_flow.py -q
```

자동 정리는 WU-B15 Backend의 다음 기동부터 시작합니다. 공유 DB의 모든 Backend instance도
같은 코드로 갱신해야 합니다. 구버전은 사용자 동작 시각을 기록하지 않으므로 혼합 배포하면
활동 중인 게임을 만료로 오인할 수 있습니다. 이번 migration·테스트에서는 상시 서버를
기동하거나 기존 게임에 정리 sweep을 실행하지 않았습니다.

## 브라우저 게임 1회 검증과 후속 수정 (2026-09-07)

후속 수정은 [보고서 8절](../05_reports/AI_MAFIA_GAME_TEST_GAP_REPORT.md#8-수정권고-반영과-ai-진행-표시)에
기록합니다. UUID 초기 응답 전 API 요청을 막고 localStorage 복구 확인 뒤 사용자 scope를
교체하며, 홈 목록 cache와 UUID 표시를 함께 초기화합니다. 새 게임은 성공 직후 실제
참가자 이름이 있는 완료 화면으로 이동하고 이전 생성 결과를 재사용하지 않습니다.
홈은 최신 20개에서 상태별 최대 3개를 표시하고 수동 새로고침·홈 이탈·30초 경과 뒤
다음 진입에서 목록을 갱신합니다. TTL이 만료돼도 기존 카드와 홈·설정 입력을 먼저
처리하고 홈에 남아 있을 때만 목록을 조회하므로 첫 클릭이 사라지지 않습니다.
일반 피드백도 홈 버튼에서 열 수 있습니다.

진행 로그는 저장소 루트에서 다음 명령으로 순서대로 확인할 수 있습니다.

```bash
tail -f backend/logs/game-progress.log
```

`STARTED → CONTEXT_READY → DECIDING → DECIDED → APPLIED`가 정상 AI 처리 흐름이며,
기본 행동·오류·중복은 `FALLBACK`·`FAILED`·`SKIPPED`로 구분합니다. dummy Provider는
고정 행동임을 설명에 표시합니다. 공개 발언 진행 표시는 게임당 최근 50건, 최대
128게임의 메모리에 한정하고 서버 재시작 시 비워집니다. 영구 게임 이력은 DB의
공개 이벤트와 확정 행동 원장에서 복원합니다.

Agent가 선택을 마쳤어도 실제 행동 저장에 실패하면 같은 게임·window·version의
미제출 작업만 lease 반환 또는 만료 후 재시도합니다. 저장된 선택은 Provider를 다시
호출하지 않고 검증해 사용하며, 이미 제출된 행동이나 지난 window에는 적용하지 않습니다.

이번 수정 검증은 기존 데이터와 분리한 임시 PostgreSQL에서 진행했습니다. 검증용
사용자 화면은 [http://127.0.0.1:18501](http://127.0.0.1:18501), 관리자 화면은 [http://127.0.0.1:18502](http://127.0.0.1:18502)이며,
Backend/MCP는 각각 18000/18100 포트입니다. 모두 loopback에서 실행하고 dummy Provider를
사용합니다. 임시 DB는 `team4-game-qa-20260907` 컨테이너이며 종료 시 데이터가 사라집니다.
실제 `.env`·secrets·운영 계정·keyring은 변경하지 않았습니다. 기존 설정을 사용하는
8000/8100 Backend·MCP도 수정 코드와 dummy Provider로 재시작했으며, 일반 사용자
접속 포트는 8501입니다. 대량 테스트와 migration은 격리 QA DB에서만 실행했습니다.

처음 실행한 6인 게임의 발견 사항은 보고서 7절에 보존했습니다. 수정 후에는 별도의
**8인·인간 시민 게임**에서 생성·발언·저장·재개·투표·사망 후 관전·최종 지목·피드백을
진행했습니다. 낮 6일차/라운드 5의 최종 지목 실패로 마피아 승리가 확정됐고, 밤 기록
5개·투표 기록 5개·공개 이벤트 83개가 결과에 남았습니다. 결과에서 새 6인 게임을
만들어 탐정 조사 표시·저장 재개·사망 후 빠른 진행 선택과 종료도 확인했습니다.
탐정 결과는 본인 정보 영역에서 이름·밤 번호·마피아 여부로 표시합니다. 결과의
마지막 투표 표시는 해당 투표의 round/phase를 사용하며 실제 종료 원인과 구분합니다. 실제 LLM 품질이나 모든
역할의 사람 입력을 이 한 판에서 검증한 것은 아닙니다.

2026-09-07에는 같은 격리 환경의 Orca 내장 브라우저에서 **6인·인간 탐정 게임**을
추가로 완주해 UI·UX를 점검했습니다. 생성·발언·저장·재개·자동 밤 행동·투표·결과
기록은 정상 동작했지만, 누적 타임라인 아래에 인간 행동 패널이 묻혀 탐정 조사와
낮 투표를 놓치고 자동 선택으로 처리되는 문제를 확인했습니다. 실게임 근거, 화면
정본 대비 차이와 WU별 개선 순서는
[UI·UX 플레이테스트 보고서](../05_reports/AI_MAFIA_UI_UX_PLAYTEST_REPORT.md)에 기록했습니다.

