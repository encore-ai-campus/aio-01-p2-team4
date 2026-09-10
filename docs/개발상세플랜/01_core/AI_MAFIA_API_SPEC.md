# AI 마피아 MVP API 명세서

**상위 계약:** [AI_MAFIA_MASTER_PLAN.md](AI_MAFIA_MASTER_PLAN.md)

**데이터 계약:** [AI_MAFIA_DB_DESIGN.md](../02_backend_data/AI_MAFIA_DB_DESIGN.md)

**화면 소비자:** [AI_MAFIA_SCREEN_FLOW.md](../04_frontend/AI_MAFIA_SCREEN_FLOW.md)

**MCP 구현 설계:** [AI_MAFIA_MCP_SERVER_DESIGN.md](../03_mcp_agent/AI_MAFIA_MCP_SERVER_DESIGN.md)

**HTTP prefix:** `/api/v1`

> **현재 MCP 구현 참고 (2026-09-05):** Backend의 현재 최소 연결은 별도 공개 `/api/v1`
> MCP API가 아니라 `/internal/mcp/context`, `/internal/mcp/prompts/{name}`와
> `/internal/mcp/actions` synthetic endpoint만 제공한다. 이 문서의 Engine·MCP
> 확장 계약은 실제 게임 규칙과 함께 후속 구현할 때 적용한다.

이 문서는 일반 사용자 Front, 관리자 Front, Backend와 Mafia Game MCP 사이의 API
정본이다. 구현 완료 시 FastAPI가 생성하는 `/openapi.json`과 이 문서의 path, enum,
필수 field와 오류 코드가 일치해야 한다. 별도 수기 OpenAPI YAML은 관리하지 않는다.

## 1. 공통 규칙

### 현재 FastMCP actor projection 보완 (2026-09-07)

최소 연결의 `GET /internal/mcp/context`는 필수 `game_id`, `user_id`와 선택
`player_id`, `scope`를 받는다. scope 기본값은 `public`이며 허용 값은 8.2절의
다섯 scope다. 사용자 소유권과 player의 해당 게임 소속·AI 여부를 검증한 뒤
8.2절 envelope/data를 반환한다. actor 없는 요청은 공개 scope만 허용하며 인간
snapshot의 `me`를 재사용하지 않는다. 없는 게임·다른 소유자는 404, 잘못된
actor/scope 조합은 403으로 거부한다. UUID만으로 사용자를 구분하는 사설 MVP
경계는 유지하며 과거 bootstrap/HMAC 설계를 재도입하지 않는다.

이 내부 adapter는 진행 중 실제 OPEN window가 있을 때만 context를 제공하며
ROLE_REVEAL·SAVED·COMPLETED 또는 window 없는 상태는 409 ACTION_NOT_ALLOWED로
거부한다. actor 없는 public은 GM/game_id envelope이고 AI의 gm-guide 요청은
403이다. actor의 persona/facts 필수 자료가 없으면 403으로 거부하며 다른 사람의
자료나 임의 window UUID로 보충하지 않는다.

기존 `mafia://context/current/{game_id}/{user_id}`는 공개 조회로 유지하고, AI 호출은
`mafia://context/scoped/{game_id}/{user_id}/{player_id}/{scope}`를 사용한다. MCP는
URI를 위 endpoint 인자로 전달하는 얇은 adapter이며 DB 접근·독자 projection을
만들지 않는다. scope별 `data`는 8.2절을 유일한 정본으로 삼는다. Backend client는
envelope의 state_version/window_id를 검증하고 각 scope를 따로 조회한다.
두 Resource의 JSON text content는 `mimeType: application/json`으로 명시한다.

관련 책임은 WU-B7(내부 context endpoint·actor projection), WU-M3(기존 Resource
등록부·HTTP adapter), WU-B6(Agent client·Provider 입력 연결)로 나눈다. 공개
`agent_activity`는 AI 판단 입력에 재삽입하지 않는다.

### 1.1 전송과 형식

- JSON request·response는 UTF-8 `application/json`을 사용한다.
- 모든 시각은 UTC RFC 3339 문자열이며 예시는 `2026-09-02T12:34:56.123Z` 형식이다.
- 사용자·게임·player·window·command·event 같은 runtime ID는 canonical hyphen UUID
  문자열이다. `scenario_id`, `persona_id`처럼 정적 카탈로그 ID는 문서에 등록된
  대문자 snake case 또는 안정적인 문자열 key다.
- 알 수 없는 request field는 `422 VALIDATION_ERROR`로 거부한다.
- pagination은 opaque `cursor`와 `limit`을 사용하며 `limit` 기본 20, 최대 100이다.
- 사용자 입력 문자열은 제어 문자를 거부하고 Unicode NFC, 줄바꿈과 연속 공백을
  계약에 맞게 정규화한다. 화면 출력에서도 HTML escape한다.
- 공개 오류에는 stack trace, DB 정보, secret, prompt와 비공개 게임 상태를 넣지 않는다.

### 1.2 요청 header

| Header | 대상 | 계약 |
|---|---|---|
| `X-User-Id` | `/api/v1` 사용자·관리자 API | 필수 UUID v4, 사용자 구분값이며 인증 증명 아님 |
| `X-Request-Id` | 모든 HTTP API | 선택 UUID, 없으면 Backend가 생성 |
| `Idempotency-Key` | 변경하는 공개 `/api/v1` `POST` | 필수 UUID v4, terminal 응답 전까지 같은 값을 재사용 |
| `Last-Event-ID` | SSE reconnect | 마지막으로 적용한 Front sequence 문자열 |

일반 Front가 보내는 `Authorization`, OIDC token, email, `acting_user_id`, timestamp
서명과 HMAC header는 정의하지 않는다. Front는 URL·body에 `user_id`를 중복 전달하지
않는다.

### 1.2.1 Front 연결 정책

Backend가 cross-origin으로 제공될 때는 Front의 실행 host·port를 사전 등록하지 않고
모든 browser origin에 다음 정책을 적용한다.

- 허용 method: `GET`, `POST`, `DELETE`, `OPTIONS`
- 허용 request header: `X-User-Id`, `X-Request-Id`, `Idempotency-Key`,
  `Last-Event-ID`, `Content-Type`
- 허용 credentials: 사용하지 않음
- 허용 origin: `*`; 요청 origin별 allowlist 환경 설정을 사용하지 않음
- preflight: 모든 origin을 허용하되 허용되지 않은 method·header는 성공 응답으로 허용하지 않음

same-origin proxy를 사용하는 배포에서는 proxy가 위 header와 `text/event-stream` 응답을
Backend까지 전달한다. origin 개방은 브라우저의 CORS 읽기 제한만 해제하며 사용자 UUID·
게임 소유권·관리자 allowlist 검사를 대체하지 않는다. credentials를 허용하지 않으므로
cookie 기반 인증을 이 계약에 추가하지 않는다.

### 1.3 사용자 UUID 수명주기

1. Front가 브라우저 첫 실행에 UUID v4를 생성해 same-origin local storage에 저장한다.
2. Front 서버는 읽은 UUID를 `X-User-Id`로 Backend에 전달한다.
3. 게임 생성 또는 feedback 같은 최초 쓰기에서 Backend가 최소 사용자 행을 멱등 생성한다.
4. 사용자가 UUID 복구 값을 바꾸면 이후 요청부터 새 UUID scope만 보인다.
5. UUID만 아는 사용자는 그 UUID의 게임을 요청할 수 있다. 따라서 MVP는 접근이 통제된
   개발·사설 환경에서만 사용한다.

### 1.4 성공 envelope

일반 JSON 성공 응답은 다음 envelope를 사용한다.

```json
{
  "data": {},
  "meta": {
    "request_id": "2c2cb976-af58-4c90-a3aa-d98ee0bd0fde",
    "server_time": "2026-09-02T12:34:56.123Z"
  }
}
```

목록 응답은 `data.items`, `data.next_cursor`를 사용한다. 다음 page가 없으면
`next_cursor`는 `null`이다.

### 1.5 오류 envelope

```json
{
  "error": {
    "code": "STALE_STATE_VERSION",
    "message": "게임 상태가 변경되었습니다. 최신 상태를 불러오세요.",
    "request_id": "2c2cb976-af58-4c90-a3aa-d98ee0bd0fde",
    "retryable": true,
    "details": {
      "current_state_version": 12
    }
  }
}
```

`message`는 안전한 고정 한국어 문구다. Front는 분기와 분석에 `code`만 사용한다.

| HTTP | 코드 | 의미 |
|---:|---|---|
| 400 | `MISSING_USER_ID` | `X-User-Id` 누락 |
| 400 | `INVALID_REQUEST` | JSON·query 조합 오류 |
| 403 | `ADMIN_ACCESS_DENIED` | 관리자 allowlist 불일치 |
| 403 | `PLAYER_DEAD` | 사망한 인간의 발언·투표·밤 행동 command |
| 403 | `ACTION_NOT_ALLOWED` | 현재 actor·role에 허용되지 않은 행동 |
| 404 | `GAME_NOT_FOUND` | game 없음, 다른 UUID 소유 또는 15분 사용자 무동작으로 삭제됨, 구분하지 않음 |
| 404 | `RESOURCE_NOT_FOUND` | 기타 리소스 없음 |
| 409 | `STALE_STATE_VERSION` | expected version 불일치 |
| 409 | `IDEMPOTENCY_KEY_REUSED` | 같은 key를 다른 요청에 사용 |
| 409 | `ACTION_ALREADY_SUBMITTED` | 같은 window에 다른 key로 두 번째 제출 |
| 409 | `WINDOW_CLOSED` | 마감·해소·취소된 window |
| 409 | `INVALID_PHASE` | command와 phase 불일치 |
| 409 | `GAME_BUSY` | 짧은 동시 해소 또는 저장 충돌 |
| 409 | `GAME_ALREADY_ENDED` | 종료 게임 변경 시도 |
| 409 | `GAME_NOT_SAVED` | 진행 게임에 `RESUME` 시도 |
| 409 | `FEEDBACK_ALREADY_SUBMITTED` | 같은 게임의 두 번째 game feedback |
| 422 | `VALIDATION_ERROR` | UUID version, enum, 길이·대상 검증 실패 |
| 429 | `RATE_LIMITED` | 인프라 보호 제한 |
| 503 | `DEPENDENCY_UNAVAILABLE` | DB·Redis·MCP 등 필수 경계 장애 |

### 1.6 Idempotency와 optimistic concurrency

- `POST /games`, `/games/{game_id}/commands`, `/feedback`은 `Idempotency-Key`가
  필수다.
- Backend는 principal, route scope, key와 canonical request hash를 영구 저장한다.
- key unique 범위는 현재 `X-User-Id` 전체다. request hash는 대문자 method, concrete
  path의 `game_id`, canonical query와 정규 JSON body를 포함한다.
- 동일 요청 replay는 현재 UUID의 소유권을 다시 확인한 뒤 최초 HTTP status와 불변
  terminal 결과를 반환하고 `meta.replayed=true`를 동적으로 추가한다.
- receipt에는 snapshot, 현재 legal action, 상대 시간과 `deadline_at`을 저장하지 않는다.
  replay 뒤 현재 상태가 필요하면 GET 또는 sync를 호출한다.
- 같은 key와 다른 request hash는 `409 IDEMPOTENCY_KEY_REUSED`다.
- game command body는 `expected_state_version`을 필수로 가진다.
- version 불일치 command를 자동 재적용하지 않는다. Front가 sync한 뒤 사용자의
  의도를 다시 확인한다. 단, 사용자 요청으로 예약한 자유 토론 `SPEAK`는 동일
  사용자·게임·생존자·단계·회차·마감 범위와 최신 `legal_actions`를 검증한 뒤,
  확정된 `409 STALE_STATE_VERSION` 또는 같은 토론의 AI 창 교체로 인한
  `409 WINDOW_CLOSED`에 한해 최신 버전/창과 새 key로 순서대로 자동 재시도할 수 있다.
  `429 SPEECH_RATE_LIMITED`는 순서를 유지하며 대기하고, 응답 불명 요청은 최초
  body/key로만 확인한다. 다른 단계로 예약을 옮기지 않는다. Backend의 버전·마감
  검사와 멱등성 계약은 그대로 유지한다. `SAVE_AND_EXIT`은 화면 버전과의 일치 검사를 하지 않고
  게임 행 잠금 뒤 서버의 마지막 확정 상태를 저장한다. 해당 요청의 양의 정수
  `expected_state_version`은 요청 hash에 남겨 동일 요청 재전송을 구분하는 데만 사용한다.
- 다른 AI의 미해소 private submission과 Agent reservation은 Front projection을
  바꾸지 않으므로 공개 `state_version`을 올리지 않는다. phase 해소·공개 event 또는
  인간 본인 private 상태가 바뀔 때 version을 올린다.
- 진행 중 투표의 내부 AI 제출은 미해소 상태라면 `result_state_version`이 현재
  version과 같다. 인간의 같은 window 첫 투표만으로 한 버전 증가한 경우에는 해당
  submission의 `observed_state_version`으로 증명한 AI 판단만 계속 적용할 수 있다.
  공개 사용자 command에는 이 예외를 적용하지 않는다. 내부 투표 context client는 같은
  window·phase에서 이 한 버전 차이만 허용하고, 저장 전 원장이 원인을 최종 검증한다.
  window 변경·저장/재개·deadline 만료 결과는 거부하며 이전 표를 새 투표에 옮기지 않는다.

## 2. 공통 모델

### 2.1 Enum

```text
GameStatus = IN_PROGRESS | SAVED | COMPLETED | FAILED

GamePhase = ROLE_REVEAL | DAY_DISCUSSION | NIGHT_ACTION |
            DAY_VOTE | REVOTE | FINAL_DISCUSSION |
            FINAL_ACCUSATION | ENDED

Role = MAFIA | DETECTIVE | DOCTOR | CITIZEN
Faction = MAFIA | CITIZEN

LegalAction = BEGIN_GAME | SPEAK | PASS | SUBMIT_NIGHT_ACTION |
              SUBMIT_VOTE | SAVE_AND_EXIT | RESUME | FAST_FORWARD
```

### 2.2 공개 player

```json
{
  "player_id": "0fa54b68-a42a-4d52-81dd-8a59e54eb269",
  "seat": 1,
  "display_name": "플레이어 1",
  "kind": "HUMAN",
  "alive": true,
  "revealed_role": null,
  "eliminated_phase": null,
  "eliminated_round": null
}
```

`revealed_role`은 처형된 player 또는 게임 종료 뒤에만 설정한다. 밤 사망자는 종료
전까지 `null`이다.

### 2.3 action window

```json
{
  "window_id": "11137761-d31b-46d1-8fb0-144ecf436069",
  "kind": "VOTE",
  "cycle": 1,
  "paused": false,
  "opened_state_version": 17,
  "server_time": "2026-09-02T12:34:56.123Z",
  "deadline_at": "2026-09-02T12:35:26.123Z",
  "remaining_ms": 30000,
  "turn_player_id": null,
  "has_submitted": false,
  "legal_actions": ["SUBMIT_VOTE", "SAVE_AND_EXIT"],
  "valid_targets": [
    {
      "player_id": "70d5bd5d-61da-4db4-b218-6d0ac41f2a08",
      "display_name": "플레이어 2"
    }
  ]
}
```

진행 중 발언 window에는 규칙상 마감이 없으므로 `deadline_at`과 `remaining_ms`가
`null`이다. 진행 중 밤·투표 계열은 둘 다 값이 있고 `paused=false`다.
`status=SAVED` snapshot은 기존 window를 `paused=true`로 유지하며 `deadline_at=null`,
timed window의 동결된 `remaining_ms`만 값으로 반환한다. untimed window는 두 시간
field가 모두 `null`이다. 저장 상태의 top-level `legal_actions`는 `RESUME`만 포함하고
window 안의 `legal_actions`는 빈 배열이다. Front countdown은 표시용이며 제출 가능
여부는 Backend 응답이 결정한다.

`action_window` 자체는 nullable이다. `ROLE_REVEAL`, window 사이의 안정 상태,
`COMPLETED`, `FAILED`에는 `null`일 수 있다. `status=SAVED`에서 저장 당시 window가
없었다면 역시 `null`이며 top-level `legal_actions=["RESUME"]`만 반환한다.

### 2.4 snapshot

