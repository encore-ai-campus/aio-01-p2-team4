# 일반 사용자 Frontend

현재 사용자 앱은 `WU-F1`에 따라 로그인 없이 브라우저 UUID를 identity로 사용합니다.
앱은 UUID를 same-origin local storage의 `ai_mafia_user_id_v1` key에 저장하고,
Backend 공개 API 요청에는 `X-User-Id`와 `X-Request-Id` header만 전달합니다.

`WU-F2`에서는 홈의 이어하기·최근 완료 목록과 새 게임 설정을 제공합니다. 전체
인원은 6~9명으로 제한하고 역할 구성은 표시만 하며, 시나리오·역할·persona·닉네임은
STANDARD에서는 사용자가 선택하지 않습니다. 게임 생성 요청은 `mystery-v1`과 `scenario-v1`을 사용하고
성공 후 Backend snapshot을 조회합니다.

홈과 새 게임 설정 화면은 공통 dark header, breadcrumb, 반응형 카드 레이아웃과
게임 방식 안내를 사용하며, 입력은 UUID·인원 선택과 Backend의 STANDARD/CUSTOM_ROLE 생성 계약을
사용합니다. 새 게임 설정의 6~9명 인원 option은 카드와 별도 선택 button을 중복하지
않고, option 하나를 큰 button으로 표시합니다. 생성 중에는 선택·취소 입력을 잠급니다.

`WU-F3`에서는 역할 공개·게임 shell을, `WU-F4`에서는 snapshot의 `legal_actions`와
`valid_targets`에 따른 발언·밤 행동·투표 panel을 제공합니다. Front는 승패나 자동
선택을 계산하지 않고 Backend command 결과를 확인한 뒤 snapshot을 다시 조회합니다.

역할 공개 화면에서 `BEGIN_GAME`이 허용된 경우에만 `expected_state_version`과
UUID v4 `Idempotency-Key`를 포함해 게임 시작 command를 제출합니다. 생성 응답만으로
phase를 변경하지 않고 command 성공 뒤 authoritative snapshot을 다시 조회합니다.
역할 공개 UI는 사건 정보, 본인 역할·능력·승리 조건, 알리바이·관찰 정보와 인원 정보를
하나의 반응형 private card에 표시하며, Backend 문자열은 unsafe HTML에 삽입하지 않습니다.
게임 시작은 `PENDING_TO_RENDER → IN_FLIGHT → terminal` 순서로 처리합니다.

F4 command는 `legal_actions`, `action_window`, `valid_targets`, `state_version`을
기준으로 구성하며, 마감·stale·중복 제출은 Backend가 최종 거부해야 합니다. Front는
자동 선택이나 자동 제출을 수행하지 않습니다.

낮 토론에서는 중앙 공개 timeline 아래에 현재 발언자 또는 본인 입력 panel을 표시하고,
본인 차례에만 최대 200자 발언과 `PASS`를 활성화합니다. 밤 행동에서는 공개 생존자와
본인 비공개 정보 사이의 중앙 영역을 어두운 대상 선택 panel로 전환합니다. 마피아·탐정·
의사 안내 문구는 역할에 맞게 달라지지만 command에는 역할이나 세부 행동을 넣지 않고
STANDARD에서는 Backend가 제공한 `valid_targets`의 `target_player_id`만 전송합니다. 시민·제출 완료자는
입력 없이 대기 안내만 보며, 결과를 확인할 수 없는 재시도는 최초 Idempotency-Key를
그대로 사용합니다.

낮 투표·재투표·최종 지목에서는 중앙 영역을 공개 timeline 요약, Backend 기준 남은
시간, 후보 선택, 제출 버튼으로 구성합니다. 후보는 `valid_targets`만 표시하고 15초 이하
경고를 제공하며, 최초 제출 뒤에는 후보를 다시 선택할 수 없습니다. 집계 전에는 사용자의
선택이나 다른 플레이어의 개별 투표를 공개하지 않습니다.

