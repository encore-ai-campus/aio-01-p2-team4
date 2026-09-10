# AI 마피아 MVP 프론트엔드 기술 설계서

**상태:** 팀장 검토·승인 요청안  
**담당:** Frontend  
**기술:** Python 3.12 + Streamlit 1.55  
**위치:** `frontend_user/`, `frontend_admin/`  
**범위:** `WU-F1` ~ `WU-F10`
**기준일:** 2026-09-03

**정본:** [마스터플랜](../01_core/AI_MAFIA_MASTER_PLAN.md) · [화면 흐름](AI_MAFIA_SCREEN_FLOW.md) · [API 계약](../01_core/AI_MAFIA_API_SPEC.md) · [독립 개발 계약](../01_core/AI_MAFIA_INDEPENDENT_CONTRACT.md)

이 문서는 Streamlit Frontend의 구현 순서, 상태 경계, 산출물과 검증 기준을 정의한다.
새로운 게임 규칙·API field·enum·상태 전이를 만들지 않으며 충돌 시 위 정본을 우선한다.

## 0. 제출 결론과 적합성

- 사용자 앱(`:8501`)과 관리자 앱(`:8502`)을 독립 Streamlit 프로세스로 유지한다.
- Front는 Backend snapshot과 operation을 표현하는 Presenter로만 동작한다.
- 구현 순서는 `F1 → F2 → F3 → F4 → F5 → F6 → F7 → F8 → F10`이다.
- 한 개발 세션과 branch·PR은 WU 하나 이하로 제한한다.
- Backend 준비 전에는 정본 기반 synthetic fixture로 독립 개발한다.
- 동기화는 SSE 우선, 동일 envelope의 polling fallback을 사용한다.
- private 정보는 숨겨서 보관하지 않고 payload·session state·DOM에서 제외한다.

| 검토 항목 | 판정 | 근거 |
|---|---|---|
| Streamlit 사용자·관리자 UI | 적합 | 화면 정본의 대상 UI와 동일 |
| Presenter 원칙 | 적합 | 승패·phase·자동 행동 계산 금지 |
| UUID-only 식별 | 적합 | Web Crypto, local storage, `X-User-Id` |
| OIDC·로그인·Front HMAC 제거 | 적합 | F1 범위 |
| WU-F1~F10 | 적합 | 마스터플랜 순서·범위 유지 |
| 닉네임 입력 | 제외 | 이름·프로필 수집 금지 |
| SSE·polling | 적합 | 동일 operation envelope·cursor |
| 관리자 | 적합 | 별도 앱·UUID allowlist·read-only·fail-closed |

### 승인 필요 사항

- [ ] 두 Streamlit 앱의 독립 process·origin 유지
- [ ] UUID와 SSE에 한정한 최소 custom component 사용
- [ ] Backend가 모든 origin과 `X-User-Id`, `X-Request-Id`, `Idempotency-Key`,
      `Last-Event-ID` header를 허용하고 credentials를 막는 CORS 계약 제공
- [ ] Front fixture와 Backend `/openapi.json` 통합 gate
- [ ] F1 착수 전 기존 OIDC·HMAC 삭제·유지 파일 목록
- [ ] WU별 branch·review와 README 동시 갱신

## 1. 책임 경계

### Front 소유

- 사용자 UUID, 홈, 생성, 역할, 게임, 관전, 결과, 피드백 화면
- 관리자 UUID, read-only metrics·목록·상세 화면
- Streamlit route, widget·session 상태, 공개 API client
- payload 검증, ViewModel, SSE·polling과 operation 적용기
- pytest, Streamlit AppTest, contract·browser E2E fixture

### Front 비소유

- 역할 배정, 승패, phase 전이, target 적법성의 최종 판단
- deadline 만료, 자동 행동, RNG
- DB·Redis·migration·repository, LLM·MCP·Agent Manager
- 관리자 allowlist 최종 판정과 Backend private projection
- 닉네임·프로필·이메일·계정 인증

```text
Browser → frontend_user Streamlit :8501 ┐
Browser → frontend_admin Streamlit :8502 ├→ Backend /api/v1
                                         └X→ DB / Redis / LLM / MCP / internal API
```

Front에는 Backend URL과 storage key만 설정한다. DB·Redis URL, LLM key, MCP·Engine secret을
Streamlit secrets, session state, HTML 또는 browser bundle에 넣지 않는다.

## 2. 아키텍처 원칙

### Presenter-only

Front는 schema 검증, `legal_actions`·`valid_targets` 표시, deadline 기반 표시용 countdown,
입력 형식 검사와 오류 복구만 담당한다. 승패 계산, phase·round 증가, 자동 target 선택,
자동 제출, 역할 추론과 임의 action subtype 생성은 금지한다.

mutation 성공만으로 화면을 낙관 변경하지 않는다. terminal 응답 후 GET 또는 sync로
snapshot을 확인하여 `st.session_state`를 한 번에 교체한다. callback은 제출 의도만 기록하고
domain 상태를 직접 변경하지 않는다.

### Private-by-construction

- 공개 player와 인간 본인 projection model을 분리한다.
- 다른 AI의 private model을 Front에 정의하지 않는다.
- private projection은 현재 game session에만 둔다.
- raw snapshot을 `st.write`, exception, analytics와 log에 출력하지 않는다.
- CSS로 가린 role을 HTML에 남기지 않는다.
- 예상하지 못한 private field는 출력하지 않고 계약 오류로 거부한다.