```json
{
  "game": {
    "game_id": "d9ae9b5d-1d17-4f80-8f1a-276bfe170412",
    "status": "IN_PROGRESS",
    "phase": "DAY_DISCUSSION",
    "round": 1,
    "day_number": 2,
    "state_version": 12,
    "last_sequence": 42,
    "ruleset_version": "mystery-v1",
    "scenario_version": "scenario-v1",
    "player_count": 6,
    "mafia_count": 1,
    "fast_forward_enabled": false,
    "updated_at": "2026-09-02T12:34:56.123Z"
  },
  "scenario": {
    "scenario_id": "BLACKOUT_STUDIO",
    "title": "정전된 방송국",
    "background": "생방송을 준비하던 방송국에서 PD가 사망했습니다.",
    "victim": "생방송 PD",
    "locations": ["스튜디오", "조정실", "분장실", "대기실", "장비실"]
  },
  "players": [
    {
      "player_id": "0fa54b68-a42a-4d52-81dd-8a59e54eb269",
      "seat": 1,
      "display_name": "플레이어 1",
      "kind": "HUMAN",
      "alive": true,
      "revealed_role": null,
      "eliminated_phase": null,
      "eliminated_round": null
    },
    {
      "player_id": "70d5bd5d-61da-4db4-b218-6d0ac41f2a08",
      "seat": 2,
      "display_name": "플레이어 2",
      "kind": "AI",
      "alive": true,
      "revealed_role": null,
      "eliminated_phase": null,
      "eliminated_round": null
    },
    {
      "player_id": "e15f18b6-ea20-477e-9d99-8a22dc6048f5",
      "seat": 3,
      "display_name": "플레이어 3",
      "kind": "AI",
      "alive": true,
      "revealed_role": null,
      "eliminated_phase": null,
      "eliminated_round": null
    },
    {
      "player_id": "b2177718-e0eb-43b4-a585-225da47ced78",
      "seat": 4,
      "display_name": "플레이어 4",
      "kind": "AI",
      "alive": true,
      "revealed_role": null,
      "eliminated_phase": null,
      "eliminated_round": null
    },
    {
      "player_id": "c38f59b7-c26c-4638-9980-31a26cffd997",
      "seat": 5,
      "display_name": "플레이어 5",
      "kind": "AI",
      "alive": true,
      "revealed_role": null,
      "eliminated_phase": null,
      "eliminated_round": null
    },
    {
      "player_id": "d46579fc-9520-4a29-9d9d-d804e7986fc5",
      "seat": 6,
      "display_name": "플레이어 6",
      "kind": "AI",
      "alive": true,
      "revealed_role": null,
      "eliminated_phase": null,
      "eliminated_round": null
    }
  ],
  "me": {
    "player_id": "0fa54b68-a42a-4d52-81dd-8a59e54eb269",
    "role": "DETECTIVE",
    "alive": true,
    "spectator": false,
    "alibi": "정전 당시 조정실에서 방송 장비를 확인하고 있었다.",
    "observation": "정전 직전 누군가 장비실 방향으로 이동하는 것을 봤다.",
    "private_events": []
  },
  "action_window": {
    "window_id": "11137761-d31b-46d1-8fb0-144ecf436069",
    "kind": "SPEECH",
    "cycle": 1,
    "paused": false,
    "opened_state_version": 12,
    "server_time": "2026-09-02T12:34:56.123Z",
    "deadline_at": null,
    "remaining_ms": null,
    "turn_player_id": "0fa54b68-a42a-4d52-81dd-8a59e54eb269",
    "has_submitted": false,
    "legal_actions": ["SPEAK", "PASS", "SAVE_AND_EXIT"],
    "valid_targets": []
  },
  "legal_actions": ["PASS", "SPEAK", "SAVE_AND_EXIT"],
  "public_events": [],
  "result": null
}
```

- 일반 사용자 snapshot은 소유 게임의 인간 player 비공개 정보만 포함한다.
- 다른 player의 role, 알리바이, 관찰, 조사, 보호, 공격과 개별 투표를 넣지 않는다.
- AI GM context와 MCP resource는 이 Front snapshot을 재사용하지 않고 audience별
  projection을 별도로 만든다.
- 사망한 인간도 이미 허용됐던 자기 role·알리바이·관찰·private event는 계속 받지만
  다른 player의 private 정보는 종료 전 받지 않는다.
- 종료 snapshot의 `result`에는 2.5절의 전체 role·action 공개 기록을 넣는다.

### 2.4.1 AI 처리 상태 표시

일반 snapshot에 선택적 `agent_activity` 배열을 추가한다. 미지원 또는 재시작 직후는
빈 배열이다. 게임 소유권 확인 뒤 같은 게임의 최근 공개 발언 처리 기록만 최대
50개를 순서대로 반환한다. 이 정보는 진행 보조 표시이며 command version이나
SSE cursor를 바꾸지 않는다. `NIGHT_ACTION`과 진행 중 투표의 actor별 기록은 공개
배열에 넣지 않는다. Front는 해당 phase에서 공통 비공개 처리 안내를 표시한다.

각 item은 다음 field만 갖는다.

| field | 계약 |
|---|---|
| `sequence` | 해당 Backend 실행 내 단조 증가 양의 정수 |
| `run_id` | 서버 실행 UUID; 재시작 시 변경 |
| `created_at` | UTC RFC 3339 |
| `player_id` | 같은 게임의 AI player UUID |
| `phase` | `DAY_DISCUSSION` 또는 `FINAL_DISCUSSION` |
| `state_version` | 관찰한 상태 버전, 양의 정수 |
| `stage` | `STARTED`, `CONTEXT_READY`, `DECIDING`, `DECIDED`, `APPLIED`, `FALLBACK`, `FAILED`, `SKIPPED` |
| `action` | `SPEAK`, `PASS` 또는 `null`; 적용 전 선택과 적용 완료를 stage로 구별 |
| `summary` | Backend가 enum에서 만드는 고정 한국어 안내, 최대 200자 |
| `decision_source` | 선택적 `MODEL`, `DUMMY`, `FALLBACK` 또는 `null`; 과거 응답의 필드 생략 허용 |
| `reason_code` | 선택적 실패 분류 코드 또는 `null`; 아래 allowlist만 허용 |
| `decision_basis` | 선택적 공개 판단 근거 코드 또는 `null`; 아래 allowlist만 허용 |

`reason_code`는 `PROVIDER_TIMEOUT`, `PROVIDER_AUTHENTICATION`, `PROVIDER_RATE_LIMIT`,
`PROVIDER_MODEL_UNAVAILABLE`, `PROVIDER_INCOMPLETE`, `PROVIDER_UNAVAILABLE`,
`PROPOSAL_INVALID`, `MCP_UNAVAILABLE`, `MCP_SUBMISSION_FAILED`,
`AGENT_DEPENDENCY_ERROR`만 허용한다. `decision_basis`는 `PUBLIC_EVIDENCE`,
`COMPARE_STATEMENTS`, `ASK_FOR_CLARIFICATION`, `INSUFFICIENT_EVIDENCE`,
`NO_NEW_INFORMATION`만 허용하며 Backend가 고정 한국어로 설명한다. 이는 모델이
선택한 공개 근거 유형이며 내부 사고 원문이나 사실의 진위 검증 결과가 아니다.
SPEAK의 기존 `public_rationale` 문자열 중 위 코드에 정확히 일치하는 값만 표시한다.
PASS의 `public_rationale`는 null 또는 위 코드만 허용한다. 밤·투표 proposal에는
기존처럼 rationale를 넣지 않으며 공개 진행 배열에도 기록하지 않는다.
새 Provider 요청은 현재 job의 행동 enum과 위 근거 코드로 출력 schema를 제한한다.

summary는 모델이 생성한 내부 사고나 원문 rationale가 아니다. 자유 형식 Provider
문자열·발언 원문·대상·비공개 역할은 이 배열과 운영 로그에 복사하지 않는다.
`APPLIED`는 mutation이 성공 반환한 뒤에만 기록한다. 취소되거나 오래된 작업은
성공으로 표시하지 않는다. Front는 field를 검증하고 텍스트를 escape한다.

### 2.5 종료 결과

`result`는 `status=COMPLETED`에서만 object이며 그 전에는 `null`이다.

```json
{
  "winner": "CITIZEN",
  "win_reason": "ALL_MAFIA_ELIMINATED",
  "finished_at": "2026-09-02T12:34:56.123Z",
  "players": [
    {
      "player_id": "0fa54b68-a42a-4d52-81dd-8a59e54eb269",
      "display_name": "플레이어 1",
      "role": "DETECTIVE",
      "alive": true,
      "eliminated_phase": null,
      "eliminated_round": null
    }
  ],
  "nights": [
    {
      "round": 1,
      "attack_choices": [],
      "resolved_attack_target_player_id": null,
      "protect_player_id": null,
      "investigations": [],
      "killed_player_id": null
    }
  ],
  "votes": [
    {
      "round": 1,
      "phase": "DAY_VOTE",
      "ballots": [],
      "counts": [],
      "eliminated_player_id": null
    }
  ],
  "public_event_ids": []
}
```

`win_reason` enum:

```text
ALL_MAFIA_ELIMINATED
MAFIA_PARITY
FINAL_MAFIA_SELECTED
FINAL_NON_MAFIA_SELECTED
```

`attack_choices`, `investigations`와 `ballots`는 종료 뒤 공개되는 actor·target·자동 선택
여부의 구조화 배열이다. 내부 추론, prompt와 raw model response는 포함하지 않는다.

배열 item은 `actor_player_id`, `target_player_id`(같은 게임 UUID), `is_auto`(boolean)를
갖고 investigations에는 `is_mafia` boolean을 추가한다. nights의 보호 대상은 UUID
또는 null이며 counts는 5.1절의 후보별 집계다. 마피아 전원 미응답의 진영 자동 선택은
개별 attack_choices를 창작하지 않고 확정 공격 대상에만 반영한다. 오래된 게임에
확정 해소 원장이 없으면 누락된 선택을 추정하지 않고 해당 기록을 빈 배열로 반환한다.

## 3. 상태 확인

### 3.1 `GET /health`

프로세스 liveness만 확인한다. DB·Redis를 호출하지 않는다.

```json
{
  "status": "ok"
}
```

### 3.2 `GET /ready`

Backend가 새 요청을 받을 준비가 됐는지 확인한다.

```json
{
  "status": "ready",
  "dependencies": {
    "postgresql": "ok",
    "redis": "ok"
  }
}
```

Provider와 MCP health는 게임 생성 준비를 막지 않는다. 실제 Agent turn에서 실패하면
규칙 fallback을 사용한다. readiness 응답은 secret, URL과 오류 원문을 포함하지 않는다.

## 4. 사용자 게임 API

### 4.1 `POST /api/v1/games`

새 게임을 만들고 역할 공개 상태를 반환한다. `X-User-Id`, `Idempotency-Key` 필수다.

Request:

```json
{
  "player_count": 6,
  "ruleset_version": "mystery-v1",
  "scenario_version": "scenario-v1"
}
```

Validation:

- `player_count`는 6~9다.
- 두 version은 현재 지원 값과 정확히 일치해야 한다.
- 사용자별 직전 성공 게임 scenario를 제외하고 seed로 결정한다.
- 같은 사용자의 동시 create는 직렬화한다.

Response `201`:

```json
{
  "data": {
    "game_id": "d9ae9b5d-1d17-4f80-8f1a-276bfe170412",
    "status": "IN_PROGRESS",
    "phase": "ROLE_REVEAL",
    "round": 0,
    "state_version": 1,
    "snapshot_url": "/api/v1/games/d9ae9b5d-1d17-4f80-8f1a-276bfe170412"
  },
  "meta": {
    "request_id": "2c2cb976-af58-4c90-a3aa-d98ee0bd0fde",
    "server_time": "2026-09-02T12:34:56.123Z",
    "replayed": false
  }
}
```

생성만으로 첫날 발언은 시작하지 않는다. Front는 성공 뒤 `snapshot_url`을 GET해 역할
화면을 그리고 별도 `BEGIN_GAME`을 제출한다. create replay가 과거 snapshot을 반환하지
않으므로 이미 진행된 game도 현재 상태로 열린다.

생성은 첫 사용자 동작이다. 이후 성공한 공개 사용자 command가 없고 15분이 지나면
`IN_PROGRESS` 게임과 종속 원장을 자동 삭제한다. GET·sync·SSE polling과 AI·자동 진행은
사용자 동작 시간을 연장하지 않는다. `SAVE_AND_EXIT`가 성공한 `SAVED` 게임과 종료 상태는
이 정책의 삭제 대상이 아니다. 삭제 시 생성 receipt도 함께 정리되므로 같은 생성
`Idempotency-Key`를 15분 보존 경계 뒤 다시 제출하면 새 게임 생성 요청으로 처리한다.

### 4.2 `GET /api/v1/games`

현재 UUID가 소유한 게임을 최신 갱신 순으로 반환한다.

Query:

| 이름 | 값 |
|---|---|
| `status` | 선택, `IN_PROGRESS`, `SAVED`, `COMPLETED`, `FAILED` |
| `cursor` | 선택 opaque cursor |
| `limit` | 선택 1~100 |

Response `200` item:

```json
{
  "game_id": "d9ae9b5d-1d17-4f80-8f1a-276bfe170412",
  "status": "SAVED",
  "phase": "NIGHT_ACTION",
  "round": 2,
  "day_number": 2,
  "state_version": 21,
  "scenario_title": "정전된 방송국",
  "player_count": 6,
  "human_alive": true,
  "winner": null,
  "can_resume": true,
  "updated_at": "2026-09-02T12:34:56.123Z"
}
```

알 수 없는 UUID는 `200` 빈 목록을 받는다. 정리된 게임은 목록에 포함하지 않는다.

### 4.3 `GET /api/v1/games/{game_id}`

현재 authoritative snapshot을 반환한다. 다른 UUID 소유 게임은 존재 여부를 숨기기
위해 `404 GAME_NOT_FOUND`다. 15분 사용자 무동작으로 정리된 진행 게임도 같은 응답을
사용해 삭제 여부와 과거 존재를 별도로 공개하지 않는다. 삭제 전에 시작한 command의
재전송도 receipt가 함께 정리된 뒤에는 replay하지 않고 같은 `404`를 반환한다.

Response `200`: `data`는 2.4절 snapshot이다.

### 4.3.1 `DELETE /api/v1/games/{game_id}`

게임 이탈 팝업에서 사용자가 `게임 삭제`를 선택하면 호출한다. `X-User-Id`와
양의 정수 query `expected_state_version`이 필수이며 body는 없다. 게임 행을
잠근 뒤 소유권·버전을 확인하고 `IN_PROGRESS` 또는 `SAVED` 게임만 삭제한다.
성공은 HTTP 200, 공통 envelope의 `data={"game_id":"<uuid>","deleted":true}`다.
없는 게임·타인 소유는 동일한 404 `GAME_NOT_FOUND`, 버전 불일치는 409
`STALE_STATE_VERSION`, 완료·실패 상태는 409 `INVALID_GAME_STATUS`다.
DELETE는 별도 Idempotency-Key나 receipt를 생성하지 않는다. 응답 유실 시 동일
game ID·버전으로 재시도하며, 이미 삭제됐다면 404를 반환한다. Front는 해당 삭제
요청의 404도 더 이상 접근 가능한 게임이 없는 상태로 처리하고 홈으로 이동한다.
DB commit 뒤 Redis 공개 이력을 정리하며, Redis 실패는 삭제 성공을 취소하지 않는다.

### 4.4 `POST /api/v1/games/{game_id}/commands`

모든 게임 변경의 단일 endpoint다. `Content-Type`과 `type`으로 union member를
구분한다. 성공은 `200`이며 비동기 operation ID를 만들지 않는다.

공통 성공 응답:

```json
{
  "data": {
    "command_id": "d57fac33-4f83-46fb-99dd-1d27fd724b5c",
    "command_type": "SPEAK",
    "accepted_state_version": 12,
    "result_state_version": 13,
    "sync_url": "/api/v1/games/d9ae9b5d-1d17-4f80-8f1a-276bfe170412/sync"
  },
  "meta": {
    "request_id": "2c2cb976-af58-4c90-a3aa-d98ee0bd0fde",
    "server_time": "2026-09-02T12:34:56.123Z",
    "replayed": false
  }
}
```

`command_id`는 요청 `Idempotency-Key`와 같은 UUID다.
`accepted_state_version`은 request를 검증한 mutation 이전 version이고
`result_state_version`은 성공 commit 뒤 version이다. 응답은 snapshot을 포함하지 않으며
Front는 `sync_url` 또는 game GET으로 현재 상태를 확인한다.

#### `BEGIN_GAME`

```json
{
  "type": "BEGIN_GAME",
  "expected_state_version": 1
}
```

`ROLE_REVEAL`에서만 허용하며 `DAY_DISCUSSION`, day 1, round 0으로 전환한다.

#### `SPEAK`

```json
{
  "type": "SPEAK",
  "expected_state_version": 12,
  "window_id": "11137761-d31b-46d1-8fb0-144ecf436069",
  "message": "조정실 근처에 있던 사람의 설명을 먼저 듣고 싶습니다."
}
```

현재 인간 player의 `DAY_DISCUSSION` 또는 `FINAL_DISCUSSION` 발언 차례에만 허용한다.
정규화한 본문은 1~200자다.

#### `PASS`

```json
{
  "type": "PASS",
  "expected_state_version": 12,
  "window_id": "11137761-d31b-46d1-8fb0-144ecf436069"
}
```

첫날 낮(`DAY_DISCUSSION`, `day_number=1`)에는 인간·AI 모두 금지하며 새 요청은
`409 ACTION_NOT_ALLOWED`로 거부한다. 이후 토론에는 기존 발언 권한을 적용한다.
첫날 snapshot의 `legal_actions`에는 `PASS`를 넣지 않는다. 이미 확정된 receipt의
멱등 재응답은 보존하며 거부된 새 요청은 상태·발언 원장·이벤트를 변경하지 않는다.

