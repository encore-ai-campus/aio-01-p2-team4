# AI 마피아 Frontend–Backend 연동 인계 요약

**목적:** Frontend와 Backend 담당자가 서로의 내부 구현을 공유하지 않고도 공개 API를
정확히 연결하기 위한 최소 합의사항을 정리한다.

**정본:** [마스터플랜](../01_core/AI_MAFIA_MASTER_PLAN.md) · [API 계약](../01_core/AI_MAFIA_API_SPEC.md) ·
[화면 흐름](AI_MAFIA_SCREEN_FLOW.md) · [독립 개발 계약](../01_core/AI_MAFIA_INDEPENDENT_CONTRACT.md)

상세 구현은 각 섹터 계획서를 따르며, 충돌 시 위 정본을 우선한다.

## 1. 담당 경계

| Frontend | Backend |
|---|---|
| Streamlit 화면과 widget·session 상태 | authoritative 게임 상태와 규칙 판정 |
| UUID browser 저장과 요청 header 전달 | UUID 검증·user upsert·game ownership |
| `legal_actions`·`valid_targets` 렌더링 | phase·role·deadline·target 최종 검증 |
| 입력 형식 사전 검증 | command 성공·거부 최종 판정 |
| snapshot·operation 적용과 중복 제거 | snapshot·sync·SSE projection 생성 |
| pending·오류·reconnect UI | transaction·idempotency receipt·event ordering |

Front는 DB·Redis·LLM·MCP·internal API를 호출하지 않는다. Backend는 화면 상태를
가정하지 않고 공개 계약만 제공한다.

## 2. 공통 요청 계약

| 항목 | 합의 값 |
|---|---|
| API prefix | `/api/v1` |
| 사용자 식별 | UUID v4 `X-User-Id`; 인증 증명이 아님 |
| 요청 추적 | UUID `X-Request-Id` |
| 변경 POST | UUID v4 `Idempotency-Key` 필수 |
| game command | `expected_state_version` 필수 |
| JSON | UTF-8 `application/json` |
| 시간 | UTC RFC 3339 |
| 성공 | `{data, meta:{request_id,server_time,replayed?}}` |
| 오류 | `{error:{code,message,request_id,retryable,details}}` |

- Front→Backend OAuth, `Authorization`, email, profile과 Front HMAC은 사용하지 않는다.
- Front는 `user_id`를 URL·body에 중복하지 않는다.
- Backend는 알 수 없는 request field를 `422 VALIDATION_ERROR`로 거부한다.
- Front는 모든 response를 Pydantic `extra="forbid"` model로 검증한다.
- 결과 불명 POST만 같은 key·같은 body로 재시도한다. body가 바뀌면 새 key를 쓴다.

## 3. 공개 endpoint 인계표

| Front WU | Backend WU | Method·path | 연결 완료 증거 |
|---|---|---|---|
| F1 | B1 | 공통 `X-User-Id` 처리 | UUID 정상·누락·잘못된 형식·ownership contract test |
| F2 | B5 | `POST /api/v1/games` | 6~9명, idempotency replay, `snapshot_url` |
| F2 | B5 | `GET /api/v1/games` | empty·status·cursor·limit fixture |
| F3·F6 | B5 | `GET /api/v1/games/{game_id}` | public·human-private projection test |
| F3·F4·F6 | B5 | `POST /api/v1/games/{game_id}/commands` | command별 성공·거부·stale matrix |
| F5 | B5·B7 | `GET /api/v1/games/{game_id}/sync` | DELTA·SNAPSHOT·no-change·gap test |
| F5 | B5·B7 | `GET /api/v1/games/{game_id}/events` | SSE reconnect·complete batch·CORS test |
| F7 | B5 | `POST /api/v1/feedback` | GENERAL·GAME·중복 409 test |
| F8 | B8 | `GET /api/v1/admin/games` | filter·pagination·403 test |
| F8 | B8 | `GET /api/v1/admin/games/{game_id}` | 진행 중 private redaction test |
| F8 | B8 | `GET /api/v1/admin/metrics` | 기간·지표·403 test |
| F10 | B8 | `GET /api/v1/admin/speech-analytics` | AI 공개 발언·임베딩 주제·coverage·403 test |