F3 화면은 `ROLE_REVEAL`과 진행 phase를 Backend snapshot으로 구분합니다. 역할 공개
화면에는 본인의 role·alibi·observation만 표시하고, 게임 shell의 player·timeline에는
공개 projection만 표시합니다. 새로고침 시에도 Front가 phase나 승패를 계산하지 않고
`game_id`로 authoritative snapshot을 다시 요청합니다.
게임 shell은 desktop에서 생존자 목록·중앙 phase 작업 영역·내 정보의 3열 구조로
표시하고 768px 이하에서는 단일 열로 재배치합니다. 중앙 공개 timeline의 이벤트 목록은
고정 높이 scroll 영역이며, 낮 발언·밤 행동·투표 panel은 그 아래에 배치합니다. 따라서
발언 입력은 대화 흐름의 하단에 유지됩니다. 첫날에도 정본 snapshot의
scenario와 공개 event만 사용하며, 본인 role·알리바이·관찰·private event는 오른쪽
panel에만 표시합니다.

`WU-F5`에서는 browser `fetch` streaming SSE를 주 연결로 사용하고, 연결이 없거나
envelope 검증에 실패하면 동일 cursor의 `/sync` polling으로 전환합니다. operation은
`(game_id, front_sequence, operation_index)`로 deduplicate하며 gap·unknown·잘못된
snapshot은 부분 적용하지 않습니다. Backend가 반환하는 sequence별 중첩
`operations` batch는 Front가 sequence와 operation index를 보존해 원자적으로 펼친 뒤
적용합니다. SSE stream 종료 시에는 마지막 수신 `last_sequence`부터 1초 간격으로
재연결하고, 실제 데이터인 `envelope`만 Streamlit component state에 등록해 수신 즉시
화면 rerun을 유도합니다. 연결 상태는 component 내부에서 관리해 상태 표시만으로
전체 화면 rerun이 반복되지 않게 하며, 현재 cursor의 no-op DELTA도 Streamlit에
전달하지 않습니다. Backend `/events`는 연결을 유지하고 변경 batch만 push하므로
정상 연결 중에는 Front polling이 발생하지 않습니다.
게임 command 생성부는 stale snapshot을 근거로 행동을 차단하지 않고 입력 형식만
정규화하며, 최신 phase·turn·window·대상 검증은 Backend 응답으로 처리합니다.

F5 연동 시 Backend 팀은 `/events`와 `/sync`에 동일한 `front_sequence`와 operation
index를 제공하고, `Last-Event-ID` 재연결·CORS header·보존 범위 밖 SNAPSHOT 응답을
지원해야 합니다. Front는 gap이나 schema 오류를 부분 적용하지 않고 authoritative
snapshot을 재조회합니다. Backend의 활성 timed window는 `remaining_ms`를 제공해야
하며, lifecycle command에는 `window_id`를 보내지 않습니다.

`WU-F6`에서는 인간 player가 사망하면 action widget을 제거하고 관전 안내와 공개
timeline만 표시합니다. `FAST_FORWARD`와 `SAVE_AND_EXIT`은 Backend의
`legal_actions`에 있을 때만 요청하며, `COMPLETED` 결과는 snapshot의 `result`만
사용합니다. `FAILED`에서는 마지막 공개 상태와 복구 불가 안내만 표시합니다.

관전 화면은 생존자·사망자 공개 목록, 공개 event timeline, 이미 허용된 본인의 역할·
알리바이·관찰·탈락 시점만 표시하는 3열 구조입니다. 빠른 진행은 Backend의
`fast_forward_enabled`가 확정되기 전까지 완료로 표시하지 않으며, 결과 불명 시 최초
body와 Idempotency-Key로만 재확인합니다. 다른 플레이어의 역할, 사망 원인, private
event나 개별 행동은 관전 화면에서도 추론하거나 공개하지 않습니다.