#### `SUBMIT_NIGHT_ACTION`

```json
{
  "type": "SUBMIT_NIGHT_ACTION",
  "expected_state_version": 20,
  "window_id": "11137761-d31b-46d1-8fb0-144ecf436069",
  "target_player_id": "70d5bd5d-61da-4db4-b218-6d0ac41f2a08"
}
```

Backend가 인간의 저장 role로 `ATTACK`, `INVESTIGATE`, `PROTECT`를 결정한다. client가
role이나 action subtype을 보내지 않는다. 시민, 사망자와 이미 제출한 actor는 거부한다.

#### `SUBMIT_VOTE`

```json
{
  "type": "SUBMIT_VOTE",
  "expected_state_version": 27,
  "window_id": "11137761-d31b-46d1-8fb0-144ecf436069",
  "target_player_id": "70d5bd5d-61da-4db4-b218-6d0ac41f2a08"
}
```

`DAY_VOTE`, `REVOTE`, `FINAL_ACCUSATION`에서만 허용한다. 후보는 snapshot의
`valid_targets` 중 하나여야 하고 자기 자신은 선택할 수 없다.

#### `SAVE_AND_EXIT`

```json
{
  "type": "SAVE_AND_EXIT",
  "expected_state_version": 27
}
```

게임이 `IN_PROGRESS`이고 window가 `RESOLVING`이 아닌 안정 상태에서 허용한다. 열린
timed window가 있으면 게임 행·window 잠금 획득 뒤 계산한 남은 서버 시간을 저장한다.
화면의 `expected_state_version`이 서버 버전과 달라도 저장을 거부하지 않으며,
`accepted_state_version`은 실제 저장 직전의 서버 버전이다. 예를 들어 화면이 27이고
서버가 29이면 확정 상태 29를 저장해 결과 버전 30을 반환한다. 과거 버전으로 원장을
되돌리거나 확정된 event·submission을 버리지 않는다. 아직 확정되지 않은 Agent 응답은
기다리지 않고 저장 후 state/window 재검증으로 거부한다. 같은 body·Idempotency-Key의
재전송은 최초 저장 결과를 replay하며 다시 저장하거나 저장 시간을 갱신하지 않는다.
소유권·안정 상태 검증과 `RESUME` 등 다른 command의 버전 일치 요구는 유지한다.

#### `RESUME`

```json
{
  "type": "RESUME",
  "expected_state_version": 28
}
```

`status=SAVED`에서만 허용한다. timed window에 저장된 남은 시간이 있을 때만 새
`deadline_at`을 만든다. untimed 발언 window는 deadline 없이 복원하고
`ROLE_REVEAL`처럼 window가 없던 상태는 `action_window=null`을 유지한다. phase, role과
scenario는 저장 당시 값을 복원한다.

#### `FAST_FORWARD`

```json
{
  "type": "FAST_FORWARD",
  "expected_state_version": 31
}
```

인간 player가 사망한 진행 게임에서만 허용한다. Backend는 관전자의 행동을 대신
제출하지 않고 `fast_forward_enabled=true`를 영구 저장한 뒤 남은 AI turn을 자동 진행
모드로 바꾼다. `FAST_FORWARD_ENABLED` event와 이후 진행은 sync/SSE로 전달한다.

### 4.5 command 허용표

| 조건 | 허용 command |
|---|---|
| `ROLE_REVEAL`, 인간 생존 | `BEGIN_GAME`, `SAVE_AND_EXIT` |
| 인간의 발언 차례 | `SPEAK`, `PASS`, `SAVE_AND_EXIT` |
| 다른 player 발언 차례 | `SAVE_AND_EXIT` |
| `NIGHT_ACTION`, 인간 특수 역할·미제출 | `SUBMIT_NIGHT_ACTION`, `SAVE_AND_EXIT` |
| `NIGHT_ACTION`, 시민 또는 제출 완료 | `SAVE_AND_EXIT` |
| 투표 phase, 인간 생존·미제출 | `SUBMIT_VOTE`, `SAVE_AND_EXIT` |
| `SAVED` | `RESUME` |
| 인간 사망·진행 중 | `FAST_FORWARD`, `SAVE_AND_EXIT` |
| `COMPLETED`·`FAILED` | 없음 |

## 5. 동기화 API

### 5.1 operation 모델

polling과 SSE는 같은 operation 모델을 사용한다.

현재 Backend의 nested 전송 형식도 허용한다. 바깥 batch는 `front_sequence`,
`state_version`, `operations`를 가지며, 안쪽 각 operation은 `schema_version: 1`,
`operation_index`, `type`, `payload`를 가진다. 바깥 sequence/version을 상속할 뿐
원장의 index나 schema를 새로 추정하지 않는다. flat 형식에는 위 공통 필드를 모두
포함한다. 명시된 schema가 없거나 서로 충돌하면 전체 batch를 거부한다.

```json
{
  "schema_version": 1,
  "front_sequence": 43,
  "operation_index": 0,
  "state_version": 13,
  "type": "APPEND_PUBLIC_EVENT",
  "payload": {
    "event_id": "a7dd582b-bcad-4d91-b045-1c771128e380",
    "event_type": "PLAYER_SPOKE",
    "created_at": "2026-09-02T12:34:56.123Z",
    "data": {
      "player_id": "70d5bd5d-61da-4db4-b218-6d0ac41f2a08",
      "message": "조정실에 있었습니다."
    }
  }
}
```

허용 operation type:

```text
SET_GAME_STATE
REPLACE_PLAYERS
SET_PRIVATE_STATE
SET_ACTION_WINDOW
CLEAR_ACTION_WINDOW
APPEND_PUBLIC_EVENT
APPEND_PRIVATE_EVENT
SET_RESULT
```

Front는 `(game_id, front_sequence, operation_index)`를 기준으로 operation을 한 번만
적용한다. 하나의 client-visible transaction은 Front sequence 한 개와 index 0부터
연속인 operation batch가 된다. 이 값은 PUBLIC event와 인간 본인의 private event에만
배정된다. 다른 AI의 private event는 Front sequence나 공개 `state_version`을 올리지
않는다. 알 수 없는 type·`schema_version`, sequence gap 또는 batch index gap이 있으면
batch 일부를 적용하지 않고 snapshot을 다시 요청한다.

operation payload 계약:

| Type | payload 필수 field |
|---|---|
| `SET_GAME_STATE` | `status`, `phase`, `round`, `day_number`, `state_version`, `fast_forward_enabled` |
| `REPLACE_PLAYERS` | `players` 공개 player 배열 |
| `SET_PRIVATE_STATE` | `me`, 현재 인간 본인 projection |
| `SET_ACTION_WINDOW` | 2.3절 action window |
| `CLEAR_ACTION_WINDOW` | `window_id` |
| `APPEND_PUBLIC_EVENT` | 아래 `PublicEvent` |
| `APPEND_PRIVATE_EVENT` | 아래 `PrivateEvent`, 현재 인간 대상만 |
| `SET_RESULT` | 2.5절 종료 결과 |

`PublicEvent` 공통 field는 UUID `event_id`, 아래 enum `event_type`, UTC RFC 3339
`created_at`, 폐쇄형 object `data`이고 모두 필수다.

| `event_type` | `data` 필수 field |
|---|---|
| `GAME_BEGAN` | `message` |
| `TURN_OPENED` | `player_id`, `cycle`, `prompt` nullable |
| `PLAYER_SPOKE` | `player_id`, `message` |
| `PLAYER_PASSED` | `player_id` |
| `NIGHT_RESOLVED` | `round`, `killed_player_id` nullable |
| `VOTE_RESOLVED` | `round`, `phase`, `counts`, `tied`, `needs_revote` |
| `PLAYER_EXECUTED` | `player_id`, `revealed_role` |
| `FAST_FORWARD_ENABLED` | `enabled` true |
| `GAME_SAVED`·`GAME_RESUMED` | `phase`, `round` |
| `GAME_ENDED` | `winner`, `win_reason` |

`PublicEvent`와 각 `data` object는 표에 적힌 field만 갖는 폐쇄형 union이다.
`GAME_BEGAN.message`는 마스터플랜 3.4절의 고정 시작 문구다. player 관련 ID는 같은
game의 공개 player UUID다. `PLAYER_SPOKE.message`는 공백 정규화 뒤 1~200자,
`TURN_OPENED.cycle`은 1 또는 2다. 첫날은 항상 1이며 둘째 날부터 첫 순환이 전원
PASS일 때만 한 번 더 순환한다. 추가 순환의 `prompt`는 마스터플랜의 고정 질문이며
그 밖에는 `null`이다.
`NIGHT_RESOLVED`와 `VOTE_RESOLVED.round`는 1~5,
저장·재개 event의 `round`는 0~5다. `NIGHT_RESOLVED.killed_player_id`는 UUID 또는
`null`, `PLAYER_EXECUTED.revealed_role`은 2.1절 `Role`이다.
`VOTE_RESOLVED.phase`는 `DAY_VOTE`, `REVOTE`, `FINAL_ACCUSATION` 중 하나다.
`VOTE_RESOLVED.tied`는 최다 득표 동률 여부의 boolean이고 `needs_revote`는
첫 낮 투표 동률로 재투표를 여는 경우만 true다.
`VOTE_RESOLVED.counts`는 `target_player_id` UUID와 `vote_count` 0 이상 정수만 가진
폐쇄형 item 배열이다. 해소 당시 유효 후보를 좌석 오름차순으로 한 번씩 포함하고 각
count는 생존 투표자 수 이하이며 합계는 확정된 유효 표 수와 같다. actor, 자동 선택
여부와 개별 ballot은 종료 전 포함하지 않는다.
`GAME_ENDED.winner`는 2.1절 `Faction`, `win_reason`은 2.5절 enum이다.

현재 인간에게 허용하는 `PrivateEvent`는
`INVESTIGATION_RESULT {round, target_player_id, is_mafia}`와
`NIGHT_ACTION_ACCEPTED {round, action_type, target_player_id}`다. 다른 player의 private
event는 operation으로 만들지 않는다.

각 operation은 PostgreSQL `game_events.operation_type`, `schema_version`과 `payload`에
동일한 형태로 영구 저장된다. 한 visible transaction이 여러 operation을 만들면 같은
`front_sequence`와 연속 index를 사용하므로 Redis stream이 trim돼도 DB에서 완전한
batch를 다시 만들 수 있다.

### 5.2 sync envelope

```json
{
  "data": {
    "game_id": "d9ae9b5d-1d17-4f80-8f1a-276bfe170412",
    "mode": "DELTA",
    "from_state_version": 12,
    "state_version": 12,
    "last_sequence": 42,
    "operations": [],
    "snapshot": null
  },
  "meta": {
    "request_id": "2c2cb976-af58-4c90-a3aa-d98ee0bd0fde",
    "server_time": "2026-09-02T12:34:56.123Z"
  }
}
```

- `mode=DELTA`면 `snapshot=null`이고 `operations`에 0개 이상의 완전한 batch가
  sequence·index 순으로 들어간다.
- `mode=SNAPSHOT`이면 `snapshot`이 있고 `operations=[]`다. 같은 snapshot을 operation에
  중복하지 않는다.
- 변경이 없어도 `200`, `mode=DELTA`, `operations=[]`을 반환한다.
- `operations=[]`이면 `state_version`과 `last_sequence`는 요청 client 위치에서
  전진하지 않는다. version이 증가한 응답은 대응하는 operation batch가 반드시 있다.

### 5.3 `GET /api/v1/games/{game_id}/sync`

Query:

| 이름 | 필수 | 의미 |
|---|---|---|
| `after_state_version` | 예 | client가 마지막으로 적용한 version, 0 이상 |
| `after_sequence` | 예 | snapshot의 마지막 Front sequence, 0 이상 |

delta가 보존 범위 밖이거나 client version이 서버보다 크면 authoritative snapshot
mode로 응답한다. 소유권과 audience filter는 snapshot endpoint와 동일하다. snapshot의
`last_sequence`와 그 다음 SSE 구독 지점이 하나의 Front-visible sequence를 사용하므로
최초 GET과 SSE 연결 사이의 event도 재요청할 수 있다.

Front 구현에서 `after_state_version`과 `after_sequence`는 polling cursor로 사용하고,
SSE의 `Last-Event-ID`는 같은 `after_sequence`에 해당하는 마지막 Front sequence로
사용한다. Backend는 두 transport에 동일한 `front_sequence`와 완전한 operation batch를
제공해야 하며, 어느 한 transport에서만 증가하는 별도 cursor를 만들지 않는다.

### 5.4 `GET /api/v1/games/{game_id}/events`

`text/event-stream` SSE endpoint다.

```text
id: 43
event: game_sync
data: {"game_id":"...","mode":"DELTA","from_state_version":12,"state_version":13,"last_sequence":43,"operations":[...],"snapshot":null}
```

- `Last-Event-ID`가 있으면 해당 Front sequence 다음부터 재개한다.
- 보존 범위 밖이면 첫 `game_sync` data를 `mode=SNAPSHOT`으로 보낸다.
- 하나의 SSE `game_sync` event는 한 `front_sequence`의 모든 operation을 index 순서로
  포함한다. 같은 batch 일부만 전송하지 않는다.
- heartbeat는 SSE comment로 보내며 game operation으로 처리하지 않는다.
- 연결이 끊겨도 게임 deadline은 계속된다.
- SSE 실패 시 Front는 동일 sync endpoint polling으로 전환한다.
- SSE와 polling이 동시에 같은 Front sequence를 전달해도 client deduplication으로 한 번만
  적용한다.

## 6. 피드백 API

### 6.1 `POST /api/v1/feedback`

`feedback_type` discriminated union이다. `X-User-Id`, `Idempotency-Key`가 필수다.

일반 피드백:

```json
{
  "feedback_type": "GENERAL",
  "rating": 4,
  "comment": "게임 흐름을 더 빠르게 확인할 수 있으면 좋겠습니다.",
  "tags": ["UX"]
}
```

게임별 피드백:

```json
{
  "feedback_type": "GAME",
  "game_id": "d9ae9b5d-1d17-4f80-8f1a-276bfe170412",
  "rating": 5,
  "comment": "추리 과정이 재미있었습니다.",
  "tags": ["BALANCE", "DIALOGUE"]
}
```

Validation:

- `rating`은 1~5다.
- `comment`는 선택이며 정규화 후 1~1000자다.
- tag는 서버 등록 allowlist이고 중복 없이 최대 5개다.
- `GAME`은 현재 UUID가 소유하고 `COMPLETED`인 game만 허용한다.
- 한 사용자는 한 game에 `GAME` feedback을 한 건만 작성한다.
- 피드백은 게임 상태, Agent prompt나 자동 밸런스 조정 입력으로 사용하지 않는다.

Response `201`:

```json
{
  "data": {
    "feedback_id": "e2ee137c-04cb-451c-b913-928d102a8c34",
    "feedback_type": "GAME",
    "created_at": "2026-09-02T12:34:56.123Z"
  },
  "meta": {
    "request_id": "2c2cb976-af58-4c90-a3aa-d98ee0bd0fde",
    "server_time": "2026-09-02T12:34:56.123Z",
    "replayed": false
  }
}
```

## 7. 관리자 API

모든 endpoint는 `X-User-Id`가 `ADMIN_USER_IDS`에 정확히 등록돼야 한다. allowlist가
비어 있거나 파싱에 실패하면 전부 `403 ADMIN_ACCESS_DENIED`다. 관리자 API는
loopback·사설망 전용이며 MVP에서 read-only다.

### 7.1 `GET /api/v1/admin/games`

Query: `status`, `phase`, `cursor`, `limit`.

Item:

```json
{
  "game_id": "d9ae9b5d-1d17-4f80-8f1a-276bfe170412",
  "owner_user_id": "8a2ab744-aea3-4b36-b975-ec73364b4a43",
  "status": "IN_PROGRESS",
  "phase": "NIGHT_ACTION",
  "round": 2,
  "state_version": 21,
  "player_count": 6,
  "open_window_kind": "NIGHT",
  "updated_at": "2026-09-02T12:34:56.123Z"
}
```

### 7.2 `GET /api/v1/admin/games/{game_id}`

진행 상태, version, public events, window metadata와 비밀 없는 failure code를 반환한다.
진행 중인 role, 개인 사실, 개별 행동·투표, seed와 Agent private context는 관리자에게도
반환하지 않는다. 종료 뒤에는 일반 종료 결과 범위만 볼 수 있다.

### 7.3 `GET /api/v1/admin/metrics`

Query `from`, `to`는 최대 31일 범위다.

```json
{
  "data": {
    "games_created": 120,
    "games_completed": 93,
    "games_saved": 12,
    "completion_rate": 0.775,
    "average_rounds": 3.2,
    "wins_by_faction": {"CITIZEN": 49, "MAFIA": 44},
    "auto_action_count": 18,
    "feedback_average": 4.1
  },
  "meta": {
    "request_id": "2c2cb976-af58-4c90-a3aa-d98ee0bd0fde",
    "server_time": "2026-09-02T12:34:56.123Z"
  }
}
```

