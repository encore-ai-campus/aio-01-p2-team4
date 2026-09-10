# AI 마피아 게임 실행 로그 보고서

## 1. 수집 범위

- 수집일: 2026-09-08
- 원본 로그: `backend_runtime.error.log`, `backend_runtime.log`, `mcp_runtime.error.log`, `mcp_runtime.log`
- 이벤트 시간 범위: `2026-09-08T01:11:57Z` ~ `2026-09-08T01:52:26Z` (한국시간 10:11:57 ~ 10:52:26)
- Backend 실행 `run_id`: `a18de729-81d8-4f38-b334-387c53d69f81`
- 수집 이벤트 수: 2,800건
- 확인된 게임 ID 수: 22개

이 문서는 실행 중 생성된 로그 파일의 특정 시점 스냅샷이다. 로그 파일은 여러 실행 시도에서 재사용될 수 있으므로, 아래의 미완료 표시는 데이터베이스의 최종 게임 상태가 아니라 이 로그 수집본에서 `COMPLETED` 이벤트를 확인하지 못했다는 뜻이다.

## 2. 전체 진행 요약

| 진행 단계 | 건수 |
| --- | ---: |
| `STARTED` | 895 |
| `SKIPPED` | 654 |
| `COMMAND_APPLIED` | 237 |
| `APPLIED` | 236 |
| `CONTEXT_READY` | 224 |
| `DECIDING` | 224 |
| `DECIDED` | 223 |
| `FALLBACK` | 62 |
| `PHASE_CHANGED` | 20 |
| `CREATED` | 7 |
| `COMPLETED` | 5 |
| `FAILED` | 4 |
| `WORKER_FAILED` | 4 |
| `BEGIN_GAME` | 3 |
| `RESUME` | 1 |
| `SAVE_AND_EXIT` | 1 |
| 합계 | **2,800** |

단일 `run_id`가 전체 이벤트에 사용되므로, Backend 재시작 없이 하나의 프로세스 실행 중에 여러 게임의 worker가 처리된 기록으로 보인다. `STARTED → CONTEXT_READY → DECIDING → DECIDED → COMMAND_APPLIED → APPLIED` 흐름이 확인된 게임은 모델 판단과 게임 반영까지 진행된 것이다.

## 3. 게임별 로그 집계

| 게임 ID | 이벤트 | sequence 범위 | 완료 | fallback | 실패 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `07e173dd-1f04-44c6-859c-5e61a281bd79` | 206 | 735–979 | 0 | 2 | 1 |
| `106acc96-0a75-4c0d-81ac-a732beecb399` | 141 | 154–452 | 0 | 10 | 3 |
| `135aa283-3e9c-4c7e-be45-21cfebe82583` | 154 | 2441–2726 | 1 | 0 | 0 |
| `207bd217-1405-4a88-83e8-92e60bb45ed2` | 2 | 963–964 | 0 | 0 | 0 |
| `256610e9-f0a6-47df-956e-a6133295f460` | 229 | 1095–1688 | 0 | 0 | 0 |
| `2a3b2097-80c9-444a-8635-6b6e9874a950` | 1 | 839–839 | 0 | 0 | 0 |
| `3e3f14cf-13f3-42ae-9b95-0ae7e1c9b746` | 184 | 3–286 | 0 | 36 | 0 |
| `47abb28c-e831-449f-88ed-627908a877f7` | 62 | 2593–2800 | 0 | 0 | 0 |
| `47cacb5b-4025-4bbd-aacc-801bd0b6bb4b` | 338 | 876–1649 | 1 | 2 | 0 |
| `5377f7a0-04ad-4e1b-ac74-39adbc5527b6` | 48 | 2708–2794 | 0 | 0 | 0 |
| `5b8fd63e-c9f3-4e25-a4a4-adba1c6fe757` | 127 | 1280–1630 | 0 | 0 | 0 |
| `60a6fbe9-7e82-4dc6-8fb7-a74337ab392b` | 246 | 1749–2447 | 0 | 0 | 0 |
| `784516ba-c90b-498a-8434-82d6680539b2` | 121 | 421–707 | 0 | 1 | 0 |
| `7c763d08-ca9f-48d2-9ba7-966ad2e5ce64` | 1 | 385–385 | 0 | 0 | 0 |
| `8182c65d-8b27-404e-9472-8734c73e29e0` | 38 | 1–64 | 0 | 4 | 0 |
| `86a1b49a-2167-4c72-9ae7-998a2ab1af38` | 235 | 1540–2157 | 1 | 1 | 0 |
| `98e4e088-5e39-4ce9-b94b-9740ef8dc2e1` | 1 | 832–832 | 0 | 0 | 0 |
| `afeefc13-0877-4224-b8ef-0bf21dafa8b2` | 272 | 1951–2585 | 0 | 0 | 0 |
| `c8981cac-32ce-4a03-8ada-b88e1617afb1` | 1 | 852–852 | 0 | 0 | 0 |
| `e548f6d5-36b9-4046-8619-7a44baa3ce3d` | 112 | 295–578 | 1 | 5 | 0 |
| `e5bb6996-0543-415b-b2e6-a5648e06cdd0` | 133 | 1842–2259 | 0 | 1 | 0 |
| `fa8429ff-44d1-45f6-a00b-a458e9936bdb` | 144 | 400–746 | 1 | 0 | 0 |