### 멱등성과 동시성

- 모든 변경 POST에 UUID v4 `Idempotency-Key`를 사용한다.
- terminal 결과 전까지 같은 key와 body를 session에 보관한다.
- 결과 불명 네트워크 오류만 같은 key·body로 재시도한다.
- body가 바뀌면 새 key를 사용한다.
- game command에는 snapshot의 `expected_state_version`을 포함한다.
- stale command를 자동 재적용하지 않는다.

## 3. 기술 스택

| 영역 | 선택 | 역할·제약 |
|---|---|---|
| Runtime | Python 3.12 | 저장소 지원 버전 유지 |
| UI | Streamlit `>=1.55,<2` | callback에 게임 판단 금지 |
| HTTP | `httpx` | timeout·header·streaming·mock 중앙화 |
| Validation | Pydantic v2, `extra="forbid"` | 외부 payload allowlist 검증 |
| State | `st.session_state` | snapshot·cursor·widget 상태 분리 |
| Browser bridge | 최소 custom component | Web Crypto·local storage·SSE만 담당 |
| Test | pytest + `AppTest` | synthetic fixture·fake transport |
| Lint | Ruff | 저장소 `pyproject.toml` 준수 |
| E2E | Python Playwright 필수 | storage·SSE·DOM·접근성 검증 |

의존성은 각 Front requirements에 직접 명시하고 추가한 WU에서 root·Front README를 함께
갱신한다. browser component에는 게임 판단과 API mutation을 넣지 않는다.

custom component는 Streamlit 1.55의 `st.components.v2.component`로 통일한다. Python
wrapper가 저장소의 신뢰 가능한 정적 HTML·JavaScript를 읽어 등록하고 component의
state·trigger 결과를 Pydantic model로 검증한다. 외부 입력, query parameter, API payload와
LLM 출력은 component source에 삽입하지 않는다.

## 4. Streamlit 디렉터리 설계

기존 구조를 유지하며 필요한 파일만 WU별로 추가한다. 파일 생성·삭제·이동 전에는 실제
대상, 이유와 영향을 고지한다.

```text
frontend_user/
├─ app.py                         # 초기화·route만 담당
├─ app_pages/
│  ├─ home_page.py                # F2 추가
│  ├─ game_create_page.py         # F2 추가
│  ├─ role_reveal_page.py         # F3 추가
│  ├─ game_page.py                # F3~F6 추가
│  ├─ result_page.py              # F6 추가
│  ├─ feedback_page.py            # F7 추가
│  └─ settings_page.py            # F1 추가
├─ components/
│  ├─ ui.py
│  ├─ identity_bridge.py          # F1: storage bridge
│  ├─ sync_bridge.py              # F5: SSE bridge
│  ├─ browser_components/
│  │  ├─ identity/                # F1: UUID component v2 HTML·JS
│  │  └─ sync/                    # F5: 인증 streaming fetch component v2
│  ├─ player_panel.py
│  ├─ timeline.py
│  └─ action_panel.py
├─ core/
│  ├─ api_client.py               # F1: 공개 UUID API로 교체
│  ├─ identity.py
│  ├─ session.py
│  ├─ models.py
│  ├─ view_models.py
│  ├─ commands.py
│  ├─ sync.py
│  └─ errors.py
└─ tests/
   ├─ fixtures/
   ├─ test_identity.py
   ├─ test_api_client.py
   ├─ test_session.py
   ├─ test_sync.py
   └─ test_app_smoke.py

frontend_admin/
├─ app.py                         # 초기화·guard·route
├─ app_pages/
│  ├─ dashboard_page.py
│  ├─ game_list_page.py
│  └─ game_detail_page.py
├─ components/
│  ├─ identity_bridge.py
│  └─ ui.py
├─ core/
│  ├─ api_client.py               # admin GET만 노출
│  ├─ auth.py
│  ├─ models.py
│  └─ session.py
└─ tests/
   # F8 착수 시 디렉터리와 아래 테스트 파일을 새로 생성
   ├─ fixtures/
   ├─ test_auth.py
   ├─ test_api_client.py
   └─ test_app_smoke.py
```

기존 `auth/`, login page, OIDC secrets 검사와 Front HMAC은 F1에서 참조·테스트·README
영향을 조사한 뒤 승인된 목록만 제거한다. 공용 top-level package는 임의로 만들지 않는다.

## 5. 상태와 데이터 흐름

| 상태 | 원본 | 저장 위치 | 수명 |
|---|---|---|---|
| `user_id` | browser | local storage + session mirror | UUID 교체까지 |
| game list | Backend | 제한된 session cache | UUID scope |
| snapshot·version | Backend | 현재 game session | snapshot 교체까지 |
| sync cursor | Backend | session | game·connection scope |
| idempotency key·body | Front | pending session | terminal 결과까지 |
| countdown | Backend deadline | rerun 계산값 | 현재 window |
| 미제출 입력 | 사용자 | widget/session | 현재 form |
| private projection | Backend | 현재 game session만 | route·UUID 변경까지 |
| 연결 상태 | transport | session | 현재 connection |

local storage에는 UUID만 저장한다. snapshot, role, target, capability와 operation은 금지한다.
URL에는 opaque `game_id`만 허용하고 `user_id`·role·private 값은 넣지 않는다.