LLM token·비용·timeout·예산 metric은 제공하지 않는다.

### 7.4 관리자 센터 확장 계약 (2026-09-07)

현재 관리자 센터의 통합 운영 분석·사용자 피드백·관리자 로그 화면에 맞춘 WU-B8 확장이다.
질문 API는 WU-B10에서 추가한 read-only 검색 기능이며, 관리자 화면과 분리된
Backend 계약으로 유지한다.
7.1~7.3의 기존 필드와 UUID allowlist 인증을 유지한다. 공개 데모 키는 HTTP 인증에
사용하지 않는다. 성공 응답은 기존 `data`, `meta.request_id`, `meta.server_time` 형식이다.
각 조회는 성공한 뒤 감사 기록을 저장하며, 조회 또는 감사 저장 실패는
`503 DEPENDENCY_UNAVAILABLE`로 반환한다. 비허용 UUID는 데이터 조회 없이 403이다.

`GET /api/v1/admin/metrics`의 data에 다음 필드를 추가한다.

```json
{
  "users_total": 300,
  "daily_games": [{"date": "2026-09-07", "games_created": 40}]
}
```

- `users_total`: DB users 전체 UUID 수. 기간과 무관하며 실제 사람 수와 동일하지 않을 수 있다.
- 기존 게임 KPI는 games.created_at 기간으로 집계한다. 기간 생략 시 전체 기록이다.
- `daily_games`: UTC 날짜별 생성 수. 기간 생략 시 오늘 포함 최근 30일, 지정 시 해당
  범위(최대 31일 간격). 생성 없는 날짜도 0으로 채운다.
- `auto_action_count`: 해당 게임 집계 범위의 action_submissions 중 source=AUTO인 행 수.
  진영 단위 자동 해소는 별도 submission이 없으면 포함하지 않는다.

### 7.5 `GET /api/v1/admin/role-win-rates`

Query: 선택적 `from`, `to` (7.3과 동일). 종료된 게임(status=COMPLETED)에 참여한
AI(kind=AI)만 포함한다. games.created_at으로 기간을 제한하며 생존 여부와 무관하다.
승률은 해당 직업 AI의 소속 faction이 게임 winner와 일치한 횟수 / 참여 횟수이다.
사람 좌석·진행/저장/실패 게임은 제외한다. 직업 4종은 항상 반환하며 참여 0이면 승률 0이다.
개별 게임·플레이어의 역할은 반환하지 않는다.

```json
{"data":{"items":[
  {"job":"MAFIA","participations":100,"wins":40,"win_rate":0.4},
  {"job":"DETECTIVE","participations":100,"wins":60,"win_rate":0.6},
  {"job":"DOCTOR","participations":100,"wins":60,"win_rate":0.6},
  {"job":"CITIZEN","participations":300,"wins":180,"win_rate":0.6}
]}}
```

### 7.6 `GET /api/v1/admin/persona-win-rates`

Query: 선택적 `from`, `to` (7.3과 동일). 종료된 게임에 참여한 AI만 페르소나별로
집계한다. `agent_personas`의 `display_name`과 짧은 `speech_style`만 화면 설명으로
투영하며, `parameters`, prompt, backstory 원문과 개별 게임·플레이어 정보는 반환하지
않는다. 승률은 해당 페르소나 AI의 소속 faction이 게임 winner와 일치한 횟수 / 참여
횟수이다. 활성 페르소나는 참여 0이어도 반환하며 승률은 0이다.

```json
{"data":{"items":[
  {"persona_id":"CAUTIOUS_ANALYST","persona_name":"신중한 분석가",
   "personality_summary":"근거를 차분히 쌓고 성급한 결론을 피하는 성격",
   "participations":120,"wins":72,"win_rate":0.6}
]}}
```

### 7.7 `GET /api/v1/admin/feedback`

Query: `feedback_type` (GENERAL/GAME), `rating` (1~5), `cursor` (마지막 feedback UUID),
`limit` (기본 20, 최대 100). created_at DESC, id DESC 순서의 커서 페이지 조회다.
필터를 변경하면 cursor를 초기화한다. 존재하지 않는 커서는 빈 페이지를 반환한다.

```json
{"data":{"items":[{
  "feedback_id":"00000000-0000-4000-8000-000000000301",
  "user_id":"00000000-0000-4000-8000-000000000302",
  "feedback_type":"GENERAL","game_id":null,"rating":4,
  "comment":"투표 시간을 더 크게 보고 싶어요.","tags":[],
  "created_at":"2026-09-07T01:00:00Z"
}],"next_cursor":null}}
```

의견은 사용자 입력이므로 HTML로 실행하지 않고 텍스트 표로 표시한다.
이메일·개인 프로필·게임 private context는 조인하거나 반환하지 않는다.

### 7.8 `GET /api/v1/admin/audit-logs`

Query: `event_type` (아래 감사 분류), `cursor` (양의 bigint ID를 표현한 문자열),
`limit` (기본 20, 최대 100). ID DESC 순서이며 ID는 JSON 정밀도 손실을 막기 위해 문자열이다.

```json
{"data":{"items":[{
  "audit_id":"180","admin_user_id":"00000000-0000-4000-8000-000000000201",
  "event_type":"ADMIN_GET_METRICS","target_game_id":null,
  "request_id":"00000000-0000-4000-8000-000000000401",
  "created_at":"2026-09-07T01:00:00Z"
}],"next_cursor":"180"}}
```

DB action을 응답에서는 `event_type`으로 투영한다. 분류는 ADMIN_LIST_GAMES,
ADMIN_GET_GAME, ADMIN_GET_METRICS, ADMIN_GET_ROLE_WIN_RATES, ADMIN_GET_PERSONA_WIN_RATES,
ADMIN_LIST_FEEDBACK, ADMIN_LIST_AUDIT_LOGS, ADMIN_QUERY_INSIGHTS, ADMIN_GET_SPEECH_ANALYTICS,
ADMIN_LIST_AGENT_JOBS이다. 조회 자체의 감사 기록은 조회 후 추가되어 다음 새로고침에서
확인할 수 있다. 이 API는 관리자 조회 감사 기록이며 서버 원문 로그·INFO/WARN 등급은
제공하지 않는다. 신규 목록의 잘못된 cursor/enum/limit/rating은 422 INVALID_REQUEST다.

### 7.9 `POST /api/v1/admin/insights/query`

승인된 `FEEDBACK`, `GAME_SUMMARY`, `OPERATIONS_DOC` 청크를 키워드 검색과 pgvector
cosine 검색으로 함께 조회한다. 이 endpoint는 질문을 위한 POST이지만 게임·문서·사용자
데이터를 변경하지 않는다. `X-User-Id`가 관리자 allowlist를 통과해야 하며, 성공한 질문은
`ADMIN_QUERY_INSIGHTS` action으로 감사 기록된다.

요청 body:

```json
{
  "question": "최근 낮은 평점에서 반복되는 문제는 무엇인가요?",
  "filters": {
    "source_types": ["FEEDBACK", "OPERATIONS_DOC"],
    "rating_lte": 2,
    "from": "2026-09-01T00:00:00Z",
    "to": "2026-09-07T23:59:59Z"
  },
  "top_k": 5
}
```

`question`은 3~500자, `top_k`은 1~10이며 기간은 최대 31일이다. `filters`를 생략하면
세 승인 자료 유형을 모두 검색한다. 비밀값 조회 의도로 보이는 질문과 허용되지 않은 자료
유형은 `422 INVALID_REQUEST`다.

성공 응답:

```json
{
  "data": {
    "answer": "승인된 자료에서 확인된 내용입니다: 사건 설명이 더 명확하면 좋겠습니다.",
    "confidence": "MEDIUM",
    "has_sufficient_evidence": true,
    "sources": [{
      "source_type": "FEEDBACK",
      "source_id": "feedback:00000000-0000-4000-8000-000000000001",
      "title": "사용자 피드백",
      "snippet": "사건 설명이 더 명확하면 좋겠습니다.",
      "score": 0.81
    }]
  },
  "meta": {"request_id": "<uuid>", "server_time": "<timestamp>"}
}
```

근거 점수가 낮으면 `confidence=LOW`, `has_sufficient_evidence=false`와 추가 확인 안내를
반환한다. 응답에는 원문 사용자 식별자, 역할·개별 행동·투표·seed, prompt·token·비용을
포함하지 않는다. 질문 원문은 audit payload에 저장하지 않고 action·request ID·결과 상태만
기록한다.

### 7.10 `GET /api/v1/admin/speech-analytics`

공개 발언 분석이 활성화된 게임에서 `speech_analysis`의 완료 임베딩과 주장 결과를
관리자용 집계로 투영한다. query는 선택적인 `from`, `to`(최대 31일), `game_id`,
`persona_id`, `round`(0~5), `analysis_version`, `limit`(주제 수, 기본 12·최대 20)다.
기간은 발언 원본 event의 `created_at`으로 제한한다. `game_players.kind=AI`인
발언만 포함하며 사람 발언·역할·진영·비공개 context는 조회하지 않는다.

같은 `analysis_version`의 임베딩만 비교하고, 버전을 생략하면
`speech_analysis_versions.activated_at`이 가장 최근인 버전을 선택한다. Backend는
조회 범위에서 최대 500건을 결정적으로 표본화하고 저장된 벡터의 앞 96차원 투영을
사용해 cosine 유사도 0.78 이상의 greedy 묶음을 계산한다. 이 묶음은 설명 가능한
화면용 주제 후보이며 새로운 LLM 호출이나 DB
저장을 시작하지 않는다. 주제별 `keywords`는 원문에서 정규화한 2글자 이상 표현의
빈도이고, `related_terms`는 같은 주제 안에서 함께 나타난 표현이다. 동의어 판정이나
사실 판정으로 해석하지 않는다.

성공 응답의 `coverage`는 대상 공개 AI 발언, 분석 행, 임베딩·주장 완료 수를 각각
보여준다. 표본 상한을 넘으면 `sample_limited=true`로 표시한다. `topics`에는 주제별
에이전트 분포·주장 stance 분포·대표 공개 발언·최대 5개의 근거 발언이 들어가고,
`agents`에는 에이전트별 발언 수·상위 주제·상위 표현이 들어간다. `keywords`는 전체
범위의 상위 표현이다. 모든 공개 원문은 관리자 화면에서 근거를 확인할 수 있도록
그대로 반환하되 HTML로 실행하지 않는다.

```json
{
  "data": {
    "analysis_version": "v1",
    "generated_at": "2026-09-08T02:00:00Z",
    "coverage": {
      "eligible_speeches": 48,
      "analyzed_speeches": 46,
      "embedding_ready": 44,
      "claims_ready": 42,
      "embedding_coverage": 0.9167,
      "claims_coverage": 0.875,
      "sampled_speeches": 44,
      "sample_limited": false
    },
    "topics": [{
      "topic_id": "topic-001",
      "label": "근거 · 투표",
      "speech_count": 12,
      "agent_count": 4,
      "agent_breakdown": [{"persona_id": "CAUTIOUS_ANALYST", "persona_name": "신중한 분석가", "speech_count": 5, "share": 0.4167}],
      "stance_breakdown": [{"stance": "SUSPICION", "count": 6, "share": 0.5}],
      "keywords": [{"term": "근거", "speech_count": 8, "occurrence_count": 10}],
      "related_terms": ["투표", "수상"],
      "representative": {"event_id": "<uuid>", "game_id": "<uuid>", "persona_id": "<id>", "persona_name": "신중한 분석가", "round": 2, "phase": "DAY_DISCUSSION", "message": "...", "created_at": "2026-09-08T01:59:00Z"},
      "evidence": []
    }],
    "agents": [{"persona_id": "CAUTIOUS_ANALYST", "persona_name": "신중한 분석가", "speech_count": 10, "share": 0.2273, "top_topics": [{"topic_id": "topic-001", "label": "근거 · 투표", "speech_count": 5}], "top_keywords": [{"term": "근거", "speech_count": 7, "occurrence_count": 9}], "stance_breakdown": [{"stance": "SUSPICION", "count": 4, "share": 0.4}]}],
    "keywords": [{"term": "근거", "speech_count": 20, "occurrence_count": 27, "agent_count": 5}]
  }
}
```

조회 성공 뒤 `ADMIN_GET_SPEECH_ANALYTICS` 감사 action을 저장한다. DB·감사 저장 실패는
`503 DEPENDENCY_UNAVAILABLE`, 비허용 UUID는 데이터 조회 없이 `403 ADMIN_ACCESS_DENIED`,
잘못된 기간·UUID·버전·limit은 `422 INVALID_REQUEST`다. 응답에는 벡터 배열, claims 원문,
role·faction·개별 행동·투표·seed·prompt·비용을 넣지 않는다.

### 7.11 `GET /api/v1/admin/agent-jobs` (2026-09-09, WU-B8)

팀 DB `public.agent_jobs`의 AI Agent 작업 메타데이터를 조회한다. UUID allowlist와
공통 성공 envelope를 사용한다. Query는 `game_id`(UUID), `job_kind`(SPEECH,
NIGHT_ACTION, VOTE, GM_NARRATION), `status`(RESERVED, SUCCEEDED, FALLBACK, STALE,
FAILED), `cursor`(마지막 job UUID), `limit`(기본 20, 1~100)이다.
`created_at DESC, id DESC`로 정렬하며 필터 변경 시 커서를 초기화한다. 없는 커서는
빈 페이지다. `limit + 1`건만 조회해 다음 페이지 존재 여부를 판단한다.

```json
{"data":{"items":[{
  "job_id":"00000000-0000-4000-8000-000000000501",
  "game_id":"00000000-0000-4000-8000-000000000502",
  "player_id":"00000000-0000-4000-8000-000000000503",
  "player_name":"AI 플레이어",
  "window_id":"00000000-0000-4000-8000-000000000504",
  "job_kind":"SPEECH","status":"SUCCEEDED","reserved_state_version":12,
  "failure_code":null,"created_at":"2026-09-09T01:00:00Z",
  "completed_at":"2026-09-09T01:00:03Z"
}],"next_cursor":null}}
```

`player_name`은 같은 게임 `game_players.display_name`만 읽으며 GM의 `player_id`와
`player_name`은 NULL이다. 진행 중 작업의 `completed_at`은 NULL이다. 실패 분류는
저장된 비밀 없는 `failure_code`만 사용한다. `normalized_proposal`/`normalized_result`,
선택 대상·발언 원문·역할·진영·개인 문맥·lease token·capability는 선택하거나 반환하지
않는다. `SUCCEEDED`/`FALLBACK`은 생성 결과의 상태이며 실제 게임 반영 완료를 뜻하지
않는다. 작업당 현재 상태 한 행이며 재예약·중간 단계의 전체 변경 이력은 아니다.
게임 삭제 시 CASCADE로 삭제된 작업은 조회되지 않는다.

조회 후 `ADMIN_LIST_AGENT_JOBS` 감사 기록을 남기며, 게임 필터를 지정하면 해당 UUID를
`target_game_id`에 기록한다. 비허용 UUID는 조회 없이 403, 잘못된 UUID·enum·limit은
422, 조회·감사 저장 실패는 원문 없는 503이다. 성공 응답은 `Cache-Control: no-store`다.

## 8. Backend 내부 Engine API

> **현재 MVP FastMCP 연결 기준:** 아래 8.1~9절의 Engine HMAC·bootstrap token·MCP
> session 상세는 전체 운영 보안을 위한 후속 프로파일이다. 현재 FastMCP 전환에서는
> MCP가 Resource·Prompt·Tool 컨텍스트를 Backend adapter로 전달하고, 인증·권한·게임
> 상태 판정은 Backend가 담당한다. 현재 작업의 최소 HTTP adapter 계약은
> 현재 실제 코드 상태는
> `docs/개발상세플랜/05_reports/AI_MAFIA_CURRENT_CODE_STATUS.md`에 기록한다. 아래 상세 프로파일을
> 현재 FastMCP WU에 새로 추가하지 않는다.

MCP runtime만 호출하는 별도 private network endpoint다. 일반 Front와 브라우저에
route와 secret을 노출하지 않는다.

### 8.1 요청 인증

필수 header:

```text
X-Engine-Timestamp: 1788352496
X-Engine-Nonce: 53c505b1-6273-4dbf-81bf-746c562fe900
X-Engine-Signature: <base64url HMAC-SHA256>
X-Agent-Capability: <opaque random capability>
```

canonical 서명 입력:

```text
METHOD\n
PATH\n
CANONICAL_QUERY\n
SHA256_HEX(RAW_BODY)\n
TIMESTAMP\n
NONCE
```

- `METHOD`는 대문자, `PATH`는 percent decode를 하지 않은 absolute path다.
- `CANONICAL_QUERY`는 RFC 3986 percent-encoding 뒤 encoded key, encoded value 순으로
  정렬하고 `key=value`를 `&`로 연결한다. 중복 key도 제거하지 않는다.