Backend는 통합 전에 실제 `/openapi.json`, 성공·오류 예시와 synthetic fixture를 제공한다.
Front는 같은 fixture에 대한 Pydantic validation·화면 분기 결과를 제공한다.

## 4. Command 계약

모든 command는 하나의 endpoint와 discriminated union을 사용한다.

| `type` | 추가 body | Front 주의사항 |
|---|---|---|
| `BEGIN_GAME` | 없음 | 성공 뒤 snapshot/sync 확인 |
| `SPEAK` | `window_id`, `message` | 정규화 후 1~200자 |
| `PASS` | `window_id` | 본인 발언 차례만 표시 |
| `SUBMIT_NIGHT_ACTION` | `window_id`, `target_player_id` | role·ATTACK 등 subtype 전송 금지 |
| `SUBMIT_VOTE` | `window_id`, `target_player_id` | Backend `valid_targets`만 선택 |
| `SAVE_AND_EXIT` | 없음 | 사망자에게도 legal이면 표시 |
| `RESUME` | 없음 | `SAVED`에서만 표시 |
| `FAST_FORWARD` | 없음 | 인간 사망·진행 중일 때만 표시 |

Backend 성공 응답은 `command_id`, `command_type`, `accepted_state_version`,
`result_state_version`, `sync_url`을 반환한다. Front는 성공 응답으로 phase를 직접 바꾸지
않고 `sync_url` 또는 snapshot GET으로 확정한다.

## 5. Snapshot·private 정보

Backend snapshot의 공통 구조는 `game`, `scenario`, `players`, `me`, `action_window`,
`legal_actions`, `public_events`, `result`다.

- `players`에는 공개 정보만 포함한다.
- `me`에는 현재 인간 본인의 role·alibi·observation·private event만 포함한다.
- 다른 player의 role·fact·조사·보호·공격·개별 투표는 종료 전 반환하지 않는다.
- 처형 role만 즉시 공개하고 밤 사망 role은 종료 전 숨긴다.
- `result`는 `COMPLETED`에서만 전체 공개 범위를 제공한다.
- 관리자 진행 게임도 role·private fact·개별 행동·seed·Agent context를 받지 않는다.
- Front는 허용되지 않은 field를 가려서 보관하지 않고 model validation에서 거부한다.

## 6. Sync·SSE 계약

Polling과 SSE는 동일한 `game_sync` envelope를 사용한다.

```text
game_id, mode, from_state_version, state_version,
last_sequence, operations, snapshot
```

- `DELTA`: `snapshot=null`, 완전한 operation batch
- `SNAPSHOT`: `operations=[]`, authoritative snapshot
- 중복 key: `(game_id, front_sequence, operation_index)`
- gap·unknown operation·불완전 batch·version 역행: 부분 적용 금지, snapshot 재조회
- SSE 한 event에는 한 `front_sequence`의 전체 operation을 index 순으로 포함
- heartbeat comment는 operation으로 처리하지 않음

### 착수 전 필수 합의: SSE header와 CORS

Frontend Streamlit component는 native `EventSource` 대신 browser
`fetch + ReadableStream`을 사용한다.

```text
X-User-Id: 현재 browser UUID
X-Request-Id: 연결별 새 UUID
Last-Event-ID: 마지막 적용 front_sequence
```

Backend는 모든 origin에서 위 GET header와 CORS preflight를 허용한다. Front host·port를
Backend에 사전 등록하지 않으며 credentials는 사용하지 않는다. UUID query parameter
방식은 사용하지 않는다. origin 개방은 사용자 UUID·게임 소유권·관리자 allowlist 검사를
우회하지 않는다.

### 기본 timing

| 정책 | 값 |
|---|---|
| foreground polling | 2초 |
| background polling | 10초, 복귀 즉시 sync |
| sync backoff | 2→4→8→16→최대 30초, ±20% jitter |
| `STALE` | 연속 sync 실패 5회 |
| SSE reconnect | 1→2→4→8→최대 30초, ±20% jitter |
| polling 중 SSE 재시도 | 30초마다 1회 |