session key는 `identity.*`, `navigation.*`, `game.*`, `form.*`, `feedback.*` prefix로 관리한다.
UUID·game·route 변경 시 `core/session.py`의 범위별 reset 함수를 사용하며 전체 session을
무차별 clear하지 않는다.

### 화면 이동과 복원

- `app.py`는 session 기반 단일 dispatcher로 고정하고 각 `app_pages/*_page.py`의 render
  함수만 호출한다. Streamlit의 자동 pages 탐색과 별도 route 체계를 섞지 않는다.
- URL query에는 opaque `game_id`만 허용한다. UUID·role·private 값은 금지한다.
- refresh 시 local storage UUID를 먼저 복구하고 `game_id`가 있으면
  `GET /api/v1/games/{game_id}`로 소유권과 최신 상태를 확인한다.
- Backend snapshot의 status·phase로 역할 공개, 게임, 관전, 결과 화면을 결정한다.
- `GAME_NOT_FOUND`이면 query의 `game_id`를 제거하고 소유권 여부를 노출하지 않는 안내 뒤
  홈으로 이동한다.
- 화면 이동은 `navigation.page`과 query를 갱신한 뒤 `st.rerun()` 한 번으로 완료한다.

```text
앱 실행/rerun → UUID 초기화 → route·scope 검증 → GET/sync
→ payload 검증 → ViewModel → Presenter render

form submit callback → local/action/target guard → key·body 고정
→ `PENDING_TO_RENDER` 저장 → st.rerun()
→ disabled pending 화면을 먼저 렌더링 → POST 1회
→ terminal 응답 → GET/sync → snapshot 원자 교체 → st.rerun()

SSE/polling → envelope 검증 → duplicate·gap 검사 → batch 원자 적용
→ cursor 저장 → 한 번 rerun
```

정본 enum(`IN_PROGRESS`, `ROLE_REVEAL`, `BEGIN_GAME` 등)을 그대로 사용한다. `WAITING`,
`VOTING`, `TALK`, `allowedActions`, `isEnded` 같은 별칭을 만들지 않는다. API model은
Backend `/openapi.json`과 parity test를 둔다.

## 6. UUID·API client

Streamlit 서버는 browser local storage와 Web Crypto에 직접 접근할 수 없으므로 F1의 최소
custom component가 다음만 수행한다.

1. origin별 key 읽기
2. 값이 없으면 `crypto.randomUUID()`로 UUID v4 생성
3. UUID 문자열만 local storage에 쓰기
4. UUID 또는 storage 차단 상태를 Python wrapper로 반환

사용자 key는 `ai_mafia_user_id_v1`, 관리자 key는 `ai_mafia_admin_user_id_v1`이다. port가
달라 값도 공유되지 않는다. component는 snapshot 저장, API 호출, 게임 계산과 console
출력을 하지 않는다. 차단 시 session-only UUID와 복사 경고를 표시한다.

### Custom component 메시지 계약

Python과 browser component는 아래 JSON-compatible payload만 주고받는다. 모든 메시지는
`schema_version=1`, `component_instance_id`와 현재 `scope_version`을 포함한다. 이전 scope의
늦은 응답은 Python wrapper가 폐기한다.

| 방향 | 메시지 | 필수 field |
|---|---|---|
| Python→UUID | `IDENTITY_INIT` | `schema_version,component_instance_id,storage_key,scope_version` |
| Python→UUID | `IDENTITY_WRITE` | 위 공통 field + `user_id` |
| UUID→Python | `IDENTITY_READY` | 공통 field + `user_id,persistence`(`LOCAL`/`SESSION_ONLY`) |
| UUID→Python | `IDENTITY_ERROR` | 공통 field + `code`(`STORAGE_BLOCKED`/`INVALID_STORED_UUID`) |
| Python→Sync | `SYNC_CONNECT` | 공통 field + `backend_url,game_id,user_id,last_sequence,after_state_version,after_sequence` |
| Python→Sync | `SYNC_DISCONNECT` | 공통 field + `reason` |
| Sync→Python | `SYNC_ENVELOPE` | 공통 field + `event_id,envelope` |
| Sync→Python | `SYNC_STATUS` | 공통 field + `status`(`CONNECTING`/`LIVE`/`POLLING`/`STALE`) |
| Sync→Python | `SYNC_ERROR` | 공통 field + `code,retryable,attempt` |

- `backend_url`은 allowlist된 구성값만 전달하며 component는 다른 origin으로 연결하지 않는다.
- `last_sequence`는 SSE 연결의 `Last-Event-ID` 값으로 사용하고, `after_state_version`과
  `after_sequence`는 polling `/sync` 요청에 그대로 매핑한다. 두 transport는 같은
  Front-visible cursor를 공유하며 component와 Python wrapper가 서로 다른 cursor를
  독자적으로 전진시키지 않는다.
- `user_id`는 transport header 구성에만 쓰고 browser storage에는 기존 identity key 외로
  복제하지 않는다.
- component unmount, UUID·game·scope 변경 때 `AbortController.abort()`와 timer 정리를
  cleanup callback에서 수행한다.
- `SYNC_ENVELOPE`는 API의 완전한 `game_sync` 한 건만 전달하며 부분 SSE line을 넘기지 않는다.
- 오류에는 response body, UUID, URL query, raw exception과 private payload를 넣지 않는다.
- Python wrapper는 메시지 model 검증 실패, instance·scope 불일치와 sequence 역행을 무시하고
  snapshot 복구를 요청한다.