- body가 없으면 빈 byte string의 SHA-256 hex를 사용한다. timestamp는 10진 Unix
  seconds, nonce는 UUID v4다. signature는 padding 없는 base64url이다.
- `ENGINE_INTERNAL_API_SECRET`으로 HMAC-SHA256 서명하고 constant-time으로 비교한다.
- Backend 수신 시각과 timestamp 차이는 최대 60초다. 서명 검증 뒤 PostgreSQL
  `internal_request_nonces`에 `scope=ENGINE_HMAC`, nonce와 request hash를 INSERT한다.
  unique 충돌은 replay다. Redis는 이미 소비된 nonce cache로만 사용할 수 있고 장애가
  나도 PostgreSQL 판정을 계속한다.
- capability는 Backend CSPRNG가 만든 32-byte padding 없는 base64url 문자열이다.
  Backend는 hash와 `agent_job_id`, `game_id`, `subject_type`, `subject_id`, `phase`,
  `state_version`, `window_id`, 허용 resource·tool, 만료·폐기 상태만 저장한다. raw
  token은 MCP에 한 번 전달하고 DB·log에 남기지 않는다.
- MCP는 capability를 opaque 값으로 보관·전달할 뿐 내용을 decode하거나 검증하지
  않는다. `MCP_SERVER_AUTH_SECRET`도 capability 발급·검증에 사용하지 않는다.
- capability 유효 기간은 현재 phase/window와 보안상 최대 120초 중 이른 값까지다.
  이는 LLM timeout 설정이 아니라 내부 권한의 수명이다.
- HMAC 검증 뒤 Backend가 capability hash, 미폐기, 만료, allowlist와 현재 DB 상태를
  다시 비교한다.
- 실패 이유를 상세히 구분해 외부로 노출하지 않는다.

### 8.2 `GET /internal/v1/agent-context`

Query `scope=public|me|turn|persona|gm-guide` 중 capability가 허용한 하나를 사용한다.

Response:

```json
{
  "context_version": 1,
  "game_id": "d9ae9b5d-1d17-4f80-8f1a-276bfe170412",
  "subject_type": "AI_PLAYER",
  "subject_id": "0fa54b68-a42a-4d52-81dd-8a59e54eb269",
  "phase": "DAY_DISCUSSION",
  "state_version": 12,
  "window_id": "11137761-d31b-46d1-8fb0-144ecf436069",
  "scope": "turn",
  "data": {
    "window_id": "11137761-d31b-46d1-8fb0-144ecf436069",
    "window_kind": "SPEECH",
    "cycle": 1,
    "opened_state_version": 12,
    "server_time": "2026-09-02T12:34:56.123Z",
    "deadline_at": null,
    "turn_player_id": "0fa54b68-a42a-4d52-81dd-8a59e54eb269",
    "allowed_tools": ["propose_speech", "propose_pass"],
    "valid_targets": []
  }
}
```

이 절과 여기서 명시적으로 참조하는 이 API 명세의 공통 모델이 다섯 MCP Resource
`data` 상세 schema의 유일한 정본이다. MCP 구현 설계서나 fixture가 이 schema를 다시
정의해서는 안 된다. 공통 envelope와 모든 하위 object는 폐쇄형이며 명시되지 않은
field를 거부한다. 모든 field는 필수이고, 아래에서 `nullable`로 적은 field만 JSON
`null`을 허용한다. UUID는 canonical hyphen 형식, 시각은 UTC RFC 3339 형식이다.

| 공통 field | 계약 |
|---|---|
| `context_version` | 정수 상수 `1` |
| `game_id` | capability가 고정한 game UUID |
| `subject_type` | `AI_PLAYER` 또는 `GM` |
| `subject_id` | AI player는 자기 `player_id`, GM은 `game_id`와 같은 UUID |
| `phase` | 2.1절 `GamePhase` |
| `state_version` | 1 이상의 정수, capability 발급 버전과 일치 |
| `window_id` | 현재 `agent_jobs.window_id` UUID |
| `scope` | query 및 MCP Resource URI에 대응하는 고정값 |
| `data` | 아래 scope별 폐쇄형 object |

`subject_type`별 허용표는 다음과 같다. 허용되지 않은 scope는 존재 여부를 구분하지
않고 `403 CAPABILITY_DENIED`로 거부하며, 다른 agent ID를 query로 선택할 수 없다.

| subject | `public` | `me` | `turn` | `persona` | `gm-guide` |
|---|---:|---:|---:|---:|---:|
| `AI_PLAYER` | 허용 | 허용 | 허용 | 허용 | 거부 |
| `GM` | 허용 | 거부 | 거부 | 거부 | 허용 |

Backend는 매 GET에서 capability의 미폐기·만료, 현재 job reservation,
game·subject·phase·`state_version`·`window_id`·scope allowlist를 다시
최종 판정한다. 또한 같은 authoritative state에서 projection이
생성됐는지의 provenance와 `public` subject 비의존성, `turn` target과
`public` player의 일치, `gm-guide` source event와 `public` event의 일치 같은
여러 scope에 걸친 의미 불변식을 검증한 뒤 응답한다.

MCP는 8.3절 consume에서 저장한 binding과 단일 GET 응답에서 관측할 수
있는 공통 envelope·해당 `data` 폐쇄형 schema·응답 내 일치
불변식만 검증한다. 다른 scope를 추가 조회하거나 이전 응답을
저장해 cross-scope 의미를 재판정하지 않으며, 이 불변식의 최종
권위는 Backend에 있다.

#### 8.2.1 `scope=public` data

모든 subject에게 같은 game·`state_version`이면 같은 projection을 반환한다. envelope의
subject field 외에는 요청 주체에 따라 달라지는 값이 없어야 한다.

| field | 타입·제약 |
|---|---|
| `game` | 아래에 명시한 공개 game 폐쇄형 object |
| `scenario` | 아래에 명시한 scenario 폐쇄형 object |
| `players` | 아래에 명시한 공개 player 6~9개, `seat` 오름차순 |
| `public_events` | 5.1절 `PublicEvent` 0개 이상, Engine 확정 순서 |

`game`은 `game_id`, `status`, `phase`, `round`, `day_number`, `state_version`,
`last_sequence`, `ruleset_version`, `scenario_version`, `player_count`, `mafia_count`,
`fast_forward_enabled`, `updated_at`만 가진다. `round`는 0~5, `day_number`는 1~6,
`state_version`은 1 이상, `last_sequence`는 0 이상이다. `player_count`는 6~9이고
`mafia_count`는 6~7명이면 1, 8~9명이면 2다. 두 version 값은 각각
`mystery-v1`, `scenario-v1`이다.

`scenario`는 `scenario_id` 1~64자, `title` 1~120자, 비어 있지 않은 `background`,
`victim` 1~120자와 `locations`만 가진다. `locations`는 서로 다른 1~80자 문자열
4~5개다. 공개 player는 `player_id`, `seat` 1~9, `display_name` 1~40자,
`kind=HUMAN|AI`, `alive`, nullable `revealed_role`(2.1절 `Role`), nullable
`eliminated_phase`(2.1절 `GamePhase`), nullable `eliminated_round`(1~5)만 가진다.
배열 안의 `player_id`와 `seat`는 각각 중복되지 않고
`HUMAN`은 정확히 한 명이다. 처형 전·종료 전 role 공개 조건은 2.2절을 따른다.

진행 중 `alive=true` player의 세 탈락 field는 모두 `null`이다. `alive=false`이면
`eliminated_phase`는 `NIGHT_ACTION`, `DAY_VOTE`, `REVOTE`, `FINAL_ACCUSATION` 중 하나고
`eliminated_round`는 non-null이다. 밤 사망자의 `revealed_role`은 종료 전 `null`,
투표로 처형된 player는 즉시 non-null이다. `game.status=COMPLETED`이면 생존 여부와
관계없이 모든 player의 `revealed_role`이 non-null이다.

`game.game_id`, `game.phase`, `game.state_version`은 공통 envelope의 같은 값과 반드시
일치한다. `public_events`에는 `PUBLIC` audience event만 넣고 진행 중 개별 투표,
공격자, 보호 대상, 조사 결과와 다른 player의 role·알리바이·관찰을 넣지 않는다.
`event_id`는 배열 안에서 중복되지 않는다. Front의 종료 `result`는 MCP `public`
Resource에 넣지 않는다.

`VOTE_RESOLVED.data.counts`는 5.1절의 item·정렬·합계 계약을 그대로 사용한다.

#### 8.2.2 `scope=me` data

`AI_PLAYER` 전용이며 다음 field만 포함한다.

| field | 타입·제약 |
|---|---|
| `player_id` | UUID, envelope의 `subject_id`와 같음 |
| `role` | 2.1절 `Role` |
| `alive` | boolean |
| `alibi` | 공백 정규화된 한 문장, 1~240자 |
| `observation` | 공백 정규화된 한 문장, 1~240자 |
| `private_events` | 아래 `PrivateEvent` 0개 이상, Engine 확정 순서 |

`PrivateEvent` 공통 field는 `event_id`, `event_type`, `created_at`, `data`이고 모두
필수다. 허용 union은 다음 두 종류뿐이다.

| `event_type` | `data` 필수 field |
|---|---|
| `INVESTIGATION_RESULT` | `round` 1~5, `target_player_id` UUID, `is_mafia` boolean |
| `NIGHT_ACTION_ACCEPTED` | `round` 1~5, `action_type=ATTACK\|INVESTIGATE\|PROTECT`, `target_player_id` UUID |

`data`도 폐쇄형이다. 이 subject에게 발생한 event만 반환하며, 마피아가 둘이어도 다른
마피아의 role·action·응답 여부를 포함하지 않는다. `event_id`는 배열 안에서 중복되지
않는다.

#### 8.2.3 `scope=turn` data

`AI_PLAYER`의 현재 job 전용이며 다음 field만 포함한다.

| field | 타입·제약 |
|---|---|
| `window_id` | UUID, envelope의 `window_id`와 같음 |
| `window_kind` | `SPEECH`, `NIGHT`, `VOTE`, `REVOTE`, `FINAL_VOTE` |
| `cycle` | 정수 1 또는 2; 첫날은 1, 둘째 날부터 전원 PASS일 때만 추가 순환 2 |
| `opened_state_version` | 1 이상의 정수 |
| `server_time` | 응답 생성 시각 |
| `deadline_at` | `SPEECH`이면 `null`, 나머지는 UTC RFC 3339 시각 |
| `turn_player_id` | `SPEECH`이면 subject UUID, 나머지는 `null` |
| `allowed_tools` | 아래 matrix와 정확히 같은 Tool 이름 배열 |
| `valid_targets` | 아래 target 0~8개, 좌석 오름차순 |

target object는 `player_id` UUID와 `display_name` 1~40자만 가진다. 숨은 role이나
현재 선택 수는 넣지 않는다. `player_id`는 배열 안에서 중복되지 않고 같은 `public`
projection의 생존 player와 일치한다. 자기 자신 제외 규칙을 적용하되 의사의 `NIGHT`
target에만 자기 자신을 허용한다.

| `window_kind` | `allowed_tools` | `valid_targets` |
|---|---|---|
| `SPEECH` | 첫날 낮은 `propose_speech`만, 이후 토론은 `propose_speech`, `propose_pass` | 빈 배열 |
| `NIGHT` | `propose_night_action` | Backend가 role·생존 상태로 확정한 대상 |
| `VOTE`, `REVOTE`, `FINAL_VOTE` | `propose_vote` | Backend가 해당 투표에 확정한 후보 |

`phase`와 `window_kind` 조합은 각각 `DAY_DISCUSSION|FINAL_DISCUSSION`→`SPEECH`,
`NIGHT_ACTION`→`NIGHT`, `DAY_VOTE`→`VOTE`, `REVOTE`→`REVOTE`,
`FINAL_ACCUSATION`→`FINAL_VOTE`만 허용한다. `allowed_tools`는 표의 순서로 중복 없이
직렬화한다. 첫날 판정은 Backend의 `DAY_DISCUSSION`, `day_number=1`을 사용한다.
MCP는 `SPEECH`의 두 허용 배열을 검증하며 최종 PASS 거부는 Backend가 담당한다.
`SPEECH`의 `valid_targets`는 비어 있고 나머지 window는 1~8개다.
`opened_state_version`은 envelope `state_version` 이하이고 timed window의
`deadline_at`은 성공 응답의 `server_time`보다 뒤여야 한다.

MCP는 이 값을 근거로 게임 규칙을 다시 계산하지 않는다. capability와 Engine이 허용한
현재 Tool만 노출하고 제출 시 Backend가 role·phase·target·deadline·version을 다시
검증한다.

#### 8.2.4 `scope=persona` data

`AI_PLAYER` 전용이며 서버에 등록되고 game에 배정된 preset 한 개만 반환한다.

| field | 타입·제약 |
|---|---|
| `persona_id` | 1~64자 안정 ID |
| `version` | 1~32자 |
| `display_name` | 1~40자 |
| `speech_style` | 1~240자 |
| `backstory` | 1~500자 |
| `parameters` | 아래 10개 field만 가진 폐쇄형 object |

`parameters`는 `sociability`, `assertiveness`, `suspicion`, `deception`,
`risk_tolerance`, `memory_recall`, `reasoning_skill`, `emotionality`,
`cooperativeness`, `verbosity`를 정확히 한 번씩 포함한다. 모든 값은 0.0~1.0의
유한 number이다. `reasoning_skill`도 같은 범위를 허용하며 preset 간 동일 값 제약은 없다.
현재 등록 목표는 0.60~0.80이고 기존 0.5도 호환을 위해 유효하다. persona는 말투·표현·
추론 성향 데이터이며 규칙·정보 권한이나 Provider의 모델·추론 effort를 바꾸지 않는다.

#### 8.2.5 `scope=gm-guide` data

`GM` 전용이며 다음 폐쇄형 union이다.

| field | 타입·제약 |
|---|---|
| `narration_kind` | `PUBLIC_EVENT` 또는 `FIXED_MESSAGE` |
| `source_public_event` | 5.1절 `PublicEvent` 한 개 또는 `null` |
| `fixed_message_key` | 아래 고정 key 또는 `null` |

`PUBLIC_EVENT`이면 `source_public_event`만 object이고 `fixed_message_key=null`이다.
`FIXED_MESSAGE`이면 `source_public_event=null`이고 `fixed_message_key`는 다음 중 하나다.

| `fixed_message_key` | 제품 문구 정본 |
|---|---|
| `GAME_INTRO` | 마스터플랜 3.4절 게임 시작 안내 |
| `ALL_PASS_FOLLOW_UP` | 마스터플랜 3.6절 둘째 날 이후 전원 `PASS` 후 고정 질문 |
| `FINAL_ACCUSATION_NOTICE` | 마스터플랜 3.8절 최종 지목 안내 |

`source_public_event`는 현재 GM job을 연 원인 event와 일치하고 같은
`state_version`의 `public.data.public_events`에 같은 `event_id`와 내용으로 존재해야
한다. 이 scope에는 role별 action, 후보 target, 공격자, 보호 대상, 조사 결과, 개별
투표와 private event를 넣지 않는다. Backend projection이 알 수 없는 field나 금지
field를 반환하면 MCP는 조용히 제거해 전달하지 않고 해당 Resource read를
fail-closed한다.

### 8.3 `POST /internal/v1/mcp-bootstrap/consume`

MCP runtime이 MCP 세션 개설 토큰(bootstrap token)과 opaque capability를 받은 직후
Engine HMAC으로 호출한다.

```json
{
  "bootstrap_token": "<signed bootstrap token>"
}
```

Backend는 세션 개설 토큰 서명, claim의 `agent_job_id`·subject·capability hash와
저장된 capability 및 현재 job reservation을 다시 검증한다. 이 요청의
`X-Agent-Capability` header가 유일한 capability 원문이며 body에 중복하지 않는다.
header hash가 세션 개설 토큰 claim·DB hash와 모두 같아야 한다. token nonce를 PostgreSQL
`internal_request_nonces`에
`scope=MCP_BOOTSTRAP`으로 INSERT한다. 성공 응답은 다음 다섯 field만 가진
폐쇄형 object며 모든 field가 필수다.

```json
{
  "status": "CONSUMED",
  "allowed_resource_scopes": ["public", "me", "turn", "persona"],
  "phase": "DAY_DISCUSSION",
  "state_version": 12,
  "window_id": "11137761-d31b-46d1-8fb0-144ecf436069"
}
```

- `status`는 상수 `CONSUMED`다.
- `allowed_resource_scopes`는 `public`, `me`, `turn`, `persona`, `gm-guide`
  순서를 canonical order로 사용하는 중복 없는 nonempty 배열이다.
  `AI_PLAYER`는 `public`, `me`, `turn`, `persona`의 nonempty 부분집합,
  `GM`은 `public`, `gm-guide`의 nonempty 부분집합만 받을 수 있다.
- `phase`는 2.1절 `GamePhase`, `state_version`은 1 이상 정수,
  `window_id`는 capability가 고정한 job window UUID다.