게임 종료 화면은 `result.winner`, `win_reason`, `finished_at`, 전체 `players`, `nights`,
`votes`, `public_event_ids`를 승리 영역·게임 요약·전체 역할·게임 기록으로 구분해
표시합니다. 밤과 투표 기록은 Backend가 확정한 대상·집계·탈락자만 이름으로 변환하며,
Front가 승패나 결정적 선택을 다시 계산하지 않습니다. `FAILED` 또는 result 누락 상태는
전체 역할을 공개하지 않고 복구 불가 안내와 이동 제어만 제공합니다.

`WU-F7`에서는 일반·게임별 feedback의 별점·의견·태그를 검증하고 제출 중에는 입력을
잠급니다. 결과가 불명확한 경우에만 동일 idempotency key로 재시도하며, Backend의
409 응답을 이미 제출한 상태로 표시합니다.

게임별 피드백 화면은 직전 완료 snapshot의 시나리오·승리 진영·라운드·인원·완료 시간을
읽기 전용 요약으로 표시합니다. 별 아이콘은 1~5점, 의견은 최대 1000자이며 태그는 현재
서버 allowlist인 `BALANCE`, `DIALOGUE`, `UX`만 선택할 수 있습니다. 성공 또는 409
중복 응답 뒤에는 입력 form을 숨기고 결과 화면으로 돌아가는 동작만 제공합니다.

## 실행 준비

기존 컴포넌트별 가상환경을 재사용하며, 설치는 반드시 해당 환경의 Python으로
실행합니다.

```powershell
& ".\frontend_user\.venv\Scripts\python.exe" -m pip install -r ".\frontend_user\requirements-dev.txt"
```

Python 3.12 설치 경로가 바뀌어 기존 `.venv`가 실행되지 않으면 환경을 재생성한
뒤 같은 명령을 실행합니다. 실제 비밀값이나 DB·Redis·MCP 설정은 Frontend에
넣지 않습니다.

## 실행

```powershell
& ".\frontend_user\.venv\Scripts\python.exe" -m streamlit run ".\frontend_user\app.py" --server.port 8501
```

첫 실행 시 브라우저 UUID를 생성합니다. 저장소가 차단된 브라우저에서는 session-only
UUID로 동작하며 새로고침 뒤 게임 복구가 보장되지 않는다는 경고를 표시합니다.
설정 화면에서 UUID를 확인·복사하거나 UUID v4를 입력해 scope를 교체할 수 있습니다.
이 경고는 홈 화면 렌더링을 막지 않습니다. Backend 게임 목록 조회가 실패하면 자동
재호출을 멈추고 홈 화면의 오류와 `다시 시도` 버튼을 표시합니다.

## 테스트·검증

```powershell
& ".\frontend_user\.venv\Scripts\python.exe" -m pytest ".\frontend_user\tests"
& ".\frontend_user\.venv\Scripts\python.exe" -m ruff check ".\frontend_user"
```

현재 확인된 Python 3.12 설치 경로는
`C:\Users\Playdata\AppData\Local\Programs\Python\Python312\python.exe`이며,
위 테스트는 `frontend_user\.venv`가 이 Python을 정상적으로 참조할 때 실행합니다.

## 책임 경계

- `app.py`: UUID bootstrap과 화면 dispatcher
- `components/identity_bridge.py`: 브라우저 local storage bridge
- `components/browser_components/identity/`: UUID만 반환하는 정적 browser component
- `core/identity.py`: UUID v4 검증·생성
- `core/session.py`: identity mirror와 UUID scope 초기화
- `core/api_client.py`: UUID 공개 Backend API client
- `app_pages/settings_page.py`: UUID 확인·복구·교체 UI