복구 UI는 UUID v4 이중 검증, 비밀번호가 아니라는 경고, 교체 확인 dialog, storage·session
교체, 이전 UUID scope cache·snapshot·cursor·form 초기화, 목록 재조회 순서로 동작한다.

`core/api_client.py`는 모든 공개 요청에 `X-User-Id`, 요청별 `X-Request-Id`를 추가한다.
mutation caller의 `Idempotency-Key`는 덮어쓰지 않는다. `Authorization`, OIDC token,
email, timestamp 서명과 Front HMAC을 보내지 않는다. GET만 제한적으로 retry하고 POST는
결과 불명일 때 사용자 동작으로 같은 key·body만 재시도한다.

모든 API 성공·오류는 Pydantic v2 model로 검증한다. model은 `extra="forbid"`를 사용하되
공개 snapshot의 정본 `me` projection과 operation별 payload는 명시적으로 정의한다. 검증
실패 시 raw payload를 표시·기록하지 않고 request ID와 고정 안내만 제공한다.

### API 소비표

| WU | 기능 | Method·path | Front 입력·보존 값 |
|---|---|---|---|
| F2 | 목록 | `GET /api/v1/games?limit=20` | UUID scope |
| F2 | 생성 | `POST /api/v1/games` | player/ruleset/scenario version, idempotency key |
| F3·F6 | snapshot | `GET /api/v1/games/{game_id}` | opaque game ID |
| F3·F4·F6 | command | `POST /api/v1/games/{game_id}/commands` | union body, expected version, idempotency key |
| F5 | sync | `GET /api/v1/games/{game_id}/sync` | `after_state_version`, `after_sequence` |
| F5 | SSE | `GET /api/v1/games/{game_id}/events` | user/request/last-event header |
| F7 | feedback | `POST /api/v1/feedback` | union body, idempotency key |
| F8 | 관리자 목록 | `GET /api/v1/admin/games` | status·phase·cursor·limit |
| F8 | 관리자 상세 | `GET /api/v1/admin/games/{game_id}` | opaque game ID |
| F8 | 관리자 지표 | `GET /api/v1/admin/metrics` | from·to, 최대 31일 |
| F10 | AI 발언 분석 | `GET /api/v1/admin/speech-analytics` | from·to·game·persona·round·analysis_version·limit |

성공 응답은 `data`·`meta`, 오류는 `error` envelope를 먼저 검증한다. 허용 operation은
`SET_GAME_STATE`, `REPLACE_PLAYERS`, `SET_PRIVATE_STATE`, `SET_ACTION_WINDOW`,
`CLEAR_ACTION_WINDOW`, `APPEND_PUBLIC_EVENT`, `APPEND_PRIVATE_EVENT`, `SET_RESULT`만이다.

### Pydantic 모델 계약

모든 model은 `ConfigDict(extra="forbid")`를 공통 base로 사용한다. 날짜는 timezone이 있는
UTC `datetime`, runtime ID는 UUID, enum은 정본의 문자열 enum으로 검증한다.

| 모델 | 필수·nullable field |
|---|---|
| `SuccessEnvelope[T]` | `data:T`, `meta:{request_id,server_time,replayed?}` |
| `ErrorEnvelope` | `error:{code,message,request_id,retryable,details}` |
| `GameListItem` | `game_id,status,phase,round,day_number,state_version,scenario_title,player_count,human_alive,winner?,can_resume,updated_at` |
| `GameState` | `game_id,status,phase,round,day_number,state_version,last_sequence,ruleset_version,scenario_version,player_count,mafia_count,fast_forward_enabled,updated_at` |
| `Scenario` | `scenario_id,title,background,victim,locations` |
| `PublicPlayer` | `player_id,seat,display_name,kind,alive,revealed_role?,eliminated_phase?,eliminated_round?` |
| `MeProjection` | `player_id,role,alive,spectator,alibi,observation,private_events` |
| `ActionWindow` | `window_id,kind,cycle,paused,opened_state_version,server_time,deadline_at?,remaining_ms?,turn_player_id?,has_submitted,legal_actions,valid_targets` |
| `Snapshot` | `game,scenario,players,me,action_window?,legal_actions,public_events,result?` |
| `Operation` | `schema_version=1,front_sequence,operation_index,state_version,type,payload` discriminated union |
| `SyncEnvelope` | `game_id,mode,from_state_version,state_version,last_sequence,operations,snapshot?` |
| `PublicEvent` | `event_id,event_type,created_at,data` event-type union |
| `PrivateEvent` | 조사 결과 또는 본인 밤 행동 접수 event만 허용 |
| `GameResult` | `winner,win_reason,finished_at,players,nights,votes,public_event_ids` |
| `FeedbackRequest` | `feedback_type,rating,comment?,tags`와 GAME일 때 `game_id` |
| `AdminGameItem` | `game_id,owner_user_id,status,phase,round,state_version,player_count,open_window_kind?,updated_at` |
| `AdminGameDetail` | operational state·public event·window metadata·안전한 failure code만 허용 |
| `AdminMetrics` | 생성·완료·저장 수, 완료율, 평균 round, 진영별 승리, 자동 행동 수, 피드백 평균 |

`Operation`은 `type`, command와 feedback은 각각 `type`, `feedback_type`을 discriminator로
사용한다. `SET_PRIVATE_STATE`와 `APPEND_PRIVATE_EVENT`는 본인 projection 전용 model로만
파싱한다. 관리자 진행 게임 model에는 role·alibi·observation·개별 action·vote·seed·Agent
context field를 정의하지 않는다.