- `status`를 제외한 네 binding 값은 Backend가 token·capability·reservation을
  같은 판정에서 검증할 때 사용한 capability record의 immutable issuance
  metadata를 그대로 반환한 것이다. 현재 상태를 별도로 재계산해 응답
  binding을 바꾸지 않는다.
- 9.1절의 bootstrap claim field는 그대로 유지하며 이 네 binding을
  claim에 추가하지 않는다.

재사용·만료·capability 불일치는 fail-closed한다. MCP는 이 성공
뒤에만 session을 활성화하고 네 binding을 session memory에 저장한다.
`allowed_resource_scopes`는 `resources/list`·read allowlist로, 나머지 세 값은
8.2절 Engine context envelope의 `phase`·`state_version`·`window_id`
교차 검증에 사용한다.

MCP는 Engine consume 성공 응답의 raw JSON을 duplicate member를 허용하지 않는
decoder로 해석한다. duplicate member, invalid JSON, 위 5-field binding 위반은
fail-closed하며 session을 활성화하지 않는다. 기존 `{"status":"CONSUMED"}`
status-only 성공 응답은 더 이상 허용하지 않는 breaking 동기 전환이다. MCP `WU-M3`와
Backend `WU-B7`은 같은 시점에 위 5-field 폐쇄형 응답으로 전환해야 한다.

### 8.4 `POST /internal/v1/agent-proposals` (full proposal contract)

Request:

```json
{
  "proposal_id": "184e0e1d-3083-489d-a2f4-6639f61e59e1",
  "game_id": "d9ae9b5d-1d17-4f80-8f1a-276bfe170412",
  "agent_id": "0fa54b68-a42a-4d52-81dd-8a59e54eb269",
  "window_id": "11137761-d31b-46d1-8fb0-144ecf436069",
  "expected_state_version": 12,
  "proposal": {
    "type": "SPEAK",
    "message": "공개된 발언의 앞뒤가 맞지 않는 부분을 확인하고 싶습니다.",
    "target_player_id": null,
    "public_rationale": "공개 발언의 모순을 확인하는 질문"
  }
}
```

허용 proposal type은 `SPEAK`, `PASS`, `NIGHT_ACTION`, `VOTE`다. Backend는 capability,
reservation, current state와 domain 규칙을 모두 재검증한다.
`proposal_id`가 내부 idempotency key다. 같은 agent가 같은 ID·body를 재전송하면 저장된
terminal 결과를 반환하고 다른 body에 재사용하면 `409 IDEMPOTENCY_KEY_REUSED`다.
별도 `Idempotency-Key` header는 사용하지 않는다.

Response `200`:

```json
{
  "proposal_id": "184e0e1d-3083-489d-a2f4-6639f61e59e1",
  "status": "ACCEPTED",
  "result_state_version": 13
}
```

MCP Tool 성공은 게임 행동의 무조건 성공이 아니라 Backend가 proposal을 검증·반영한
결과다. 만료·폐기·phase·version·subject·audience 불일치를 외부에서 구분하지 않고
`403 CAPABILITY_DENIED`로 거부한다. 상세 분류는 비밀 없는 내부 운영 log에만 남긴다.

### 8.5 `POST /internal/v1/agent-action` (MVP thin adapter contract)

최소 MCP 연결에서는 MCP가 full proposal의 내부 식별자를 조립하지 않는다. 인증된
Backend session·capability가 game, agent, window와 현재 state version을 결정하고,
MCP는 아래 행동 입력만 전달한다. 이 endpoint도 8.1의 Engine HMAC과
`X-Agent-Capability` header 검증을 동일하게 적용한다.

Request:

```json
{
  "action": "PASS",
  "target_player_id": null,
  "message": null
}
```

`action`은 `PASS`, `SPEAK`, `VOTE`, `NIGHT_ACTION` 중 하나이며, `target_player_id`와
`message`는 행동 종류에 따라 nullable이다. 추가 field는 거부한다. Backend는 인증된
session·capability와 현재 game state를 사용해 phase, role, 대상, deadline, 중복 요청을
재검증하고 authoritative engine을 호출한다. MCP는 이 검증을 복제하지 않는다.

Response `200`:

```json
{
  "action": "PASS",
  "status": "ACCEPTED",
  "state_version": 13
}
```

실행 거부, 만료, 잘못된 대상과 상태 충돌의 외부 분류는 Backend 공통 오류 계약을
따르며, MCP는 오류 원문이나 내부 상태를 추가하지 않는다. 기존 8.4 full proposal
endpoint는 Backend·Agent Manager가 직접 사용하는 확장 경로로 유지하고, 최소 MCP
운영 연결은 8.5 endpoint를 사용한다.

## 9. Mafia Game MCP 계약

### 9.1 transport와 session

- endpoint는 `${MAFIA_MCP_URL}` 전체 값이며 기본 개발 예시는
  `http://127.0.0.1:8100/mcp`다.
- MCP Streamable HTTP initialize로 session을 만들고 `Mcp-Session-Id`를 사용한다.
- Backend Agent Manager가 `MCP_SERVER_AUTH_SECRET`으로 서명한 일회성 세션 개설 토큰을
  `Authorization: Bearer <token>`으로 보낸다. raw shared secret 자체를 보내지 않는다.
- 세션 개설 토큰은 먼저 key 정렬·공백 없는 UTF-8 canonical JSON을 padding 없는
  base64url `encoded_payload`로 만든 뒤
  `encoded_payload.base64url(HMAC-SHA256(MCP_SERVER_AUTH_SECRET, ASCII(encoded_payload)))`
  로 직렬화한다. claim은
  `token_type=MCP_BOOTSTRAP`, `agent_job_id`, `game_id`, `subject_type`, `subject_id`,
  `capability_hash`, `iat`, 최대 120초 `exp`와 UUID nonce다.
- claim object는 폐쇄형이다. `capability_hash`는 raw capability byte string의
  SHA-256 lowercase hex 64자이며, `iat`와 `exp`는 UTC Unix seconds 정수다.
  `iat <= current_time < exp`이고 `1 <= exp - iat <= 120`인 경우만 허용하며 clock
  leeway를 적용하지 않는다. 운영 host는 동기화된 시스템 시계를 사용한다.
- bootstrap claim은 위 field를 그대로 유지하며
  `allowed_resource_scopes`, `phase`, `state_version`, `window_id`를 추가하지 않는다.
  이 네 값은 8.3절 consume이 capability record에서 반환한다.
- initialize HTTP 요청의 `X-Agent-Capability` header에 raw opaque capability를 정확히
  한 번 전달한다. MCP는 해당 header를 session memory에만 보관하고 세션 개설 토큰
  signature를 확인한 뒤 8.3절 consume까지 성공해야 session을 연다.
- 최초 initialize 이후 같은 활성 session의 HTTP 요청은 동일 bearer 세션 개설 토큰을
  계속 보내 session owner를 증명하되 `X-Agent-Capability`는 다시 보내지 않는다.
  MCP는 후속 bearer에 대해 서명·claim·만료와 session owner 일치를 검사하지만 이미
  성공한 세션 개설 토큰 consume을 반복하지 않는다. 다른 bearer, 만료 bearer 또는
  capability header 재전송은 session을 닫고 고정 오류로 거부한다.
- session은 정확히 한 `agent_job_id`, `game_id`, `subject_type`과 `subject_id`에
  묶인다. AI player는 `subject_type=AI_PLAYER`, GM은 `subject_type=GM`이다.
- AI player의 `subject_id`는 해당 `player_id`다. GM은 별도 player row를 만들지 않고
  `subject_id`에 현재 `game_id` UUID를 그대로 사용한다.
- Backend Agent Manager는 `agent_jobs` reservation 한 건마다 새 capability, 새 세션
  개설 토큰과 그 nonce, 새 MCP initialize session을 만든다. 같은 subject·phase·
  window·state라도 다른 job에 이 셋을 재사용하지 않는다.
- job이 성공, fallback, stale, 실패(호출 취소 포함) 또는 lease 만료로 끝나면 Backend는
  capability를 폐기하고 session 종료를 시도한다. MCP는 session memory의 capability와
  subject binding을 제거한다. phase·window·state version 변화도 기존 capability를
  즉시 폐기하며 늦은 결과를 새 상태에 자동 rebase하지 않는다.
- transport가 끊기면 소비한 세션 개설 토큰이나 기존 `Mcp-Session-Id`를 다시 쓰지
  않는다. 같은 job lease 안에서 재접속할 수 있을 때도 기존 capability를 먼저
  폐기하고 새 capability·세션 개설 토큰·session으로 시작한다. Backend가 job의 현재
  상태를
  확인할 수 없으면 재접속하지 않고 정의된 fallback을 수행한다.
- 정상 session 종료는 `DELETE /mcp`와 `Mcp-Session-Id`를 사용한다. MCP는 Tool
  terminal 결과, 명시적 DELETE, transport 종료, 세션 개설 토큰·capability 만료와 process
  shutdown에서 session memory를 멱등 폐기한다. idle 요청이 30초 동안 없으면 session을
  종료하며 event store나 외부 저장소로 session을 복원하지 않는다.
- 세션 개설 토큰 consume 응답이 유실되면 해당 initialize와 session을 실패로 닫고 같은
  token을 다시 consume하지 않는다. Backend만 job 상태를 확인한 뒤 살아 있는 job에
  fresh capability·세션 개설 토큰·session을 발급할 수 있다.
- 운영은 검증된 TLS를 사용한다. loopback 개발만 평문 HTTP를 허용한다.

### 9.2 Resource

session이 agent를 이미 고정하므로 URI에서 다른 agent ID를 받지 않는다.
MCP는 raw JSON-RPC 요청을 duplicate member를 허용하지 않는 decoder로 해석하며,
중복 member를 last-value-wins로 병합하지 않고 `-32602`로 fail-closed한다.

| URI | Engine `scope` | 허용 subject | `data` 정본 |
|---|---|---|---|
| `mafia://session/public` | `public` | AI_PLAYER, GM | 8.2.1절 |
| `mafia://session/me` | `me` | AI_PLAYER | 8.2.2절 |
| `mafia://session/turn` | `turn` | AI_PLAYER | 8.2.3절 |
| `mafia://session/persona` | `persona` | AI_PLAYER | 8.2.4절 |
| `mafia://session/gm-guide` | `gm-guide` | GM | 8.2.5절 |

AI GM session은 `public`과 `gm-guide`만 사용할 수 있다. `me`, `turn`, `persona`와
모든 행동 Tool capability를 받지 않는다.

`resources/list`는 8.3절 consume binding의 `allowed_resource_scopes`만
`public`, `me`, `turn`, `persona`, `gm-guide` canonical order로 직렬화한다.
각 descriptor는 `uri`, `name`, `mimeType` 세 field만 가진 폐쇄형 object며
`name`은 scope 문자열, `mimeType`은 `application/json`이다. list는 Engine을
호출하지 않는다. 요청에는 `cursor` field가 아예 없어야 하며 존재하면
`-32602`로 거부한다. 응답은 pagination·`nextCursor`를 제공하지 않는다.

MCP SDK 1.29.1에서 Resource handler 등록으로 initialize 응답에 포함되는
`capabilities.resources`는 `subscribe=false`, `listChanged=false`로 고정한다. 이는 두
기능을 지원하지 않는 canonical 광고다. Resource template과
`resources/templates/list`, `notifications/resources/list_changed`는 제공하지 않는다.

Resource read는 요청 URI와 같은 URI, MIME type `application/json`인 text content를
정확히 한 개 반환한다. text의 JSON은 8.2절 공통 envelope와 해당 `data` schema 전체다.
MCP는 Engine 응답의 subject·scope·version과 폐쇄형 schema를 확인한 뒤 그대로
직렬화하며, 알 수 없거나 금지된 field를 임의로 제거해서 성공 응답으로 바꾸지 않는다.
MCP는 SDK의 `AnyUrl` 정규화 전에 raw `params.uri` 문자열을 상수 registry의 위 다섯
URI와 exact 비교한다. percent-encoding, scheme·host case 변경, trailing slash·문자 등
모든 변형은 거부한다. exact URI가 아니거나 session binding에 허용되지 않은 URI인
경우 존재 여부를 숨기고 Engine 호출 0회로
`-32002 CAPABILITY_DENIED`를 반환한다. 허용된 read 한 번은 해당
scope의 Engine GET을 정확히 한 번만 호출하며 cross-scope 검증을 위한 추가
GET을 하지 않는다.

MCP는 session-local을 포함해 요청 종료 뒤 context cache나 Resource JSON,
model object, 직렬화 text의 retained reference를 남기거나 이후 요청에서 재사용하지
않는다. 한 요청을 decode·검증·직렬화하는 동안의 transient local object까지 금지하는
뜻은 아니다. Engine 실패나 계약 위반에서 stale Resource로 fallback하지 않는다.

### 9.3 Tool

| Tool | 입력 | 허용 상황 |
|---|---|---|
| `propose_speech` | `message`, `public_rationale` | 자기 발언 차례 |
| `propose_pass` | 없음 | 자기 발언 차례 |
| `propose_night_action` | `target_player_id` | 생존 특수 역할의 밤 |
| `propose_vote` | `target_player_id` | 일반·재·최종 투표 |

- `game_id`, `agent_id`, role, phase와 version을 Tool input으로 받지 않는다. session과
  capability에서 가져온다.
- MCP는 입력 schema를 검사한 뒤 내부 Engine API에 전달할 뿐 게임 상태를 직접
  변경하지 않는다.
- 응답에는 `proposal_id`, `status`, `result_state_version`과 고정 오류 코드만 담는다.
- Engine의 terminal 결과를 반환한 뒤 해당 job session은 추가 Tool 호출을 받지 않고
  종료 절차로 이동한다. Backend의 window별 첫 유효 submission 제약이 최종 중복을
  막는다.
- MCP는 Tool 호출을 처음 전달하기 전에 UUID v4 `proposal_id`를 한 번 생성한다.
  Engine 응답이 유실되어 같은 살아 있는 job에서 재시도한다면 동일
  `proposal_id`와 byte-equivalent proposal body를 사용하고 Engine HMAC nonce만 새로
  만든다. 다른 body로 ID를 재사용하거나 stale version·window를 자동 갱신하지 않는다.

#### 9.3.1 고정 오류 매핑

initialize 단계의 HTTP 오류 body는 `{"error":"<code>"}` 하나만 사용한다.
JSON-RPC 오류는 숫자 `code`와 고정 한국어 `message`만 가지며 `data`, upstream body,
exception text와 stack trace를 포함하지 않는다.

| 경계 | 조건 | HTTP/JSON-RPC | 공개 code |
|---|---|---:|---|
| initialize | bearer 또는 capability header 누락·형식 오류 | HTTP 401 | `AUTH_REQUIRED` |
| initialize | 세션 개설 토큰 서명·claim·만료·replay·mismatch 또는 consume 거부 | HTTP 403 | `BOOTSTRAP_DENIED` |
| session | 알 수 없거나 닫힌 `Mcp-Session-Id` | HTTP 404 | `SESSION_NOT_FOUND` |
| protocol | raw JSON-RPC duplicate member, Tool 폐쇄형 입력 오류 또는 `resources/list`의 `cursor` 존재 | `-32602` | `VALIDATION_ERROR` |
| handler | 비활성 session 또는 terminal 뒤 호출 | `-32001` | `SESSION_NOT_ACTIVE` |
| Resource·Engine context | local exact registry·session allowlist 거부 또는 Engine 403·존재 은닉 404 | `-32002` | `CAPABILITY_DENIED` |
| Engine context | timeout·연결 단절·429·5xx | `-32003` | `DEPENDENCY_UNAVAILABLE` |
| Engine context | 그 밖의 1xx·200 외 2xx·3xx·예상 밖 4xx, 잘못된 Content-Type·invalid JSON·duplicate member, 200 응답의 binding·envelope·schema·응답 내부 불변식 위반 | `-32004` | `UPSTREAM_CONTRACT_VIOLATION` |
| proposal | 같은 `proposal_id`의 body conflict | `-32005` | `PROPOSAL_CONFLICT` |
| handler | 분류되지 않은 내부 실패 | `-32603` | `INTERNAL_ERROR` |

- `-32002` message는 `요청한 리소스에 접근할 수 없습니다.`로 고정한다.
- `-32003` message는 `게임 컨텍스트를 불러올 수 없습니다.`로 고정한다.
- `-32004` message는 `게임 컨텍스트 응답 형식이 올바르지 않습니다.`로 고정한다.

위 세 오류에는 `data`를 넣지 않고 Engine response body, 원문 오류·exception text와
stack trace를 노출하지 않는다.

취소는 상위 task로 전파하고 session cleanup을 수행한다. 취소 원문을 별도 protocol
payload로 변환하지 않는다.

### 9.4 구조화 운영 로그와 redaction

이 절은 initialize, 세션 개설 토큰 consume, Resource, Tool, Engine adapter와 session 종료의
성공·거부·예외 경로 모두에 적용한다.