Frontend는 로그인 없이 브라우저 UUID로 사용자를 구분합니다. UUID는 인증 수단이
아니므로 이 앱은 신뢰된 로컬·사설망 환경을 전제로 합니다. Frontend는 PostgreSQL,
Redis, MCP 서버에 직접 연결하지 않습니다.

## 팀 전달 사항

<!--
팀 합의 게이트 전달용 요약:
CP-0: 정본·fixture·API header와 CORS 계약을 먼저 고정한다.
CP-1: F1 UUID-only 요청을 Backend B1·MCP M1A와 함께 확인한다.
CP-5: F2~F7 사용자 흐름과 Backend 공개 API B5를 통합 테스트한다.
CP-6: F8 관리자 guard·read-only API와 Backend B8을 운영 환경에서 검증한다.
각 게이트 전에는 계약이 바뀐 경우 관련 정본 문서를 먼저 갱신한다.
-->

- `CP-0`: 정본·fixture·API header·CORS 계약 고정
- `CP-1`: F1 UUID-only 요청 + Backend B1 + MCP M1A 확인
- `CP-5`: F2~F7 사용자 흐름 + Backend B5 통합 테스트
- `CP-6`: F8 관리자 guard·read-only API + Backend B8 운영 검증

- Backend는 `X-User-Id`와 `X-Request-Id`를 공개 사용자 API 계약으로 처리합니다.
- Frontend는 UUID와 요청 추적 ID만 공개 Backend API에 전달합니다.
- Backend CORS 또는 proxy는 `X-User-Id`, `X-Request-Id`, `Idempotency-Key`,
  `Last-Event-ID`를 허용해야 합니다.
- `GET /api/v1/games/{game_id}/sync`와 SSE `/events`는 동일한 Front sequence를
  사용해야 하며, 보존 범위를 벗어난 cursor에는 완전한 snapshot을 반환해야 합니다.
- UUID는 인증 자격증명이 아니므로 공개 인터넷 배포 전 별도 인증 계약이 필요합니다.


## WU-F11 커스텀 직업

새 게임의 기본 모드는 STANDARD입니다. CUSTOM_ROLE에서는 시민/마피아 진영과
NFC·앞뒤/연속 공백 정규화 후 1~40자인 자유 직업명을 입력합니다. Backend의
`GET /api/v1/game-config/custom-role-abilities` catalog 카드와 multiselect로 능력을
1~3개 선택하며, 시민은 조사·보호·투표 조작·특수 직업 열람 중 선택하고, 마피아는
필수 공격을 포함해 총 1~3개를 사용합니다. 낮/조회 능력만 가진 시민도 가능합니다.
생성 body에는 `mode`, `custom_role.name/faction/catalog_version/ability_ids`를 포함합니다.
원시 MCP Tool명은 입력으로 받지 않습니다. catalog 로딩·실패·빈 목록·알 수 없는 버전은
커스텀 생성만 막고 기본 생성은 유지하며, 실패 화면에서 목록을 다시 조회할 수 있습니다.

생성 결과 불명 상태는 입력을 잠그고 최초 body와 Idempotency-Key로 재시도합니다.
422 등 교정 가능한 거부 뒤 입력을 고쳐 다시 생성하면 새 body와 key를 사용합니다.
역할 공개와 내 정보는 본인 `me`의 직업명·진영·저장 능력 설명만 표시하며, 다른 player의
비공개 필드는 사용하지 않습니다. 밤에는 본인 `ability_options` 중 하나를 고른 뒤 그
능력의 `valid_targets`만 선택합니다. CUSTOM_ROLE 밤 command에는 선택 능력의 `ability_id`를
포함하고, 기존 command 멱등 재시도와 저장/재개 경계를 유지합니다. 선택 키는 게임·행동
창·능력별로 분리하여 rerun 시 선택을 보존하고 능력 전환 시 잘못된 대상을 제출하지 않습니다.