### Command payload 계약

모든 command는 `expected_state_version`을 포함하며 같은 endpoint와 idempotency header를
사용한다.

| type | 추가 body field |
|---|---|
| `BEGIN_GAME` | 없음 |
| `SPEAK` | `window_id`, `message` 1~200자 |
| `PASS` | `window_id` |
| `SUBMIT_NIGHT_ACTION` | `window_id`, `target_player_id`; role·subtype 전송 금지 |
| `SUBMIT_VOTE` | `window_id`, `target_player_id` |
| `SAVE_AND_EXIT` | 없음 |
| `RESUME` | 없음 |
| `FAST_FORWARD` | 없음 |

command 성공 model은 `command_id`, `command_type`, `accepted_state_version`,
`result_state_version`, `sync_url`을 검증한다. 응답에는 snapshot이 없으므로 반드시
`sync_url` 또는 snapshot GET으로 authoritative 상태를 확인한다.

## 7. WU별 실행 계획

| WU | 산출물 | 종료 증거 |
|---|---|---|
| WU-F1 | UUID bridge·session·API client·설정 | 최초·복구·차단·header·OIDC 제거 |
| WU-F2 | 홈·생성 form·game list | loading·empty·error·6~9명·single POST |
| WU-F3 | role reveal·game shell·ViewModel | refresh·private 격리 |
| WU-F4 | phase action form·countdown | action·target·200자·deadline guard |
| WU-F5 | SSE bridge·polling·operation 적용기 | duplicate·gap·reconnect |
| WU-F6 | 관전·fast-forward·결과 | 종료 전후 공개 범위 |
| WU-F7 | 일반·game feedback | validation·게임당 한 건 |
| WU-F8 | admin guard·dashboard·상세 | 403·private 비노출 |

### WU-F1 — UUID 저장·복구 shell

- Web Crypto/local storage component, UUID validation, session mirror를 구현한다.
- storage 차단 fallback과 설정의 확인·복사·복구·교체 dialog를 구현한다.
- UUID 교체 시 이전 game·private·cursor·pending/widget 상태를 제거한다.
- API client를 UUID 공개 계약으로 교체하고 OIDC·로그인·Front HMAC 실행 경로를 제거한다.
- 기존 파일은 참조 목록 승인 후 삭제한다.

테스트: 없음·정상·손상·차단 storage, rerun 유지, 복구·취소, scope reset, header와 HMAC
부재. local storage 동작은 Playwright browser E2E를 필수로 실행한다.

### WU-F2 — 홈·새 게임·목록

- `GET /api/v1/games?limit=20`, 이어하기·최근 완료 각 최대 3개, 상태별 CTA를 구현한다.
- loading, empty, error, success를 별도 렌더링한다.
- 6~9명만 허용하고 정본 역할 구성 preview와 규칙 요약을 표시한다.
- scenario·role·persona·닉네임 선택은 만들지 않는다.
- submit 때 key·body를 한 번 고정하고 pending 동안 모든 입력을 disabled 처리한다.
- callback은 네트워크를 호출하지 않고 `PENDING_TO_RENDER`만 저장한다. 다음 rerun에서
  disabled 화면을 먼저 그린 뒤 `IN_FLIGHT`로 바꾸고 POST를 정확히 한 번 호출한다.
- terminal 응답 뒤 `SUCCEEDED`, `RETRYABLE_UNKNOWN`, `REJECTED` 중 하나로 저장한다.
- 성공 후 `snapshot_url`을 GET한 뒤 실제 phase로 이동한다.

테스트: 모든 목록 상태, 6·7·8·9명, 이중 click/rerun single POST, same-key retry.

### WU-F3 — 역할 공개·게임 shell

- scenario, 내 역할·능력·승리 조건·알리바이·관찰과 공개 player·timeline을 표시한다.
- desktop 3열, mobile 단일 열·하단 action 구조를 사용한다.
- refresh/rerun 때 `game_id`로 authoritative snapshot을 복구한다.
- 다른 player role·조사·행동이 HTML·session·log에 없어야 한다.
- 처형 role만 즉시 공개하고 밤 사망 role은 숨긴다.

테스트: refresh 복구, private DOM/session 부재, 320px·200% 확대.

### WU-F4 — 낮·밤·투표 command

공통 guard는 `command ∈ legal_actions`, pending 없음, 현재 UUID·game scope 일치다.
window command는 `paused=false`, `has_submitted=false`, window legal action 일치가 필요하다.
target option은 `valid_targets`에서만 만들고 제출 직전 다시 membership을 검사한다. stale로
무효가 된 선택은 비우며 자동 대체하지 않는다.

| command | 추가 조건 |
|---|---|
| `BEGIN_GAME` | 역할 공개, 인간 생존 |
| `SPEAK`·`PASS` | 인간 생존, 본인 차례 |
| `SUBMIT_NIGHT_ACTION` | 인간 생존, 특수 역할, 미제출 |
| `SUBMIT_VOTE` | 인간 생존, 투표 phase, 미제출 |
| `SAVE_AND_EXIT` | 진행 중 안정 상태; 사망자도 가능 |
| `RESUME` | 저장 상태 |
| `FAST_FORWARD` | 인간 사망, 진행 중 |