- 구조화 record가 가질 수 있는 application field는 `request_id`, `correlation_id`,
  `operation`, `status`, `duration_ms`, `error_class`뿐이다. `error_class`는 비밀 없는
  폐쇄형 분류이고 exception message를 그대로 사용하지 않는다. 두 ID는 검증된 UUID만
  기록하며 임의 header 문자열을 그대로 복사하지 않는다.
- Resource·Tool request·response payload, target player, game·agent·player ID, private
  context, capability, 세션 개설 토큰, signature, secret, HTTP header, prompt, raw model
  response, exception 전문·stack과 chain-of-thought를 로그에 남기지 않는다.
- logger와 sink의 표준 process metadata는 허용하되 application payload를 자동
  직렬화하지 않는다. formatter·sink 장애도 금지값을 임시 파일이나 spool에 쓰는
  근거가 아니다.
- MCP runtime은 application DB·Redis·queue 기반의 영속 audit outbox를 만들지 않고
  Backend `event_outbox`를 읽거나 쓰지 않는다. sink 종류와 보존 기간은 배포 운영
  정책이며 MCP wire 계약이 아니다.

## 10. Agent 구조화 출력

### 10.1 AI player 결과

LLM adapter가 AI player의 구조화 결과를 Agent Manager에 반환하는 경로에서도
8.4절과 같은 proposal union을 사용한다.

```json
{
  "type": "SPEAK",
  "target_player_id": null,
  "message": "어젯밤 공개 결과를 바탕으로 다시 확인해 보겠습니다.",
  "public_rationale": "공개 정보만 사용한 질문"
}
```

- 추가 field와 자연어 wrapper를 허용하지 않는다.
- 내부 추론 전문을 요청하거나 field로 받지 않는다.
- schema 오류에는 교정을 한 번만 요청하고 이후 fallback한다.
- 모델·추론·출력 계약은 Backend 배포 설정, 역할 전략·말투 지침은 MCP 코드에서 관리하며 사용자·관리자 API로 변경하지 않는다.
- timeout, token 상한, token·비용 반환 field와 관련 endpoint는 MVP에 없다.
- Agent Manager는 외부 호출과 별도로 reservation부터 최대 40초인 고정 worker
  lease와 fencing token을 사용한다. timed window의 남은 시간이 더 짧으면 그 시각을
  쓴다. lease 만료 뒤 결과는 버리고 scheduler가 `PASS`, 자동 선택 또는 고정 GM
  문구를 확정한다. 이 lease는 조정 가능한 LLM timeout API나 metric이 아니다.
  Backend 배포의 `LLM_TIMEOUT_SECONDS`는 기본 30초이며, MCP·모델 최초/교정 호출은
  lease와 window 마감에서 완료·제출 여유 3초를 뺀 예산 안에서만 진행한다.

### 10.2 AI GM 직접 반환 결과

AI GM은 MCP `public`, `gm-guide` Resource를 읽기만 한다. LLM adapter는 다음
폐쇄형 결과를 MCP Tool이나 `/internal/v1/agent-proposals`를 거치지 않고 Backend
Agent Manager에 직접 반환한다.

```json
{
  "type": "GM_NARRATION",
  "narration_kind": "PUBLIC_EVENT",
  "source_event_id": "a7dd582b-bcad-4d91-b045-1c771128e380",
  "fixed_message_key": null,
  "message": "밤이 지나고 모두가 다시 모였습니다. 다행히 희생자는 없었습니다."
}
```

| field | 타입·제약 |
|---|---|
| `type` | 상수 `GM_NARRATION` |
| `narration_kind` | `PUBLIC_EVENT` 또는 `FIXED_MESSAGE` |
| `source_event_id` | UUID 또는 `null` |
| `fixed_message_key` | 8.2.5절 고정 key 또는 `null` |
| `message` | 공백 정규화된 한 문단의 plain text, 1~400자 |

`PUBLIC_EVENT`이면 `source_event_id`가 현재 `gm-guide.source_public_event.event_id`와
같고 `fixed_message_key=null`이다. `FIXED_MESSAGE`이면 `source_event_id=null`이고
`fixed_message_key`가 현재 guide와 같으며 `message`는 마스터플랜의 해당 고정 문구와
정확히 일치해야 한다.

Backend Agent Manager는 추가 field·자연어 wrapper, guide reference 불일치, 금지된
private 사실과 길이 위반을 거부한다. 교정은 한 번만 허용하며 그 뒤에는 Backend의
고정 한국어 문구를 사용한다. 검증된 결과라도 현재 job의 lease token·fencing token,
window와 `state_version`을 다시 확인한 뒤에만 `PUBLIC` event로 저장한다. 늦은 결과는
`STALE`로 끝내고 공개하지 않는다.

## 11. 보안·비간섭성 요구

- 다른 사용자 소유 game은 `404`로 통일해 존재 여부를 숨긴다.
- UUID가 일치해도 command마다 game owner, human player, alive, phase, role, target,
  deadline, window와 state version을 검증한다.
- Front snapshot, sync와 SSE는 모두 같은 audience projection 함수를 사용한다.
- 마피아가 둘이어도 상대 마피아 role과 action을 어떤 private payload에도 넣지 않는다.
- 게임 진행 중 AI GM에는 role, 공격자, 보호 대상, 조사 결과와 개별 투표를 전달하지
  않는다. 종료 뒤 공개된 role도 `gm-guide`에는 넣지 않고 `public.players`로만 제공한다.
- 관리자 allowlist는 일반 game 소유권을 우회하는 사용자 기능으로 사용하지 않는다.
- redirect URL, callback, OIDC metadata와 OAuth endpoint는 API 표면에서 제거한다.
- Backend 공개·내부 HTTP log에는 request ID, route, status, duration, game ID와
  분류 오류만 남기고 사용자 입력 본문과 private payload를 기본 기록하지
  않는다. MCP runtime log에는 9.4절의 더 엄격한 allowlist를 적용한다.
- Backend의 `event_outbox`는 MCP 감사 로그 저장소가 아니며 MCP runtime은 이를
  직접 소비하거나 갱신하지 않는다.

## 12. 계약 테스트

- `/openapi.json` snapshot에서 path, union discriminator, enum과 필수 header 확인
- UUID 누락·잘못된 version, 다른 소유자와 관리자 allowlist 거부
- create replay와 사용자별 직전 scenario 제외 동시성
- 모든 command의 phase·role·alive·target·deadline success/reject matrix
- 같은 idempotency key replay와 다른 body 재사용 충돌
- stale version과 같은 window 동시 제출
- sync no-change `200 operations=[]`, delta, snapshot fallback
- SSE reconnect, duplicate Front sequence와 polling 전환
- 진행·종료 시점별 role·밤 행동·개별 투표 비노출
- feedback union과 게임별 unique
- Engine canonical query/body HMAC, 60초 timestamp, 120초 nonce replay,
  stale capability와 agent 간 비간섭성
- bootstrap claim field 유지, consume 성공 응답의 5-field 폐쇄형 schema,
  scope 부분집합·canonical order와 issuance binding 교차 검증, status-only 응답 거부
- 5개 Resource의 공통 envelope·scope별 exact key·nullable·union 검증과 unknown field
  fail-closed 처리
- raw JSON-RPC·Engine consume/context 응답의 duplicate member 거부와 context 고정 오류
  분류·message·payload 비노출
- `resources/list`의 cursor 거부, binding 기반 descriptor·canonical order·Engine 0회,
  SDK capability 광고, 허용 read당 GET 1회, raw URI 변형·미허용 URI의 존재 은닉·Engine
  0회와 요청 종료 뒤 context 무저장
- 같은 public projection의 subject 비의존성, 다른 AI의 `me`·`persona` 비간섭성과
  `turn` target의 role 비노출
- GM session에 `me`, `turn`, `persona`, role-conditioned target과 행동 Tool이 없고
  `public`, `gm-guide` 허용 집합의 nonempty 부분집합만 있는지 확인
- GM 구조화 결과가 Agent Manager로 직접 반환되고 MCP Tool·proposal API 호출은 0회인지,
  잘못된 guide reference·private 사실·late fencing 결과가 fallback 또는 stale인지 확인
- job마다 capability hash·세션 개설 토큰의 nonce·MCP session ID가 다르고
  성공·fallback·stale·
  실패(호출 취소 포함)·lease 만료 뒤 이전 값과 소비된 세션 개설 토큰이 거부되는지 확인
- reconnect가 새 capability·세션 개설 토큰·session을 사용하고 이전 state/window 결과를
  자동 rebase하지 않는지 확인
- MCP session 고정, Resource allowlist와 Tool proposal 재검증
- 같은 `proposal_id`·같은 body의 불명확 응답 재시도는 mutation 한 번과 terminal
  결과 replay가 되고 다른 body 재사용은 충돌하는지 확인
- MCP 구조화 로그의 metadata allowlist와 payload·target·capability·token·signature·
  ID·header·prompt·raw response·exception 전문 비기록 검증
- LLM token·비용·timeout field와 API가 노출되지 않는지 확인

### FastMCP 모델 입력 축약 (2026-09-07)

현재 운영 `mafia://context/current/...`, `mafia://context/scoped/...` 등록부는 Backend 응답 후 모델 입력을 축약한다. Backend 내부 API와 인증 Resource의 8.2 schema는 그대로 유지한다. 운영 FastMCP 응답의 public.data.scenario는 scenario_id·title만 보존하고 public.data.rules는 고정 한국어 규칙 문자열 배열을 추가한다. me.data는 alibi·observation을 제외하며 그 밖의 필드는 보존한다. 공개 사건·발언·본인 private_events·turn·persona·gm-guide는 보존한다. rules는 마스터플랜 3절 규칙 설명이며 상태 판정이나 추가 비공개 정보가 아니다.

### 2026-09-08 Backend 모델 입력의 최근 대화 발췌 (WU-B6)

Backend는 토론 SPEECH의 모델 user 데이터에만 `dialogue_focus`를 추가한다.
이는 MCP 응답이나 공개 API 필드가 아니며 8.2절 Resource 스키마는 유지한다.
`recent_speeches`와 `addressed_speeches`는 현재 토론의 최근 공개 발언과 본인을
이름·좌석으로 언급한 타인 발언 후보를 각각 최대 6개 담는다. 항목은 기존 공개
event의 `event_id`, `event_type`, `created_at`, 허용된 `data`만 복사한다.
`own_last_speech`는 현재 토론의 마지막 본인 발언 또는 null이고,
`other_speech_count_since_own_last`는 그 뒤 타인 발언 수 또는 본인 발언이 없으면 null이다.
round 0의 GAME_BEGAN 또는 현재 round와 일치하는 NIGHT_RESOLVED를 토론 경계로
사용하며 경계가 없거나 다르면 발췌만 생략한다. 이전 이력은 원본 context에 남긴다.
동명이인은 이름 단독 언급을 제외하고 좌석 호칭으로 구분한다.
언급 후보는 질문·미답·회피 여부를 확정하지 않는다. 자유 문자열은 user
데이터로만 전달하며 파생 입력을 읽는 고정 안내만 Backend 출력 계약에 더한다.
역할별 전략·말투는 기존 MCP 지침을 그대로 사용하고 투표·밤·GM 요청에는 이
발췌를 추가하지 않는다. 공개 이력·본인 조사 기록을 자르거나 추가 조회하지 않는다.

## 2026-09-08 운영 MCP 역할별 프롬프트 계약 (WU-M6)

기존 운영 `mafia://context/scoped/...`의 `me.data`와 `persona.data`에 MCP가 생성한
`agent_instruction` 문자열을 추가한다. me는 본인 역할·phase에 맞는 승리/행동 지침,
persona는 토론 단계의 고정 말투 지침만 전달하며 토론 외에는 빈 문자열이다. 역할은
`MAFIA|DETECTIVE|DOCTOR|CITIZEN` 중 하나여야 한다. 사용자 발언·이름·backstory를 지침에
삽입하지 않는다. persona 지침은 배정된 원문·수치를 따르라는 공통 안내만 담는다.
성향의 구간별 정형 문구 변환과 deception 증폭은 하지 않으며, 검증된 0~1 수치는
기존 persona.data.parameters로 보존한다. 기존 public.data.rules의 게임 규칙과 공개 이력은 보존한다.
인증 Resource와 Backend 내부 API의 8.2 data schema는 변경하지 않는다.

Backend 운영 MCP client는 me 지침의 비어 있지 않음과 두 지침의 최대 2400자·문자열
형식을 검증한다. 지침이 없는 이전 MCP 응답은 추측한 역할 전략으로 대체하지 않고 기존
MCP 실패 fallback으로 처리한다. MCP를 먼저 재시작한 뒤 Backend를 갱신해야 한다.
검증한 지침은 developer 메시지에 한 번만 넣고 원본 user context에서는 해당 필드만
제외한다. system은 공통 규칙, 출력 schema·한 번 교정 지시는 Backend 소유다.
Local/Gemini는 developer 지침을 각 Provider의 system 입력에 합쳐 의미를 보존한다.

MCP `agent_instruction` Prompt는 Backend prompt endpoint를 호출하지 않는다. 선택 인자
`role`(기본 CITIZEN), `phase`(기본 DAY_DISCUSSION)로 같은 MCP 고정 템플릿을 조합한다.
기존 game_id/user_id 인자는 호환을 위해 받지만 게임 정보를 조회하지 않는다. 임의 역할을
선택해도 실제 플레이어의 비공개 정보는 반환되지 않는다. 실제 Agent 경로의 역할은 항상
Backend가 검증한 me Resource에서 선택한다. Backend의 기존 고정 prompt endpoint는
구형 클라이언트 호환용으로 남으며 역할별 전략을 소유하지 않는다.

## 2026-09-07 자유 토론 변경 (사용자 승인 WU-B4)

이번 단일 WU-B4는 1분 45초 자유 토론과 연결되는 Front·MCP 표현의 변경이다. 이 절이 기존 좌석당 한 번 발언·전원 PASS 추가 순환 규칙보다 우선한다. 새 일반·최종 토론은 Backend deadline 105초까지 열리며 인간은 AI 처리 순서와 무관하게 발언한다. 플레이어별 최근 60초 SPEAK는 최대 7회이며 서버 게임 행 잠금 안에서 원장으로 검증한다. PASS는 조기 마감하지 않는다. AI 작업은 기존 단일 예약 창을 재사용해 공정하게 배분하고, 발언마다 새 window를 열되 토론 deadline은 보존한다. turn_player_id는 AI 스케줄링 힌트이며 인간의 발언 권한 제한이 아니다. SPEECH에도 deadline·remaining_ms가 제공된다. 저장 시 잔여 시간을 보존한다. 마감 뒤 첫날은 밤, 이후 낮은 투표, 최종 토론은 최종 지목으로 진행한다. 과거 deadline 없는 발언 창은 기존 방식으로 처리한다. DB 구조와 idempotency·게임 상태 버전 검증은 보존한다.

## 2026-09-07 WU-B13 투표 보조 조회 계약

후속 사용자 요청에 따라 발언 분석은 투표 직전 토론 마감 경계에서 실행한다. 분석이
처리 중이면 기존 토론 phase와 마감된 SPEECH 창을 유지하며 새 발언·투표는 받지 않는다.
양 분석 단계가 완료되거나 재시도 상한이 소진되면 투표 창을 열고 그때부터 기존 투표
제한 시간을 계산한다. 준비 중 투표 보조 조회는 비투표 상태로 409이며 공개 응답 schema는
바꾸지 않는다. 분석 비활성·초기화/저장소 장애 시 기존 게임 진행을 유지한다.

`GET /api/v1/games/{game_id}/vote-insights?window_id=UUID&scope=current_discussion|game`
는 기존 `X-User-Id`·성공/오류 envelope를 사용한다. scope 기본값은
`current_discussion`이다. data는 다음 필드만 포함한다.

- `game_id`, `window_id`, `scope`, `cutoff_sequence`(원장 sequence 정수),
  `analysis_version`, `revision`(공개 결과 SHA-256), `generated_at`(UTC),
  `status`(`PENDING|PARTIAL|READY|UNAVAILABLE`)
- `coverage`: `total`, `embedding_ready`, `claims_ready`, `failed` 정수
- `similar_claims`: `{player_ids,target_player_id,claim,evidence:[Evidence]}` 배열
- `suspicion_ranking`: `{target_player_id,rank,accuser_count,speech_count,evidence:[Evidence]}` 배열
- `candidate_evidence`: `{target_player_id,suspicion:[Evidence],defense:[Evidence],questions:[Evidence]}` 배열
- `Evidence`: `{event_id,player_id,message,created_at,sequence}`. message는 공개 원문
  전문이며 모델의 proposition·quote·벡터·유사도·역할·내부 추론은 반환하지 않는다.

분석 입력의 B12 Provider 응답 수신부는 정수 offset이 정확한 quote와 불일치할 때만
원문 내 유일한 정확 인용의 Python 문자 반개구간으로 위치를 복구한다. 기존 span이
정확하면 반복 인용도 허용하지만, 복구 대상 인용의 반복·겹침 출현, 허구·비문자열·빈
quote, boolean 등 비정수 offset은 거부한다. 정규화 후 기존 `validate_claims`의
폐쇄형 schema·같은 게임 대상·입장·근거 검증을 그대로 적용하며 저장/공개 계약은
완화하지 않는다. 분석 버전은 파서 revision을 포함한 `claims-ko-v2`로 구분한다.