Front 검증은 합성 catalog/snapshot을 사용하는 AppTest 및 API client/command 테스트입니다.
실제 Backend 통합은 WU-B16 fixture 확정 후 CP-7에서 수행해야 하며 DB나 유료 API를
Front 테스트에서 호출하지 않습니다. focused 검증 명령:

```bash
frontend_user/.venv/bin/python -m pytest frontend_user/tests/test_home_f2.py frontend_user/tests/test_commands_f4.py frontend_user/tests/test_api_client.py frontend_user/tests/test_view_models_f3.py -q
.venv/bin/ruff check frontend_user/app_pages/game_create_page.py frontend_user/app_pages/game_page.py frontend_user/app_pages/role_reveal_page.py frontend_user/components/action_panel.py frontend_user/core/api_client.py frontend_user/core/commands.py frontend_user/core/view_models.py --select F,E9
```


## WU-F12 커스텀 능력 확장

생성 catalog는 success envelope의 `data`에서만 읽고 custom-role-v1의 정확한 다섯
ID·한국어 label·진영 배열을 검증합니다. 누락·미지/추가 필드·중복 ID/진영·배열 순서나
타입 오류는 커스텀 생성만 차단하며 목록 재시도와 STANDARD 선택은 유지합니다.

생존 CUSTOM_ROLE HUMAN의 투표 조작 보유자는 DAY_VOTE/REVOTE에서 일반 1표 또는
능력 3표를 명시적으로 선택합니다. 능력 선택 시에만 `SUBMIT_VOTE`에
`ability_id=vote.triple.v1`을 보내며 숫자 weight나 raw MCP Tool명은 보내지 않습니다.
최종 지목·표준 게임·미보유자에게 능력 선택을 제공하지 않습니다. 투표와 생성 모두
rerun 중 pending body/key를 보존하며 5xx는 동일 요청, 생성 422 교정은 새 key입니다.

특수 직업 열람은 생존 CUSTOM_ROLE HUMAN 보유자에게 IN_PROGRESS·day>=2에만
본인 패널의 수동 조회로 제공합니다. 공개 `GET /api/v1/games/{game_id}/special-roles`에
`X-User-Id`를 보내며 identity/game/player/state_version 및 현재 상태를 재확인합니다.
결과는 별도 본인 세션 값에만 두고 identity·게임·상태 전환, 로그아웃, 사망·종료·권한
상실과 조회 오류에서 폐기합니다. 늦은 응답도 범위가 다르면 표시하지 않습니다.
공개 명부·timeline·analytics·공유 cache에는 복제하지 않으며 서버 오류 원문을 숨기고
snapshot 재조회와 수동 재시도를 제공합니다. 종료 화면은 Backend custom 직업명·진영을
표준 역할보다 우선해 평문으로 표시합니다.

F12 검증은 위 focused 명령에 `frontend_user/tests/test_result_f6.py`를 추가하고,
전체 Front 회귀는 `frontend_user/.venv/bin/python -m pytest frontend_user/tests -q`로 실행합니다.
DB·유료 API 호출은 포함하지 않으며 실제 서비스 CP-7 통합은 별도 검증입니다.

2026-09-08 WU-F12 검증 결과: 능력 투표·private 조회·종료 표시 집중 검증 32건과
snapshot 재검증 실패 경계 1건이 통과했습니다. 전체 Front 회귀는 **655 passed,
5 failed**입니다. 실패는 기존 홈 UUID 복구 제어를 기대하는 F1 3건과 완료 화면에서
`result.new_game` 버튼을 기대하는 F6 2건이며, HEAD의 앱·종료 화면 코드를 임시 실행해
동일 5건 실패를 재현했습니다. 해당 기존 화면/테스트 불일치는 F12 밖이므로 유지합니다.
수정 Python 파일의 Ruff `--select F,E9` 및 `git diff --check -- frontend_user`는
통과했습니다. 실제 DB·MCP·유료 API 통합은 작업 범위 밖으로 실행하지 않았습니다.