발언은 정규화 후 1~200 Unicode code point, 제어 문자·공백 입력은 거부한다. countdown은
server offset으로 표시만 갱신하며 0초에 submit을 잠근다. Front 자동 선택·제출은 금지한다.

테스트: 전 guard, 0·1·200·201자, invalid target, deadline 0, stale, rerun 중복.

### WU-F5 — SSE·polling 동기화

- 주 transport는 `/events` SSE, fallback은 `/sync` polling이며 WebSocket은 쓰지 않는다.
- native `EventSource`는 `X-User-Id`를 넣을 수 없으므로 사용하지 않는다. custom component는
  browser `fetch` + `ReadableStream`으로 SSE를 구독하고 `X-User-Id`, `Last-Event-ID`를
  header로 전달한다. `X-Request-Id`도 연결마다 새 UUID로 전달하며 UUID를 URL query에
  넣지 않는다.
- rerun마다 Python blocking loop를 열지 않는다. browser component가 streaming fetch와
  cursor를 관리하고 완전한 공개 envelope만 Python에 전달한다.
- component 실패·연결 끊김이면 아래 timing 정책의 Python GET sync로 전환한다.
- identity는 `(game_id, front_sequence, operation_index)`이며 event ID·시간만 쓰지 않는다.
- index 연속성, 다음 sequence, schema와 version을 검증한다.
- duplicate batch는 버리고 gap·unknown·불완전·version 역행은 부분 적용 없이 snapshot으로
  복구한다. 유효 batch만 한 번에 session에 반영한다.
- game·UUID·route 변경 시 `AbortController`로 streaming fetch를 중단하고 poll timer를
  정리한다.
- Backend CORS는 모든 origin과 `X-User-Id`, `X-Request-Id`, `Idempotency-Key`,
  `Last-Event-ID`를 허용하고 credentials를 막는다. Front origin을 Backend 설정에 사전
  등록하지 않는다. same-origin proxy를 선택하면 proxy가 동일 header와 SSE stream을
  Backend까지 전달하고, `backend_url`은 proxy origin으로 고정한다.

상태는 `CONNECTING → LIVE`, 실패 시 `POLLING`, 반복 실패 시 `STALE`로 전환한다. SSE 복구
때 cursor를 확인한 뒤 `LIVE`로 돌아간다.

**기본 timing 정책**

| 상황 | 기본값 |
|---|---|
| 정상 foreground polling | 2초 |
| background polling | 10초; 입력은 잠그고 복귀 즉시 sync |
| sync 실패 backoff | 2초 → 4초 → 8초 → 16초 → 최대 30초, 각 단계 ±20% jitter |
| `STALE` 전환 | 연속 sync 실패 5회 |
| 최초 SSE reconnect | 1초 |
| SSE reconnect backoff | 1초 → 2초 → 4초 → 8초 → 최대 30초, ±20% jitter |
| polling 중 SSE 재시도 | 마지막 실패 후 30초마다 1회 |
| 연결 성공 | 실패 횟수와 backoff를 즉시 초기화 |

`visibilitychange`로 foreground 복귀하거나 browser `online` event를 받으면 timer를 기다리지
않고 즉시 `/sync`를 한 번 호출한다. timing 값은 `core/sync.py`의 단일 immutable policy에
모으고 화면 코드에 숫자를 중복하지 않는다. 부하 시험에서 변경할 때 Front 단독으로
숨겨 바꾸지 않고 Backend 담당자와 합의해 이 표와 테스트를 함께 갱신한다.

테스트: duplicate·gap·unknown·snapshot mode·offline·SSE 복귀·rerun cleanup. 실제 browser의
header·CORS preflight·stream 취소·polling 전환은 Playwright E2E를 필수로 실행한다.

### WU-F6 — 관전·빠른 진행·결과

인간 사망 시 행동 widget과 미제출 입력을 제거하고 관전 안내를 표시한다. 기존 본인에게
허용된 private 정보만 유지한다. `FAST_FORWARD`와 `SAVE_AND_EXIT`은 `legal_actions`에
따라 표시한다. 빠른 진행은 확인 후 한 번만 제출하고 snapshot으로 활성화를 확인한다.

결과는 `COMPLETED` snapshot의 `result`만 사용하며 Front가 event로 재계산하지 않는다.
`FAILED`는 마지막 공개 상태와 복구 불가 안내만 표시한다.

테스트: 사망자 form 제거, 종료 전 private 부재, 종료 후 result-only 공개. 종료 전 private
값이 실제 DOM에 없는지 Playwright E2E로 검사한다.

### WU-F7 — 피드백

- rating 1~5, 선택 comment 1~1000자, allowlist tag 최대 5개를 검증한다.
- game 피드백은 본인 `COMPLETED` game만 가능하다.
- pending 동안 submit을 잠그고 key·body를 session에 유지한다.
- 결과 불명만 같은 key로 재시도하고 validation 수정은 새 key를 쓴다.
- local storage 제출 flag를 쓰지 않고 Backend 409를 최종 판정으로 사용한다.

테스트: 모든 입력 경계, 이중 제출, same-key retry, 이미 제출 안내.

### WU-F8 — read-only 관리자