읽기 전용 REPEATABLE READ transaction 안에서 소유권, IN_PROGRESS, 생존 인간,
현재 OPEN 투표 phase/window, 서버 deadline을 검증한다. 타 소유/없는 게임은
`404 GAME_NOT_FOUND`, 비투표·저장·사망 인간·지난 window·마감은
`409 VOTE_INSIGHTS_STALE_WINDOW`, 저장소/잘못된 원장은
`503 VOTE_INSIGHTS_UNAVAILABLE` 고정 문구만 반환한다. disabled도 같은 검증 후
`UNAVAILABLE`과 빈 카드/0 coverage를 반환하며 분석 테이블은 읽지 않는다. 앱의 `speech_analysis_start_failed`도 요청별 disabled
설정으로 동일하게 처리하고 공유 설정은 바꾸지 않는다.
서버의 생존·자기 제외·확정 동률 재투표 후보 규칙과 동일한 현재 후보만 표시한다.

cutoff는 같은 window의 PUBLIC SET_ACTION_WINDOW **최초** 개설 sequence다.
저장/재개가 같은 window를 다시 게시해도 확대하지 않는다. current_discussion은
cutoff 직전 마지막 DAY_DISCUSSION/FINAL_DISCUSSION SPEECH window의 phase:round이며
현재 투표 round를 과거 발언 round에 덮어쓰지 않는다. game은 cutoff 이전 두 토론
phase의 공개 AI 발언 전체다. 사망 AI의 기간 내 과거 근거도 보존한다.
원본 PUBLIC PLAYER_SPOKE를 기준으로 분석을 LEFT JOIN하여 미발견 발언도 total에
포함한다. 게임·발언·발화자·sequence·segment·hash·모델·버전·차원이 불일치하면
미처리로 취급한다. max sequence로 완전성을 추정하지 않는다.

유사 주장 후보 검색은 저장된 전문 임베딩의 정확 cosine 비교를 사용한다. 한 묶음의 모든 쌍이 threshold를 만족하는 complete-link를
사용하여 중간 발언만 통해 다른 주장이 합쳐지는 것을 방지한다. 초기
상수 threshold는 0.88이며 실제 한국어 품질은 B14에서 아직 측정되지 않았다.
같은 대상·입장이고 원문과 proposition에서 모두 확인되는 동일 논점(알리바이,
역할 주장, 진술 변화)에 한해 표현이 다른 paraphrase도 묶는다. 이름·입장·논점·숫자·역할/시간/장소 표지
근거가 모호하거나 다중 대상·인용·부정·철회인 문장은 보류한다. 알리바이 설명이
수상하다는 주장과 앞뒤가 맞지 않는다는 주장은 후보가 될 수 있지만 역할 주장과는
묶지 않는다. 검색된 유사도는 진실 확률이 아니며 사용자에게 수치를 노출하지 않는다.
모델 proposition이나 생성 요약을 원문처럼 공개하지 않고 논점별 고정 설명과 실제
공개 원문 근거를 반환한다. 동일 AI끼리의 쌍은 제외한다. 지원 논점 밖의 발언은
순위·근거에는 포함될 수 있지만 유사 묶음은 보류한다. 이 명시적 보류는 미검증
threshold의 품질 보장이 아니며 기능 기본 비활성 상태에서 B14 평가가 필요하다.

대상은 공개 이름 및 `좌석번호번`/`좌석번호번 플레이어`를 UUID로 해소하며
알 수 없는 좌석·다중 대상은 보류한다. `마피아가 아니야` 같은 명시적 역할 부정은
DEFENSE 근거로 보존하되 SUSPICION으로 세지 않고 전언·인용은 계속 보류한다.
지목 순위도 명시적 원문 대상·입장을 검증한 SUSPICION만 집계하며 고유 AI 수가
기준이다. 동일 event/target은 한 번만 세고 질문·옹호·인용을 제외한다. 동수는 공동
competition rank(1,1,3), 동수 표시 순서는 좌석순이다. 기간중 지목 이력이며 현재
투표 의향·마피아 확률이 아니다. 후보 최대 8명, 유사 카드 최대 8개, 각 카드/각
후보의 입장별 근거 최대 5개를 sequence 오름차순으로 반환한다. 유사 카드 근거는
화자별 첫 원문을 우선하여 동일 AI의 반복이 다른 화자의 근거를 가리지 않게 한다. 집계 수와 coverage는
표시 잘림 이전 전체값이다. READY는 모든 발언의 두 분석 단계가 준비되었다는 뜻이며
품질 인증이나 카드 존재 보장이 아니다. 일부 준비는 PARTIAL, 준비 없음은 PENDING,
전부 실패면 UNAVAILABLE이다. 빈 기간은 READY와 빈 카드다.

GET은 외부 모델·색인·DB 쓰기·게임 version/event cursor 갱신을 수행하지 않는다.
revision은 generated_at을 제외한 공개 응답에서 계산하므로 private 변경이나 같은
결과의 반복 조회로 변하지 않는다. 앱별 `app.state.vote_insight_service`를 주입할 수
있으며 기본 router는 `app.state.settings`로 service/repository를 지연 생성한다.


### 2026-09-08 실시간 공개 대화 요약 확장

기존 vote-insights endpoint·인수·오류 envelope를 유지한다. 이번 절은 앞선 AI 전용
및 투표 phase 전용 조회 제한보다 우선한다. HUMAN·AI의 PUBLIC PLAYER_SPOKE를 집계하며
공개 전 원문·다른 게임·private는 계속 제외한다.

DAY_DISCUSSION·FINAL_DISCUSSION의 현재 OPEN SPEECH window도 조회할 수 있다.
토론 deadline이 지났어도 투표 준비 중인 같은 OPEN SPEECH는 허용한다. 저장·종료·
다른 window와 불일치 phase/round는 기존 stale 오류다. 토론에서는 생존 투표권 검사를
요구하지 않고 소유권과 공개 roster 소속을 검사하며 후보·순위·유사주장 배열은 비운다.
투표·재투표·최종 지목의 생존·마감·후보 검증은 유지한다.

토론 cutoff_sequence는 동일 repeatable-read snapshot의 최대 공개 원장 sequence+1이다.
private 이벤트만 추가되어서는 공개 cutoff나 revision이 달라지지 않는다.
current_discussion 구간은 현재 SPEECH 창의 phase:round이며, game은 cutoff 이전의
게임 전체 공개 발언이다. 투표 cutoff와 구간 산출은 종전 최초 개설 원장을 유지한다.

응답에 conversation_summary object를 항상 추가한다:
`{items: [{summary: string, evidence: [PublicSpeechEvidence]}], total: integer, omitted: integer}`.
원문·분석 바인딩과 claims 검증을 통과한 발언에서 공백만 아닌 서로 다른 proposition
최대 3개를 ` · `로 연결한다. 주장이 없는 완료 발언은 요약 항목을 만들지 않는다.
items는 최신 최대 20발언을 sequence 오름차순으로 반환하고 evidence는 해당 공개
발언 하나의 기존 5필드(event_id/player_id/message/created_at/sequence)다.
total은 요약 가능한 전체 발언 수, omitted는 total-items 길이다. 임베딩이 아직 없어도
완료된 주장 요약은 PARTIAL로 노출할 수 있다. coverage는 범위 내 HUMAN·AI 전체 기준이고
revision에 요약을 포함한다. GET은 모델 호출·DB 쓰기·게임 변경을 하지 않는다.

## 2026-09-08 CUSTOM_ROLE 공개 API 계약 (CP-0)

### 생성과 catalog

`POST /api/v1/games` body는 다음 additive 필드를 허용한다. `mode` 생략은
`STANDARD`이며 이때 `custom_role`은 없어야 하고 기존 요청·응답 의미가 변하지 않는다.

```json
{
  "player_count": 6,
  "ruleset_version": "mystery-v1",
  "scenario_version": "scenario-v1",
  "mode": "CUSTOM_ROLE",
  "custom_role": {
    "name": "기록 감식관",
    "faction": "CITIZEN",
    "catalog_version": "custom-role-v1",
    "ability_ids": ["night.investigate.v1", "night.protect.v1"]
  }
}
```

`CUSTOM_ROLE`에서는 `custom_role`이 필수다. `name`은 Unicode NFC 적용, 앞뒤 공백
제거와 연속 Unicode 공백의 한 칸 축약 뒤 1~40자다. 이는 plain untrusted text이며
prompt나 명령으로 해석하지 않는다. `ability_ids`는 중복 없는 1~3개 배열이다.
`CITIZEN`은 공격 외 네 ID 중 1~3개를 허용하며 낮/조회 능력만 선택해도 된다. `MAFIA`는
`night.attack.v1`을 반드시 포함하며 나머지 네 ID 중에서 추가하여 총 1~3개를 선택한다. 알 수 없는 mode,
catalog version, ability ID, 중복, 팀 제약 위반은 `422 VALIDATION_ERROR`로 fail-closed한다.

`GET /api/v1/game-config/custom-role-abilities`는 인증된 사용자에게 다음 서버 catalog를
반환하며 DB나 MCP를 호출하지 않는 versioned 공개 설정이다.

```json
{
  "catalog_version": "custom-role-v1",
  "abilities": [
    {"id": "night.attack.v1", "label": "공격", "factions": ["MAFIA"]},
    {"id": "night.investigate.v1", "label": "조사", "factions": ["CITIZEN", "MAFIA"]},
    {"id": "night.protect.v1", "label": "보호", "factions": ["CITIZEN", "MAFIA"]},
    {"id": "vote.triple.v1", "label": "투표 조작", "factions": ["CITIZEN", "MAFIA"]},
    {"id": "intel.special_roles.v1", "label": "특수 직업 열람", "factions": ["CITIZEN", "MAFIA"]}
  ]
}
```

descriptor의 내부 실행 참조는 MCP 설계 정본에만 두며 공개 catalog와 생성 body에는 raw
MCP Tool명, action subtype, prompt를 포함하지 않는다.

### Snapshot과 밤 행동

게임 snapshot의 `game.mode`는 항상 `STANDARD` 또는 `CUSTOM_ROLE`이다. CUSTOM_ROLE
본인 projection에는 `me.role_name`, `me.faction`, `me.ability_ids`,
`me.ability_options`를 반환한다. `ability_options`의 각 항목은
`{ability_id, label, valid_targets}`이며 현재 밤에 선택 가능한 본인 능력만 포함한다.
이 네 필드는 소유자 본인에게만 반환하고 다른 audience의 Resource·sync·관리자 공개
projection으로 전달하지 않는다.

공개 player에는 nullable additive `revealed_role_name`을 둔다. 해당 player가 처형됐거나
게임이 종료된 뒤에만 정규화된 자유 직업명을 제공하며 밤 사망을 포함한 그 이전에는
`null`이다. 기존 `revealed_role` 의미는 보존한다.

CUSTOM_ROLE의 `SUBMIT_NIGHT_ACTION` body에는 catalog의 `ability_id`가 필수이며
`target_player_id`와 함께 보낸다. 현재 본인의 저장 ability, faction, phase, 생존,
target 규칙을 다시 검증하고 한 밤의 첫 유효 능력 하나만 받는다. STANDARD 요청에서는
`ability_id`를 받지 않으며 Backend가 기존 role에서 action을 결정한다. 복수 actor의
INVESTIGATE·PROTECT는 각각 유효하고 밤 해소는 모든 보호 대상 집합을 적용한다.

### 2026-09-08 WU-M10 추가 능력 계약

초기 세 능력 한정 규칙을 확장한 위 catalog에 `vote.triple.v1`(투표 조작),
`intel.special_roles.v1`(특수 직업 열람)을 추가한다. 두 항목의 factions는
`[CITIZEN, MAFIA]`이며 기존 catalog version·생성 형식·1~3개 제한은 유지한다.
`ability_options`는 계속 현재 밤 능력만 반환한다. 낮/조회 능력은 밤에 선택하거나
자동 사용하지 않으며 밤 능력 없는 커스텀 직업은 밤 제출 대상에서 제외한다.

`SUBMIT_VOTE`는 선택적 `ability_id=vote.triple.v1`을 허용한다. 생존 HUMAN의
CUSTOM_ROLE 저장 능력을 검증하고 DAY_VOTE·REVOTE의 해당 표에만 가중치 3을 부여한다.
다른 phase·AI·STANDARD·미보유·밤 ID는 거부한다. 생략·자동 제출은 1표이며 최종 지목은
이 능력을 받지 않는다. 기존 window·deadline·대상·멱등성·중복 제출 검증은 동일하다.
공개 결과 counts는 가중 합계이고 개별 표·능력 사용 여부는 종료 전 공개하지 않는다.
종료 결과의 `ballots`는 능력을 사용한 표에만 additive `ability_id=vote.triple.v1`을
포함한다. 구형·일반 표의 필드 생략은 1표다. 숫자 `weight` 입력·저장은 허용하지 않고
actor의 저장 능력과 당시 phase로 가중치를 재계산한다. AUTO ballot의 능력 ID는 거부한다.

MCP `manipulate_vote(user_id, game_id, expected_state_version, window_id,
idempotency_key, target_player_id)`는 `/internal/mcp/actions`에
`action=VOTE, ability_id=vote.triple.v1`을 고정 전달한다. Tool은 player_id·weight를 받지
않으며 Backend가 게임 소유자의 HUMAN을 결정한다. 기존 submit_action은 기존 서명을 유지한다.

MCP `inspect_special_roles(user_id, game_id)`는
`GET /internal/mcp/special-roles?user_id=...&game_id=...`로 위임한다. Backend는 소유권,
CUSTOM_ROLE, HUMAN, 생존, `IN_PROGRESS`, 능력 보유 및 `day_number >= 2`를 검증한다.
소유권 불일치는 404 GAME_NOT_FOUND, 능력/actor 불일치는 403 ABILITY_NOT_ALLOWED,
상태·첫 밤 미해금은 409 ABILITY_NOT_AVAILABLE이다. 성공 응답은 폐쇄형 object
`{game_id, player_id, ability_id, state_version, roles}`이고 roles는 좌석순
`[{player_id, display_name, role, alive}]`이다. 다른 플레이어의 DETECTIVE·DOCTOR만
포함하고 MAFIA·CITIZEN·본인은 제외하며 사망자도 포함한다. 원본 상태·faction·알리바이·
밤 행동·투표는 포함하지 않는다. 응답은 Cache-Control: no-store이며 이벤트·공개 Resource·
AI context에는 추가하지 않는다. 이 조회는 읽기 전용이고 밤 행동 횟수를 소모하지 않는다.


### 2026-09-08 CP-0.1 공개 특수 직업 조회 adapter (WU-B17)

사용자 Front는 raw MCP Tool을 직접 호출하지 않고 인증된 사용자 흐름에서
`GET /api/v1/games/{game_id}/special-roles`를 `X-User-Id`로 호출한다. 기존 1.2~1.3절의
UUID 식별·접근 통제 경계를 유지하며 헤더 자체를 새로운 인증 증명으로 해석하지 않는다.
URL·body의 user_id 또는 임의 player_id 입력은 받지 않는다. Backend 공개 adapter는
기존 `read_special_roles`를 재사용해 같은 읽기 snapshot에서 소유권·CUSTOM_ROLE·HUMAN·
생존·IN_PROGRESS·`intel.special_roles.v1` 보유·`day_number >= 2`를 검증한다.

HTTP 200은 1.4절 API success envelope의 `data`에
`{game_id, player_id, ability_id, state_version, roles}`를 담고 `meta`는 공통 계약을 따른다.
`ability_id`는 `intel.special_roles.v1`이며 roles의 폐쇄형 schema·좌석순·대상 포함/제외
규칙은 위 WU-M10 계약과 동일하다. 성공·오류 응답에 `Cache-Control: no-store`를 적용한다.
소유권 불일치/미존재는 `404 GAME_NOT_FOUND`, mode·actor·능력 불일치는
`403 ABILITY_NOT_ALLOWED`, 사망·진행 중 아님·첫 밤 미해금은
`409 ABILITY_NOT_AVAILABLE`을 공통 오류 envelope로 유지한다.
`/internal/mcp/special-roles`는 MCP Tool 전용이며 공개 adapter가 MCP runtime을 경유하지 않는다.

Front는 위 catalog의 정확한 다섯 descriptor(ID·label·factions)를 검증한다. 누락·미지 ID·
중복 ID·미지 필드·잘못된 타입·진영 배열 불일치 또는 중복 진영은 fail-closed로 거부하고,
두 신규 ID는 정상 수용한다. 진영 배열은 위 명시된 배열과 일치해야 한다.
종료 결과에서는 본인의 custom `role_name`·`faction`을 표준 역할 표시보다 우선하며,
직업명과 표시 이름을 평문 escape한다. private 조회 결과는 공개 결과에 합치지 않는다.