부하 시험으로 값을 바꿀 때 Front와 Backend가 합의하고 문서·테스트를 함께 갱신한다.

## 7. 공통 오류 처리

| 오류 | Front 처리 | Backend 보장 |
|---|---|---|
| `MISSING_USER_ID` | UUID 초기화 | UUID 누락 400 |
| `GAME_NOT_FOUND` | 소유권 구분 없는 홈 안내 | 미소유·부재 모두 동일 404 |
| `STALE_STATE_VERSION` | 입력 폐기·sync·재확인 | command 자동 재적용 없음 |
| `IDEMPOTENCY_KEY_REUSED` | 자동 재전송 중단 | 다른 body 재사용 409 |
| `ACTION_ALREADY_SUBMITTED` | snapshot 재조회 | 최초 유효 제출만 유지 |
| `WINDOW_CLOSED` | 입력 잠금·sync | deadline 최종 판정 |
| `PLAYER_DEAD` | 관전 전환 | 사망자 command 거부 |
| `GAME_BUSY` | 읽기 sync backoff | 안전한 retryable 오류 |
| `FEEDBACK_ALREADY_SUBMITTED` | 제출 완료 안내 | game당 한 건 409 |
| `ADMIN_ACCESS_DENIED` | cache 제거·거부 화면 | allowlist fail-closed 403 |
| `DEPENDENCY_UNAVAILABLE` | UUID·화면 유지·재시도 | secret 없는 503 |

분기 기준은 HTTP message가 아니라 `error.code`다. 양쪽 log에는 secret, raw prompt,
private snapshot과 전체 header를 남기지 않는다.

## 8. 전달물과 확인 순서

| 시점 | Backend 전달 | Frontend 전달 |
|---|---|---|
| CP-0 | OpenAPI 초안·SSE/CORS 계약 | 화면별 필요 field·fixture 목록 |
| CP-1 | UUID·ownership API test 결과 | UUID header·복구 contract test |
| F2~F4/B5 | create·snapshot·command fixture | payload validation·화면 guard 결과 |
| F5/B7 | SSE·sync 동일 batch·disconnect 결과 | dedupe·gap·reconnect E2E 결과 |
| CP-5 | 전체 공개 API와 오류 matrix | 생성→저장→재개→종료→feedback E2E |
| CP-6 | admin redacted schema·speech analytics·403 결과 | 관리자 fail-closed·coverage·DOM 비노출 E2E |

### 변경·질문 규칙

1. 계약 질문에는 정본 파일·section·예시 payload를 함께 적는다.
2. fixture에는 `schema_version`과 기준 정본 commit을 기록한다.
3. 실제 응답이 fixture와 다르면 Front 호환 alias를 만들지 않고 먼저 계약을 수정한다.
4. field·enum·header·CORS·오류 변경은 양쪽 영향 확인과 정본 갱신 전 merge하지 않는다.
5. 완료 전달에는 실행 명령, 결과, 실패 재현, 미검증 항목과 다음 담당자를 포함한다.
6. blocker에는 관련 WU, 영향 화면·endpoint, 필요한 결정과 결정자를 기록한다.

## 9. 공동 완료 조건

- [ ] `/openapi.json`의 path·union·enum·필수 header가 API 정본과 일치한다.
- [ ] UUID 정상·오류·ownership과 idempotency replay를 양쪽 contract test로 검증했다.
- [ ] 모든 command의 성공·거부·stale·deadline 경계를 확인했다.
- [ ] polling과 SSE가 같은 batch를 중복·누락 없이 재구성한다.
- [ ] SSE header·CORS 또는 proxy 계약이 구현·검증됐다.
- [ ] 공개·human-private·admin projection 비간섭 테스트를 통과했다.
- [ ] Front가 게임 판단을 하지 않고 Backend 응답만 표현한다.
- [ ] 생성→저장→재개→관전→종료→feedback E2E를 통과했다.
- [ ] 실제 secret·사용자 데이터·private payload가 fixture·DOM·log에 없다.
- [ ] 변경된 정본과 양쪽 README가 실제 구현과 일치한다.