- `frontend_admin`을 `:8502`에서 별도 실행하고 관리자 storage key를 사용한다.
- 초기화 뒤 `GET /api/v1/admin/metrics`의 200만 접근 허용으로 본다.
- 403·연결 오류에서는 dashboard 함수와 partial data를 렌더링하지 않는다.
- API client는 admin GET만 노출하며 수정·삭제·강제 종료 UI를 만들지 않는다.
- 진행 game private field는 `***`로 보관하지 않고 model에서 거부한다.

테스트: 200·403·network, cache 제거, partial DOM 부재, private schema reject. 403 화면의 DOM과
browser network 결과는 Playwright E2E로 검사한다.

### WU-F10 — 공개 AI 발언 분석

- `speech_analysis`의 같은 분석 버전 임베딩을 Backend가 최대 500건 표본으로 묶어
  `speech-analytics` 집계를 반환한다. Front는 벡터를 받지 않고 주제 히트맵·원문
  키워드·claims stance·대표 공개 근거만 표시한다.
- 사람 발언과 분석 미완료 행은 각각 AI 필터와 coverage로 구분한다. 표본 제한·부분
  완료·동의어 확정이 아닌 표현 후보라는 안내를 화면에 유지한다.

## 8. 공통 오류·네트워크

| code·상황 | 처리 |
|---|---|
| `MISSING_USER_ID` | UUID 초기화 전환 |
| `ADMIN_ACCESS_DENIED` | cache 제거, 거부 화면만 표시 |
| `GAME_NOT_FOUND` | 소유권 여부를 구분하지 않는 홈 안내 |
| `STALE_STATE_VERSION` | 입력 폐기, sync, action 재확인 |
| `IDEMPOTENCY_KEY_REUSED` | 자동 재전송 중단 |
| `ACTION_ALREADY_SUBMITTED` | snapshot 조회 후 완료 표시 |
| `WINDOW_CLOSED` | form 제거, 결과 sync |
| `PLAYER_DEAD` | 관전 snapshot 교체 |
| `ACTION_NOT_ALLOWED`·`INVALID_PHASE` | 잠금 후 snapshot 재확인 |
| `GAME_BUSY` | 짧은 backoff 뒤 읽기 sync |
| `GAME_ALREADY_ENDED` | 결과 snapshot 이동 |
| `FEEDBACK_ALREADY_SUBMITTED` | 완료 안내 |
| `VALIDATION_ERROR` | field 오류, body 변경 시 새 key |
| `RATE_LIMITED` | mutation 자동 retry 금지 |
| `DEPENDENCY_UNAVAILABLE` | UUID·화면 유지, 재시도 |

| 연결 상태 | UI | mutation |
|---|---|---|
| `LIVE` | 실시간 연결 | legal action 허용 |
| `POLLING` | 다시 연결 중 | 중복 전송 금지 |
| `OFFLINE` | 네트워크 연결 끊김 | 잠금 |
| `STALE` | 상태 확인 필요 + 재시도·홈 | 잠금 |

banner는 text·icon·색상을 함께 사용하고 전환 때만 알린다. polling rerun마다 같은 toast를
반복하지 않는다. reconnect는 capped exponential backoff+jitter, 복귀 즉시 sync를 쓴다.

## 9. 접근성·반응형

- 768px 이하 단일 열, 320px 가로 overflow 없음, 200% 확대 시 겹침 없음
- 주요 target·button 최소 44px, 모든 input에 visible label
- 색상 외 text·icon으로 상태 표현, keyboard만으로 모든 핵심 동작 가능
- 오류 요약과 수정 field로 이동 가능, timeline 읽기 위치 강제 이동 금지
- custom HTML/CSS에 사용자·API 문자열 삽입 금지
- `prefers-reduced-motion`에서 역할·event animation 제거

## 10. 테스트·검증

| 계층 | 도구 | 대상 |
|---|---|---|
| Unit | pytest | UUID·normalization·batch·cursor·ViewModel |
| API | pytest + `httpx.MockTransport` | header·timeout·error·retry |
| Streamlit UI | `streamlit.testing.v1.AppTest` | route·form·guard·pending·banner |
| Contract | pytest | snapshot·operation·error schema |
| Browser E2E | Python Playwright | storage·SSE·refresh·DOM |
| Accessibility | keyboard·zoom·browser audit | 주요 화면 |

필수 fixture는 UUID 정상·손상·차단, 목록 전 상태, 6~9명, 모든 role·phase·action,
deadline 15·10·5·0초, duplicate·gap·unknown·snapshot mode, 사망·결과·피드백, admin
200·403·오류·private field를 포함한다. 실제 사용자 데이터·key·prompt·Agent private
context는 넣지 않는다.

```powershell
uv run pytest frontend_user/tests
uv run pytest frontend_admin/tests
uv run ruff check frontend_user frontend_admin
```

문서만 바뀌면 diff·링크·구조를 확인하고 runtime test 생략 이유를 남긴다.

## 11. Branch·통합 gate

- `main` 직접 commit·push 금지, branch는 `codex/frontend-wu-f1`처럼 WU를 표시한다.
- 사용자 승인 없이 commit·push하지 않고 사용자 변경이나 무관한 refactor를 건드리지 않는다.
- 모든 코드 주석·docstring은 의도·경계를 설명하는 한국어로 작성한다.
- 모든 WU에서 root README와 해당 Front README를 갱신한다.

| Gate | Front 조건 | 외부 의존 |
|---|---|---|
| CP-0 | 정본·Streamlit 구조·fixture 승인 | 세 섹터 합의 |
| CP-1 | F1 UUID-only 요청 완료 | B1, M1A |
| CP-5 | F2~F7 사용자 흐름 완료 | B5 공개 API |
| CP-6 | F8·F10 관리자 완료 | B8 관리자 API |