## 4. 오류 내용과 해석

### `MCP_UNAVAILABLE` 64건

AI가 MCP를 통해 게임 context를 읽거나 action을 제출하지 못한 경우다. 이때 현재 구현은 AI 발언을 실패시키는 대신 규칙 fallback으로 `PASS`를 만들고 게임에 반영한다. 따라서 로그에는 보통 다음 순서가 함께 나타난다.

```text
FALLBACK + action=PASS + reason_code=MCP_UNAVAILABLE
APPLIED  + action=PASS + reason_code=MCP_UNAVAILABLE
```

원본 Backend 로그에는 이후 MCP 요청의 `200 OK`와 `202 Accepted`도 확인되므로, 수집 기간 전체가 계속 단절된 것은 아니다. 특정 시점의 MCP session·context·action 호출 실패가 반복된 것으로 해석하는 것이 안전하다.

### `MCP_SUBMISSION_FAILED` 2건

MCP까지 요청은 진행했지만 action 제출 결과를 정상적으로 확정하지 못한 경우다. 한 게임에서 `FALLBACK` 뒤 `FAILED`가 이어졌고, 같은 시점에 별도의 `WORKER_FAILED`가 기록됐다. 이 경우 fallback 생성과 Backend 반영 사이의 제출 경계를 추가로 확인해야 한다.

### `PROVIDER_TIMEOUT` 2건

OpenAI 등 LLM provider 응답이 제한 시간 안에 도착하지 않은 경우다. 현재 정책은 발언을 `PASS` fallback으로 처리한 뒤 다음 진행을 시도한다. 따라서 모델 timeout이 게임 전체 종료를 의미하지는 않는다.

### `WORKER_FAILED` 4건

`game_id`, `player_id`, `phase`가 없는 공통 worker 오류 이벤트다. 현재 코드의 `_log_worker_error()`는 보안상 원본 예외·traceback·동적 class명을 버리고 고정된 `WORKER_FAILED`만 기록한다. 따라서 이 이벤트만으로 DB 조회 실패인지, MCP 처리 실패인지, async lifecycle 문제인지 확정할 수 없다.

### `RuntimeError: Event loop is closed` 49건

서비스 로그에서 비동기 event loop가 닫힌 뒤 다시 사용되었다는 오류가 반복 확인됐다. 이는 worker가 Agent/MCP 비동기 호출을 끝낸 뒤 닫힌 loop 또는 loop에 연결된 client를 재사용하는 상황과 관련 있을 가능성이 있다. 다만 현재 로그에는 traceback이 보존되지 않으므로 이 보고서에서는 가능성으로만 기록한다. 정확한 원인 확정에는 해당 오류가 발생한 호출 단계와 client 생성·종료 주기를 함께 로깅해야 한다.

## 5. 서비스 연결 확인

- Backend health: `GET http://127.0.0.1:18000/health` → `200 OK`, `{"status":"ok"}`
- Frontend: `GET http://127.0.0.1:18501` → `200 OK`
- MCP: `GET http://127.0.0.1:18100/mcp` → `406`
  - MCP Streamable HTTP endpoint는 일반 GET 화면이 아니라 POST session을 요구하므로, 이 GET 결과만으로 MCP 장애라고 판단하지 않는다.
- Backend 로그에서 MCP로 보낸 HTTP 요청: `200 OK` 2,533건, `202 Accepted` 234건

## 6. 결론

게임 진행 자체는 여러 게임에서 `DECIDED`와 `APPLIED`까지 진행됐고, 이 수집본에서 `COMPLETED`는 5건 확인됐다. 그러나 `MCP_UNAVAILABLE` 64건과 `RuntimeError: Event loop is closed` 49건이 있어 AI 판단·MCP action 경로가 안정적이라고 보기는 어렵다. 특히 `WORKER_FAILED`의 상세 원인이 현재 로그에서 제거되므로, 오류를 해결하려면 먼저 worker 오류의 내부 단계와 안전한 오류 분류 코드를 남기는 관측성 개선이 필요하다.