Backend 미완료는 Front 단위 개발 blocker가 아니다. 통합 시 `/openapi.json`과 다르면
Front alias를 만들지 않고 정본과 계약 테스트를 먼저 갱신한다.

### 팀 간 전달 규칙

| 시점 | Front가 제공 | 상대 섹터가 제공 | 승인 증거 |
|---|---|---|---|
| CP-0 | 화면별 fixture·필요 CORS header 목록 | Backend OpenAPI 예시·SSE frame·CORS 계약 | 정본 diff 승인 |
| CP-1 | UUID·request header contract test | UUID validation·소유권 오류 응답 | 양측 contract test |
| F2~F4 | command body·오류 code 소비표 | create·snapshot·command fixture | fixture hash/버전 기록 |
| F5 | dedupe·gap·reconnect test 결과 | SSE·sync 동일 envelope와 CORS | disconnect 통합 로그 |
| F6~F7 | 관전·결과·feedback UI test | redacted result·feedback 409 | CP-5 E2E 결과 |
| F8 | 403 fail-closed·private reject 결과 | admin allowlist·redacted schema | CP-6 E2E 결과 |

- 계약 질문과 변경 요청은 해당 정본 파일·section·예시 payload를 함께 제시한다.
- Front fixture에는 `schema_version`과 기준 정본 commit을 기록한다.
- Backend 응답이 fixture와 다르면 호환용 별칭을 추가하지 않고 먼저 계약 차이를 합의한다.
- field·enum·CORS·오류 code 변경은 Front·Backend 영향 확인과 정본 갱신 전 merge하지 않는다.
- 팀 간 완료 전달에는 실행 명령, 결과, 실패 재현, 미검증 항목과 담당자를 포함한다.
- blocker는 발견 즉시 WU·영향 화면·필요 결정·최종 결정자를 기록해 공유한다.

## 12. 위험과 대응

| 위험 | 대응 |
|---|---|
| rerun command 재전송 | pending key·body 보존, terminal 확인 |
| rerun SSE 재연결 | cursor·dedupe·polling fallback |
| storage bridge 실패 | session-only 경고·복사 안내 |
| component 책임 확대 | UUID·SSE transport만 허용 |
| multi-tab stale | expected version·sync·자동 재제출 금지 |
| private 노출 | model 분리·unknown reject·session/DOM/log 검사 |
| countdown 과도한 rerun | fragment 범위 제한·server offset |
| admin UUID 오인 | 사설망·Backend 403·fail-closed |

## 13. Definition of Done

- [ ] 해당 WU 하나 이하만 변경했는가?
- [ ] 두 앱이 독립 Streamlit process로 유지되는가?
- [ ] Front가 규칙·승패·phase·자동 행동을 계산하지 않는가?
- [ ] API enum·field가 정본·OpenAPI와 일치하는가?
- [ ] command가 legal action·target·version·deadline에 묶였는가?
- [ ] rerun이 command 중복이나 domain 전이를 만들지 않는가?
- [ ] 다른 player private 정보가 payload·session·HTML·log에 없는가?
- [ ] UUID 외 정보를 local storage·URL에 넣지 않았는가?
- [ ] loading·empty·error·pending·reconnect가 구현됐는가?
- [ ] 회귀·E2E·320px·200%·keyboard 검증을 완료했는가?
- [ ] secret·실제 사용자 데이터가 diff·fixture·log에 없는가?
- [ ] root·Front README가 현재 구현과 일치하는가?
- [ ] 승인 없이 commit·push하지 않았는가?

## 14. 팀장 최종 검토

- [ ] WU와 화면·API 계약이 모든 정본과 일치한다.
- [ ] 닉네임·OAuth·Front HMAC이 다시 포함되지 않았다.
- [ ] `app.py`는 초기화·route만 담당한다.
- [ ] widget state와 Backend authoritative state가 분리된다.
- [ ] rerun·refresh·multi-tab 복구 방안이 명확하다.
- [ ] custom component 책임이 UUID·SSE로 제한된다.
- [ ] SSE가 인증 header를 포함한 streaming fetch로 구현되고 CORS 계약이 승인됐다.
- [ ] mutation이 `PENDING_TO_RENDER → IN_FLIGHT → terminal` 순서로 한 번만 실행된다.
- [ ] Pydantic model이 `extra="forbid"`로 고정되고 정본 projection을 명시한다.
- [ ] WU-F1·F5·F6·F8 browser E2E가 필수 gate로 실행된다.
- [ ] private-by-construction, idempotency와 fail-closed가 적용된다.
- [ ] 성공·거부·offline·접근성 기준이 모두 측정 가능하다.

## 15. 착수 순서

1. 본 계획과 custom component 경계를 승인한다.
2. F1 branch에서 OIDC·HMAC 참조와 삭제 후보를 조사·보고한다.
3. 승인된 F1 범위만 구현·검증하고 README를 갱신한다.
4. CP-1 이후 F2부터 WU 단위로 진행한다.
5. F2~F7 뒤 CP-5 사용자 흐름 E2E를 수행한다.
6. 마지막으로 독립 관리자 앱 F8·F10과 CP-6을 검증한다.

계획 승인만으로 파일 삭제·commit·push가 승인되는 것은 아니다.
