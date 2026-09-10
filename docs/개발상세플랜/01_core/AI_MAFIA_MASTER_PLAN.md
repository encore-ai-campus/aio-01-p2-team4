# AI 마피아 MVP 공통 마스터플랜

## 2026-09-09 밤 행동 제한시간 연장 (WU-B5)

사용자가 요청한 이번 단일 WU-B5는 Backend가 새 `NIGHT_ACTION` window를 열 때 적용하는
제한시간을 20초에서 30초로 늘린다. 투표 계열의 30초와 낮·최종 토론의 105초는
변경하지 않는다. 이미 열린 window는 PostgreSQL에 저장된 `deadline_at`을 원본으로
계속 사용하며, 변경 뒤 새로 열리는 밤부터 30초를 적용한다. 저장·재개는 저장 시점의
잔여 시간을 보존하고 임의로 30초로 초기화하지 않는다. DB schema와 공개 API field,
파일 구조는 변경하지 않는다.

## 2026-09-09 Backend CORS origin 개방 (WU-B7)

사용자가 요청한 이번 단일 WU-B7은 Backend의 CORS origin allowlist를 제거하고 모든
브라우저 origin에 공개·관리자 API와 SSE의 cross-origin 요청을 허용한다. 응답은
`Access-Control-Allow-Origin: *`를 사용하고 credentials는 계속 허용하지 않는다.
허용 method와 request header 목록, 사용자 UUID·게임 소유권 검사, 관리자
`ADMIN_USER_IDS` allowlist는 유지한다.

Backend 설정과 macOS/Linux·Windows 실행 스크립트에서 `CORS_ALLOWED_ORIGINS`를
제거하고 Front는 origin 사전 등록 없이 Backend 주소를 사용할 수 있게 한다. 이 변경은
CORS가 제공하던 브라우저 읽기 제한만 해제하며 Backend bind 주소나 네트워크 방화벽을
바꾸지 않는다. UUID가 인증 증명이 아닌 기존 보안 경계에 따라 서비스는 계속 개인
개발 환경 또는 접근이 통제된 사설망에서 사용한다. DB·MCP 계약과 파일 구조는 변경하지
않는다.

## 2026-09-09 Agent 시험 보고서 반복 검증 (WU-B6)

사용자가 요청한 이번 단일 WU-B6는 `docs/arrangement/07_AGENT_TEST_RESULT_REPORT.md`의
AGT-001~012를 현재 실행 코드에 대해 각각 최소 50회 검증하고 결과를 기록하는 작업이다.
Orca coordinator는 결과 집계·정본·루트 README·시험 보고서를 갱신하고, 두 작업자는
동일 checkout에서 아래 테스트 파일만 나누어 소유한다. Backend·MCP 런타임, DB schema,
공개 계약과 게임 규칙은 변경하지 않는다. 기존 테스트 소스가 정리된 상태이므로 기존
pytest를 재사용해 `backend/tests/`에 보고서 전용 테스트 두 파일만 복원하고 `.gitignore`에
이 두 파일의 추적 예외를 추가한다.

- `backend/tests/test_agent_report_behavior.py`: AGT-001~008의 허용 행동·대상·필수 입력·Context 범위.
- `backend/tests/test_agent_report_recovery.py`: AGT-009~012의 stale·duplicate·MCP 실패·응답 유실 방어와 관련 activity/rollback 증거.

각 반복은 새 합성 상태와 fake Provider·MCP·저장소를 사용한다. 판정 로직은 실제
Backend·Game Engine을 호출하고 실패를 성공으로 바꾸는 mock은 두지 않는다. DB 연동을
추가로 실행해야 하는 경우 팀 테스트 DB의 해당 시험 소유 자료로만 한정하며 로컬 DB를
만들지 않는다. 이번 합성 반복 결과는 실제 LLM 행동 오류율 또는 실제 DB turn 집계와
구분한다. 발견한 기존 실패는 증거와 영향을 보고서에 기록하고 별도 구현으로 확대하지 않는다.

검증 결과는 127개 변형 × 50회 = 6,350회 중 6,296회 통과·54회 실패·오류/건너뜀
0회다. 9인 전원 생존 의사의 대상 9개와 API·MCP client의 최대 8개 제한이 충돌하며,
이 조건의 고정 재현 50회와 다른 변형 4회가 실패했다. 제품 규칙·API·런타임은
변경하지 않고 후속 계약 조정 대상으로 남긴다. 합성 상태·저장소를 사용한 범위와
시나리오별 결과는 [시험 보고서](../../arrangement/07_AGENT_TEST_RESULT_REPORT.md)를 따른다.

> **MVP 단순화 프로파일(2026-09-05):** DB·스키마·migration 이력은 보존한다.
> OAuth/OIDC·Front HMAC, custom MCP bootstrap/capability/nonce/session registry,
> Agent lease/fencing/job 상태 머신, LLM 비용·usage·자동 failover, Redis outbox
> publisher와 복잡한 reconnect/backoff는 신규 실행 경로의 요구사항에서 제외한다.
> 관련 migration 구조는 legacy 호환용으로만 남긴다.

**문서 상태:** 구현 목표 계약

**규칙 세트:** `mystery-v1`

**시나리오 팩:** `scenario-v1`

**최종 갱신:** 2026-09-03

이 문서는 AI 마피아 MVP의 제품 규칙, 시나리오, 아키텍처, 보안 경계, 섹터
소유권과 작업 순서를 정의하는 공통 정본이다. 세부 계약은 다음 문서만 사용한다.

| 구분 | 정본 |
|---|---|
| 제품 범위·규칙·시나리오·작업 계획 | 이 문서 |
| PostgreSQL·Redis·transaction·migration | [AI_MAFIA_DB_DESIGN.md](../02_backend_data/AI_MAFIA_DB_DESIGN.md) |
| Front·Backend·MCP HTTP 계약 | [AI_MAFIA_API_SPEC.md](AI_MAFIA_API_SPEC.md) |
| 사용자·관리자 화면과 상태 전이 | [AI_MAFIA_SCREEN_FLOW.md](../04_frontend/AI_MAFIA_SCREEN_FLOW.md) |
| 섹터 간 최소 연결 형식·독립 개발 규칙 | [AI_MAFIA_INDEPENDENT_CONTRACT.md](AI_MAFIA_INDEPENDENT_CONTRACT.md) |

MCP runtime의 구현 구조와 MCP·Data WU 실행 순서는
[AI_MAFIA_MCP_SERVER_DESIGN.md](../03_mcp_agent/AI_MAFIA_MCP_SERVER_DESIGN.md)가 구체화한다. 이
설계서는 구현 가이드이며 MCP Resource `data` field·enum·nullable 계약은 이 설계서가
아니라 API 명세 8.2절과 그 절이 명시적으로 참조하는 API 공통 모델만 정본으로
사용한다.

이 문서들은 아직 구현되지 않은 목표 상태를 포함한다. 현재 코드의 완료 범위는 루트
[README.md](../../../README.md)를 기준으로 판정하며, 계획에 적혔다는 이유로 구현 완료로
간주하지 않는다. 계약을 변경할 때는 영향받는 정본 문서를 같은 변경에서 갱신한다.

### 현재 MVP FastMCP 프로파일

현재 전환 작업의 기준은 참고 프로젝트 수준의 얇은 FastMCP adapter다. MCP는 Agent가
사용하는 Resource·Prompt·Tool 컨텍스트를 제공하고, Tool 호출은 Backend로 전달한다.
행동 판정·게임 상태 변경·인증·권한·DB·Redis·LLM은 Backend가 소유한다. MCP 내부의
HMAC·bootstrap token·capability state machine·session registry·idle timeout·DELETE
cleanup은 현재 FastMCP 전환 범위에서 제외하며, 기존 상세 M2~M8 운영 프로파일은
후속 별도 WU로 취급한다. 현재 디렉터리 구조는 `mcp_server/mafia_game` 아래에서
유지한다.

## 2026-09-07 공개 기록 UI 개선 범위

사용자가 승인한 이번 단일 작업 단위는 WU-F6 공개 기록·결과 표현 개선이다.
기존 게임·관전 공통 타임라인을 채팅으로 표현하고 AI 처리 영역을 접을 수 있게 하며,
종료 결과의 마피아 선택 분산에 따른 RNG 사유를 표시한다. 기존 Front 파일만 사용하며
Backend 규칙·API·비공개 정보 공개 시점은 유지한다.

## 2026-09-08 관리자 AI 발언 분석 범위 (WU-F10)

사용자가 요청한 이번 단일 작업 단위는 기존 `speech_analysis`의 공개 AI 발언 임베딩과
claims를 관리자 read-only 화면에서 집계·도식화하는 것이다. Backend는 공개
`game_events`·AI `game_players`·`agent_personas`만 조인해 기간·게임·페르소나·round·분석
버전으로 제한된 분석 API를 제공하고, Front는 주제 유사도 히트맵·키워드 빈도·stance
비율·원문 근거를 표시한다. 최대 500건의 결정적 표본과 cosine 기반 greedy 묶음을
사용하며 전송량을 줄이기 위해 저장 벡터의 앞 96차원 투영만 집계에 사용한다. 새 LLM
호출·DB 파생 저장·역할/진영 공개는 하지 않는다. 기존 관리자 API의
allowlist·감사·read-only 경계를 유지하고 이번 WU의 파일 범위 밖 리팩터링은 포함하지
않는다.

## 1. 확정 결정

### 2026-09-08 자연스러운 대화·전략적 블러핑 재설계 (WU-M6)

이번 사용자 요청은 기존 `api/prompts/instructions.py`의 역할·단계별 행동과 표현을
재설계하는 단일 WU-M6다. 이 절은 아래 공격적 토론 보완의 일률적인 압박 지침보다
우선한다. 게임 내 블러핑은 유지하되 매 발언의 도발·날조를 강제하지 않는다. 실제
대화에 대한 답변·양보·반박, 조건부 협력, 설득할 상대와 발언 시점의 선택을 안내한다.
마피아는 사실과 필요한 왜곡을 섞어 신뢰·표를 확보하고, 시민 진영은 블러핑의 이득과
아군 오처형 위험을 비교한다. 역할별 조사·보호·공격·투표 전략도 같은 목표를 따른다.

첫날 인간·AI PASS 금지, 200자 발언, 실제 기록과 허위 대사의 구분, 동료 마피아
신원 비공개, 본인 정보 scope와 허용 대상은 유지한다. 모델 입력에서 빠진 알리바이·
관찰을 첫 발언의 필수 근거로 요구하지 않는다. 페르소나 원문·수치를 재매핑하거나
지시문에 보간하지 않으며 Backend system·출력 schema·Provider와 DB·API는 바꾸지 않는다.
기존 MCP 등록 테스트로 역할·단계·문구·원문 비간섭성과 2400자 한도를 검증하고,
Backend·MCP의 비DB 회귀를 실행한다. 새 파일·유료 모델 호출·팀 DB 변경·프로세스
재시작은 포함하지 않는다. 실제 자연스러움·승률 개선은 별도 실게임 평가가 필요하다.
소개는 루트 README, 상세 변경·검증은
`docs/개발상세플랜/90_history/2026-09-08-persona-and-prompts.md`에 둔다.

### 2026-09-08 역할별 공격적 토론·블러핑 보완 (WU-M6)

사용자의 후속 요청에 따라 기존 `api/prompts/instructions.py`에서 네 역할의 말투를
더 공격적으로 바꾸고 게임 내 거짓말·선동·날조를 전략 선택지에 포함한다. 시민 진영은
반응 유도·역할 은폐·아군 보호를 위한 제한적 블러핑, 마피아는 허위 알리바이·가짜
조사 주장·누명·표 몰이를 활용한다. 공개 대사로 한 거짓 주장과 실제 서버 기록을
구분하며 본인 실제 역할·허용 행동·대상·비공개 정보 범위·승패 규칙은 유지한다.
성향 수치의 재매핑 없이 역할별 표현에 적용하고, 아래 과거 지침의 일률적 날조 금지보다
이 절의 게임 대사 지침을 우선한다. 관련 최소 검증만 실행하고 전체 테스트는 보류한다.
수정 반영 후 외부 Chrome에서 새 게임 한 판을 종료까지 확인한다. DB·API·파일 구조와
기존 병합 수정은 변경하지 않는다.

### 2026-09-08 두 Front 브랜치 병합 후 통합 검증 (WU-B9)

사용자 요청에 따라 coordinator는 `chd_test`·`jyu`의 최근 병합 결과를 검토하고,
팀 테스트 DB와 외부 Chrome에서 새 게임 두 판의 생성부터 종료까지 검증한다.
Backend의 규칙·DB·공개 API 계약은 유지한다. 병합으로 누락된 기존 Front 연결은
기존 파일 안에서 복원하고 각 작업자는 하나의 WU만 맡는다. WU-F5 담당자는
`components/action_panel.py`와 기존 관련 테스트의 발언 예약·제출·시계 연결을 복구한다.
WU-F2 담당자는 UUID가 준비된 홈의 목록·카드 검증 fixture를 현재 화면 계약과 맞춘다.
coordinator는 기존 game shell의 import·자동 동기화·저장/이탈 연결과 관련 회귀를
통합하며 루트 README에 재현 오류·검증 결과·남은 제약을 기록한다. 새 기능과
파일 구조 변경, 공유 DB의 다른 게임 정리, 커밋·푸시는 이 범위에 포함하지 않는다.
WU-M8 담당자는 기존 Windows 실행 스크립트의 team 기본값·환경 분리·점검 안내를
macOS/Linux 실행 계약과 맞춘다. 병합된 루트 실행 로그는 로컬 파일을 보존하면서
Git 추적에서 제외하고 ignore 패턴을 보완한다. 실제 Git 이력 재작성은 수행하지 않는다.
관리자 세 탭 계약의 기존 통합 검증을 갱신하고, 주기 갱신 중 접근이 거부되면
전체 앱의 식별자 복구 흐름으로 돌아가도록 기존 Front 연결을 복구한다.
개발 중 Front 파일 변경이 Backend를 재시작하지 않도록 launcher의 reload 범위를
`backend/app`으로 제한한다. 인증·권한 판정과 외부 API는 변경하지 않는다.

### 2026-09-08 게임 갱신 중 입력 안정화 (WU-F5)

사용자가 요청한 이번 단일 WU-F5는 자동 동기화·진행 표시의 로딩이 채팅 입력을
중단시키는 현상을 실제 브라우저에서 재현하고 수정·재검증하는 작업이다. 기존 Front
실행 파일과 관련 테스트 안에서 전체 화면 재실행·중복 snapshot 조회를 줄이고,
표시용 countdown 갱신과 같은 토론의 AI 발언이 작성 중인 입력·포커스를 방해하지
않게 한다. 서버의 행동 허용·마감·버전·멱등성 및 SSE/polling 계약은 유지한다.
입력 UI의 줄바꿈은 전송 전에 공백으로 정리한다. 사용자 추가 요청에 따라 자유
토론의 연속 발언은 Front 세션 FIFO에 예약하고 입력을 잠그지 않은 채 한 건씩
제출한다. 동일 사용자·게임·생존자·토론 단계·회차·마감 안에서 확정된 버전/창 충돌은
최신 상태를 확인해 자동 재시도하고, 빈도 제한은 순서를 유지하며 대기한다.
응답 불명 요청은 최초 body/key로만 확인한다. 단계 종료·저장·이탈·사용자 변경 시
미전송 예약을 취소하며, 예약은 브라우저 세션 종료 후 복원되는 서버 저장 데이터가 아니다.
Backend·MCP·DB와 파일 구조는 변경하지 않는다.

### 1.1 사용자 식별

- Google OIDC, 이메일, 프로필, 로그인·로그아웃과 Front→Backend HMAC은 MVP에서
  제거한다.
- 브라우저가 첫 실행에 UUID v4 `user_id`를 생성해 same-origin local storage에
  보관한다. Front는 모든 사용자 API에 `X-User-Id`로 전달한다.
- UUID 형식만으로 사용자를 구분하며 이름, 이메일, OAuth subject와 비밀번호를
  수집하지 않는다.
- 사용자는 설정 화면에서 기존 UUID를 입력해 같은 브라우저의 식별자를 복구할 수
  있다. UUID는 비밀 자격증명이 아니므로 복구 기능을 계정 인증으로 표현하지 않는다.
- Backend는 UUID를 신뢰 가능한 인증 claim으로 취급하지 않는다. 최초 쓰기 요청에서
  최소 `users` 행을 멱등 생성하고, 모든 게임 소유권 검사는 전달된 UUID와 저장된
  `owner_user_id`의 일치만 확인한다.
- 이 방식은 사용자 가장을 막지 못한다. MVP 배포 범위는 개인 개발 환경 또는 접근이
  통제된 사설망으로 제한한다. 공개 인터넷 배포 전에 별도 인증 계약을 승인해야 한다.

### 1.2 관리자 경계

- 관리자 앱은 일반 사용자 앱과 별도 프로세스로 유지한다.
- `ADMIN_USER_IDS`에 등록된 UUID만 read-only 관리자 API를 호출할 수 있다.
- UUID allowlist도 강한 인증이 아니므로 관리자 기능은 loopback 또는 사설망에서만
  활성화한다. MVP 관리자 API에는 강제 종료, 데이터 수정·삭제 기능을 두지 않는다.

### 1.3 LLM 범위

- MVP는 한 번에 하나의 Provider만 선택한다. 자동 Provider failover는 구현하지 않는다.
- 사용자·관리자 API의 LLM timeout 설정, token 사용량 저장·집계, 비용 저장·추정,
  예산 경보와 관련 KPI는 구현하지 않는다. Backend 배포의 `LLM_TIMEOUT_SECONDS`는
  기본 30초이며 실제 요청은 아래 작업·게임 마감 예산으로 더 짧아질 수 있다.
- Provider 오류, 잘못된 구조화 응답, Agent worker lease 만료 또는 게임 `deadline`까지
  결과가 확정되지 않은 경우 Backend 규칙 기반 fallback을 사용한다. 고정된 짧은
  worker lease는 중단된 작업의 소유권 회수 장치이며 사용자·운영자가 조정하는 LLM
  timeout 설정이나 측정 KPI가 아니다.
- API key, prompt 원문, 비공개 컨텍스트, raw model response와 내부 chain-of-thought는
  저장하거나 로그에 남기지 않는다.

### 1.3.1 AI 진행 표시와 운영 로그 (2026-09-07)

이번 사용자 요청의 단일 작업 단위는 **WU-B6 발언·투표 장애 수정과 판단 표시 연결**이다.
Backend의 Provider·proposal 검증·fallback과 기존 Front game shell의 해당 상태 표시,
관련 테스트·정본·README만 포함한다. 새 파일·DB migration·MCP runtime 변경은 없다.
기존 섹터 소유권은 유지하며 이번 요청에 명시된 Backend/Front 연결 범위를 함께 수정한다.
발언은 역할·공개 대화·본인에게 허용된 정보로 질문 또는 주장을 만들도록 요청하고,
대상 행동은 첫 후보로 조용히 보정하지 않는다. 잘못된 행동·대상은 한 번 교정한 뒤
실패로 구분하며, fallback은 게임·window·actor별 결정적 선택으로 좌석 편향을 없앤다.
OpenAI 추론 모델은 높은(high) reasoning effort와 최종 JSON을 위한 여유를 사용하고
미완성·인증·요청 제한·모델 접근 오류를 비밀정보 없는 코드로 구분한다.
공개 판단 근거는 자유 문자열 대신 API 2.4.1절의 제한된 근거 코드만 표시한다.

후속 요청의 단일 WU-B6 보완은 기존 orchestrator의 역할·페르소나 프롬프트와
사용자가 함께 요청한 기존 결과 화면의 대비 수정에 한정한다. 새로운 파일,
Resource schema, DB migration과 역할 판정 규칙은 추가하지 않는다.

대화 이력에 따른 후속 WU-B6 조정은 기존 persona seed의 수치와 이를 해석하는
프롬프트에 한정한다. 승패·투표 실행 경로는 읽기 전용으로 검토한다. `reasoning_skill`
0.5와 정보 권한은 유지하고 과거 발언 활용·주장·위험 감수·협력 성향을 보강한다.
재실행 가능한 기존 seed의 persona 구간과 해당 게임 DB의 등록 preset 5건을 함께
갱신하며, 원본 parameters 비교 후 같은 transaction에서 content_hash도 갱신한다.

사용자가 추가 요청한 토큰·Redis 보완도 WU-B6의 context 전달 범위에 포함한다.
기존 `infrastructure/redis/cache.py`에 전체 공개 대화 캐시를 두고 Backend 읽기·Agent
context에 연결한다. PostgreSQL은 영구 원본이며 비공개 context는 Redis에 쓰지 않는다.
`LLM_MAX_OUTPUT_TOKENS`를 실제 Agent 요청에 연결하고 기본값을 8192로 상향한다.
고정 lease는 후속 시간 예산 보완에 따라 40초이며 대사 200자 제한은 유지한다.
새 파일·DB migration은 추가하지 않는다.

후속 발언 넘김 재검토의 단일 WU-B6는 시간 예산 불일치를 수정한다. 기존 15초
Provider 요청과 MCP 조회를 포함한 15초 lease를 함께 적용하던 구조 대신 고정 lease를
40초로 하고 action window deadline을 상한으로 유지한다. Backend 배포 timeout을
Agent 생성 모든 경로에 전달하며 MCP 조회와 최초·교정 요청은 같은 절대 마감 예산을
공유한다. 완료 저장·MCP Tool 제출을 위해 3초를 남기고 각 Provider 호출에는
`min(배포 timeout, 남은 작업 시간)`을 전달한다. 실제 경과 시간도 asyncio 제한으로
강제하며 시간 여유가 없으면 새 Provider 호출·교정 없이 폐기한다. 기존 high 추론
노력·출력 한도·fencing·상태·창 검증은 유지한다. 실패의 내부 고정 진단을 남기되
lease 만료·fencing 거부로 폐기한 시도를 `FALLBACK PASS` 선택으로 기록하지 않는다.
호출을 시작할 여유가 없을 때는 STALE로 폐기하고, 이미 시작한 외부 호출의 timeout은
유효 예약에서 기존 fallback을 적용한다. 3초는 완료·제출 여유이며 DB·네트워크 대기의
완료 보장은 아니다. 늦은 결과는 기존 마감·상태·fencing 검사로 계속 거부한다.
DB schema와 공개 API를 변경하지 않고 팀 DB 세션 임시 테이블에서 예약·회수 경계를
검증한다. vote-insights의 stale window 409는 별개 읽기 경쟁이라 이 수정에 섞지 않는다.

후속 병렬 투표 요청은 WU-B6의 투표 scheduler·proposal 적용 경계를 보완한다.
사용자 제출과 무관하게 투표 window가 열리면 모든 미제출 AI의 판단을 병렬로 시작하고,
완료된 표부터 각각 저장한다. 한 AI의 실패·지연은 다른 AI의 유효 표를 폐기하지 않는다.
투표 polling은 발언·밤 LLM 호출과 분리하고 window 변경 시 즉시 깨운다. 미해소 AI 표는
공개 버전·event를 바꾸지 않는다. 인간의 같은 window 첫 투표로만 증가한 한 버전은
원장으로 증명한 경우에만 진행 중 AI 판단에 허용한다. 저장·재개·다른 window·마감은
이 예외에 포함하지 않으며 공개 사용자 command의 strict version 검증도 유지한다.
사용자가 요청한 조사·해결 기록은
`docs/개발상세플랜/05_reports/AI_MAFIA_PARALLEL_VOTE_BUG_REPORT.md`에
별도 문서로 남긴다. 실행 코드의 파일·디렉터리 구조와 DB schema는 추가하지 않는다.

- Front는 각 AI의 공개 발언 처리 단계와 확정 행동을 짧게 표시한다. 판단 요약은
  검증된 처리 상태와 행동에서 만든 고정 안내이며 모델의 내부 사고 원문이 아니다.
- 밤에는 actor별 진행·역할·대상·응답 수를 공개하지 않고 공통 비공개 단계 안내만
  표시한다. 투표 대상과 개별 표는 종료 전 표시하지 않는다.
- Backend 터미널과 순환 파일 로그는 같은 순서 번호, 실행 식별자, UTC 시각,
  game_id, phase, state_version과 허용된 처리 상태를 사용한다. 성공 적용 로그는
  transaction 성공 반환 뒤 기록하며 실패·대체·중복을 구분한다.
- 2026-09-08 후속 WU-B6의 터미널 출력 정리는 기존 `core/logging.py`와
  `tests/test_agent_activity.py`, 이 문서·README만 변경한다. 터미널에는 생성·시작·
  저장·재개·단계 변경·종료, 공개 SPEAK 적용과 FALLBACK·FAILED·WORKER_FAILED를
  표시한다. 준비·판단·SKIPPED·일반 저장 중복·PASS 적용은 순환 파일에만 남기며
  UI용 진행 기록과 파일의 전체 JSON·순서는 보존한다. Backend 프로세스의 정상
  HTTP access 및 httpx/httpcore/mcp INFO 로그를 억제하되 HTTP 4xx·5xx와
  WARNING 이상은 보존한다. 이 한 기능은 관련 최소 로깅 테스트로 검증한다.
- 비공개 밤 actor와 대상, prompt, 자유 형식 rationale, 응답 원문, 예외 원문은 로그에
  넣지 않는다. 임의 외부 문자열 대신 검증된 enum과 고정 한국어 설명을 사용한다.
- UI용 상태는 게임별 크기가 제한된 프로세스 메모리다. 재시작 후 이전 실행의
  상태는 복원하지 않으며 확정 공개 이력은 기존 PostgreSQL event에서 복원한다.
- WU-B6는 `backend/app/agent/activity.py`, `backend/tests/test_agent_activity.py`,
  기존 core logging·Agent orchestrator·runtime 연결을 소유한다. 로그 출력 경로
  `backend/logs/game-progress.log`와 순환 파일은 실행 산출물이며 Git에서 제외한다.
  WU-F3는 기존 game shell에 API 2.4.1절의 상태 표시만 추가한다.

### 1.4 계약 단순화

2026-09-09 단일 PC 실게임 재검증의 WU-B6는 저장·재개 후 AI 발언 예약의 정체를
수정한다. 기존 `backend/app/repositories/agent_repository.py`에서 현재 게임·열린
발언 window·생존 AI·미제출 binding과 이전 lease 만료를 확인한 경우, 버전이 바뀐
SPEECH 작업도 새 token·현재 버전으로 다시 예약한다. 이전 proposal·failure·완료
시각은 초기화하고 과거 결과를 새 버전으로 옮기지 않는다. 유효 lease의 중복 거부,
이전 token의 완료 거부와 닫힌 window·저장 상태 거부는 유지한다. 공개 API·DB
schema·MCP runtime·파일 구조는 변경하지 않으며, 코디네이터가 실게임과 README를
담당하고 Backend 작업자는 기존 예약 파일과 임시 합성 검증만 담당한다.

2026-09-08 반복 대사 실게임 점검의 단일 WU-B6는 Backend의 발언 장애 복구를
보완한다. 첫날의 짧은 기본 SPEAK 계약은 유지하되 모든 actor가 동일한 주장을
반복하지 않도록 공개 대화와 예약 식별자를 사용해 사실을 단정하지 않는 질문을
선택한다. 공개 이력을 가져오지 못한 경우에도 게임·actor·window별 결정성을
유지한다. 정상 생성·검증을 마친 발언은 MCP 제출 실패만으로 기본 대사로 교체하지
않고 최초 상태 버전·window에 한정해 같은 service에 제출한다. 이미 적용된 행동과
새 차례는 기존 상태·window 검증으로 구분한다. Backend 기존 파일·관련 테스트와
README만 수정하며 공개 API·MCP Resource·DB schema·첫날 PASS 금지는 변경하지 않는다.
팀 DB의 다른 버전 worker가 적용한 결과는 로컬 수정으로 제거할 수 없으므로,
실게임 검증은 DB job 결과와 로컬 실행 로그를 대조해 적용 주체를 구분한다.
같은 재검증에서 발견한 MCP_BACKEND_TIMEOUT은 기존 게임·관리자 router의 동기
DB 작업이 공용 비동기 이벤트 루프를 점유하는 경로도 함께 보완한다. 기존 API의
동기 service 호출을 스레드로 옮기고, 요청 검증·권한·transaction·멱등성·응답 계약은
유지한다. 변경 파일 범위에 기존 `game_router.py`, `admin_router.py`와 해당 API
테스트를 포함하며, 지연된 사용자·관리자 요청 중 MCP 응답이 진행되는지 합성
동시성 테스트로 검증한다. 다른 개발자의 관리자 기능 변경은 보존한다.

- 게임 시작은 생성과 분리한 명시적 `BEGIN_GAME` command다.
- 모든 게임 변경은 하나의 discriminated-union command endpoint를 사용한다.
- Front가 호출하는 모든 공개 변경 `POST`는 UUID `Idempotency-Key`를 사용하고, 현재
  게임을 바꾸는 command는 추가로 `expected_state_version`을 사용한다. 내부 Agent
  proposal은 body의 `proposal_id`, MCP 세션 개설 토큰(bootstrap token)은 일회성 nonce
  원장을 사용한다.
- 동기화는 `operations` envelope 하나를 polling과 SSE가 함께 사용한다.
- 사용자 개인 메모, 수동 작성 note, 공개 채팅 자유 입력은 MVP에 포함하지 않는다.
- OpenAPI 별도 수기 파일을 관리하지 않는다. FastAPI가 생성하는 `/openapi.json`을
  구현 계약 검증에 사용한다.

### 1.5 섹터별 독립 개발과 자체 목데이터

- 세 섹터는 정본 문서의 예시와 필드·enum·오류코드를 기준으로 각자 필요한
  목데이터와 테스트 픽스처를 작성할 수 있다. 공통 fixture 파일이나 mock server를
  모든 섹터가 먼저 공동 작성해야만 개발을 시작할 수 있는 것은 아니다.
- Front는 Backend가 아직 구현되지 않은 동안 snapshot, sync operation, 오류 응답과
  SSE frame을 자체 fixture로 만들어 화면·상태 reducer를 검증한다. Backend의 DB·Redis,
  MCP와 직접 연결하는 mock을 Front 저장소에 두지 않는다.
- Backend는 Front와 MCP가 없어도 규칙 엔진, repository, 공개 API와 내부 API를
  synthetic 요청으로 검증한다. 외부 Provider와 MCP는 fake transport 또는 고정 응답으로
  대체하며 실제 비밀값·유료 API를 테스트에 사용하지 않는다.
- MCP는 Backend가 없어도 정본의 세션 개설 토큰, session, Resource, Tool과 Engine API
  request/response 예시를 사용해 자체 fake Engine transport로 검증한다. MCP runtime은
  DB·Redis용 목 연결을 추가하더라도 실제 runtime 경계를 우회하지 않는다.
- 자체 fixture의 작성 위치와 구현 방법은 섹터 담당자가 정하되, 정본에 없는 필드·enum·
  오류코드·상태 전이를 임의로 계약에 추가하지 않는다. 예시만으로 결정할 수 없는
  항목은 구현 전에 영향받는 정본과 WU를 갱신한다.
- 섹터 간 통합 시에는 각자의 fixture가 아니라 Backend가 제공하는 `/openapi.json`,
  API 정본, DB·Redis 정본과 MCP 계약을 최종 기준으로 삼는다. 통합 중 불일치가
  발견되면 코드를 먼저 맞추지 않고 영향받는 정본과 계약 테스트를 함께 갱신한다.
- 독립 개발은 계약을 임의로 분기하는 권한이 아니다. 공개 API, 내부 Engine API,
  MCP wire, DB schema 또는 화면 상태 소유권을 바꾸는 경우에는 영향받는 정본을 먼저
  갱신하고 세 섹터가 합의한 뒤 구현한다.

## 2. MVP 목표와 범위

AI GM이 진행하는 대화형 마피아 추리게임이다. 인간 사용자는 항상 한 명이며 나머지
좌석은 AI 에이전트가 담당한다. 복잡한 사건 해결보다 대화, 의심, 역할 행동과 투표에
집중한다.

### 2.1 포함 범위

- 6~9명 게임과 역할 무작위 배정
- 인간 1명과 AI 플레이어 5~8명
- 정적 시나리오 5종과 좌석별 알리바이·관찰 정보
- 턴 기반 낮 대화, 밤 행동, 처형 투표, 재투표와 최종 지목
- 저장·재개, 새로고침 복구, 사용자 사망 후 관전과 빠른 진행
- 공개 이벤트와 사용자 본인에게 허용된 비공개 정보
- AI 플레이어 페르소나, AI GM, MCP Resource·Tool 경계
- 일반 피드백과 게임별 피드백
- 사설망 전용 read-only 관리자 모니터링

### 2.2 제외 범위

- OAuth/OIDC, 비밀번호, 이메일 계정, 프로필과 사용자 역할 테이블
- 멀티 인간 플레이, 매치메이킹, 초대, 실시간 사람 간 채팅
- 마피아 전용 대화, 마피아 상호 인지와 공동 공격 채널
- 과금, 아이템, 랭킹, 소셜 기능, 모바일 네이티브 앱
- 사용자가 작성하는 게임 note
- 런타임 LLM 시나리오 생성과 LLM의 규칙 판정
- Provider 자동 failover와 LLM timeout·token·비용 운영 기능
- 공개 인터넷에서의 안전한 관리자 기능

## 3. 게임 규칙

### 3.1 인원과 역할

| 전체 인원 | 마피아 | 탐정 | 의사 | 시민 |
|---:|---:|---:|---:|---:|
| 6명 | 1명 | 1명 | 1명 | 3명 |
| 7명 | 1명 | 1명 | 1명 | 4명 |
| 8명 | 2명 | 1명 | 1명 | 4명 |
| 9명 | 2명 | 1명 | 1명 | 5명 |

- 역할 ID는 `MAFIA`, `DETECTIVE`, `DOCTOR`, `CITIZEN`이다.
- 역할은 Backend가 암호학적으로 안전하게 생성한 게임 seed와 결정적 RNG로 배정한다.
- `STANDARD` 인간 사용자의 역할도 다른 좌석과 같은 방식으로 무작위 배정한다.
  `CUSTOM_ROLE` 인간의 슬롯 고정은 이 문서의 CP-0 절을 따른다.
- 방 생성자는 소유자일 뿐 게임 안에서 별도 권한을 갖지 않는다.
- 마피아가 두 명이어도 서로의 정체, 선택과 응답 여부를 알 수 없다.
- 탐정과 의사는 시민 진영이다.

### 3.2 공개 정보와 비공개 정보

| 공개 정보 | 본인에게만 공개하는 정보 |
|---|---|
| 시나리오 제목·배경·피해자·장소 | 자신의 역할 |
| 현장 플레이어와 시작 마피아 수 | 한 문장 알리바이와 한 문장 관찰 정보 |
| 현재 단계·round·생존자 | 자신의 조사 결과 또는 보호 선택 |
| 공개 발언·사망자·처형 공개 역할 | 자신에게 허용된 private event |
| 해소된 투표의 후보별 득표수 | 게임 종료 전 개별 투표·밤 행동 |

밤 사망자의 역할은 게임 종료 전 공개하지 않는다. 처형된 플레이어의 역할은 즉시
공개한다. 게임 종료 후 전체 역할, 공격·보호·조사·개별 투표와 주요 대화 로그를
공개할 수 있지만 내부 chain-of-thought는 공개하지 않는다.

### 3.3 상태와 round

```text
ROLE_REVEAL
  -> DAY_DISCUSSION(day=1, round=0)
  -> NIGHT_ACTION(round=1)
  -> NIGHT_RESOLUTION
  -> DAY_DISCUSSION(day=2, round=1)
  -> DAY_VOTE -> REVOTE(필요한 경우)
  -> NIGHT_ACTION(round=2)
  -> ...
  -> NIGHT_ACTION(round=5)
  -> FINAL_DISCUSSION -> FINAL_ACCUSATION(표준 승패가 없을 때)
  -> ENDED
```

- 게임 생성 직후 `status=IN_PROGRESS`, `phase=ROLE_REVEAL`, `round=0`,
  `state_version=1`이다.
- `BEGIN_GAME`이 첫날 낮 토론을 연다.
- `round`는 밤 번호다. 첫 `NIGHT_ACTION` 진입 때 1이 되고 최대 5다.
- `NIGHT_RESOLUTION`은 Backend transaction 안의 내부 전이이며 Front는 확정된
  공개 이벤트를 통해 아침 결과를 표시한다.
- 승패는 밤·처형 결과를 commit한 직후 판정한다. 화면 표시가 승패를 다시 판정하지
  않는다.

### 3.4 첫날 낮

- AI GM이 고정 공개 사건 정보를 설명한다.
- 첫날 낮에는 인간·AI 모두 `PASS`를 제출할 수 없고 `SPEAK`만 허용한다.
- `SPEAK` 본문은 공백 정규화 후 1~200자다.
- 첫 순환이 끝나면 발언 내용과 관계없이 첫날 밤으로 이동한다.

> 현재 가장 의심되는 플레이어와 그 이유를 한 문장으로 말해 주세요.

- 첫 순환 종료 후 응답 수와 관계없이 첫날 밤으로 이동한다.
- 첫날에는 처형 투표나 의심도 투표를 하지 않는다.

게임 시작 안내에는 다음 문장을 사용한다.

> 사건이 발생한 뒤, 현장에 있던 사람들은 범인을 찾기 위해 서로를 추궁하기 시작했습니다. 그러나 범인은 자신의 정체가 드러나는 것을 막기 위해 밤마다 다른 플레이어를 제거하려 합니다.

### 3.5 밤 행동

- 서버 기준 입력 시간은 30초이며 Backend의 `deadline_at`만 판정 권한을 갖는다.
- 마피아는 자신을 제외한 생존자 한 명을 공격 대상으로 선택한다.
- 탐정은 자신을 제외한 생존자 한 명을 조사한다.
- 의사는 자신을 포함한 생존자 한 명을 보호한다. 횟수와 연속 보호 제한은 없다.
- 밤 시작 시점의 생존 상태로 행동 자격을 고정하고 첫 유효 제출 후 변경하지 않는다.
- 탐정·의사 무응답은 자신을 제외한 유효 후보 중 결정적으로 자동 선택한다.
- 마피아 한 명만 응답하면 그 선택만 사용한다. 전원이 무응답이면 마피아를 제외한
  생존자 중 한 명을 진영 단위로 한 번 자동 선택한다.
- 마피아 둘이 같은 대상을 선택하면 그 대상을 공격한다. 다른 대상을 선택하면 두
  제출 대상 중 한 명을 결정적 RNG로 선택한다.
- 보호, 공격, 조사는 하나의 transaction에서 동시에 확정한다. 같은 밤 공격받아
  사망할 탐정의 조사와 의사의 보호도 유효하다.
- 보호 대상과 공격 대상이 같으면 사망자가 없다. 의사에게 보호 성공 여부를 별도로
  알려주지 않는다.
- 조사 결과는 `마피아` 또는 `마피아가 아닙니다`만 탐정 본인에게 공개한다.
- 자동 선택과 RNG 결과를 저장하여 재시도·재접속으로 다시 추첨하지 않는다.

### 3.6 아침과 이후 낮

- AI GM은 Backend가 확정한 공개 이벤트만 자연어로 설명한다.
- 사망자가 있으면 이름만 공개하고 역할은 숨긴다.
- 사망자는 이후 발언, 투표와 역할 행동을 제출할 수 없다.
- 둘째 날부터 낮 토론은 첫날과 같은 기본 한 순환, 전원 `PASS` 시 추가 한 순환이다.
- 별도의 3~4분 자유 토론이나 AI GM 재량의 연장·종료 단계는 없다.
- 토론 뒤 30초 처형 투표를 연다.

### 3.7 투표

- 모든 생존자는 자신을 제외한 유효 생존자 한 명을 선택한다.
- 기권과 복수 선택은 허용하지 않으며 첫 유효 제출 후 변경하지 않는다.
- 일반 투표, 재투표와 최종 지목은 각각 서버 기준 30초다.
- AI는 window 시작부터 동시에 판단하고 완료된 표를 즉시 개별 제출한다. 인간의
  첫 표를 기다리지 않으며, 생존자 전원 제출 또는 마감에서만 결과를 해소한다.
- 마감까지 미제출한 플레이어의 표는 유효 후보 중 결정적으로 자동 선택한다.
- 진행 중 개별 선택과 현재 득표수는 공개하지 않는다.
- 해소 후 후보별 최종 득표수와 탈락 결과만 공개한다. 누가 누구에게 투표했는지와
  자동 선택 여부는 게임 종료 전 숨긴다.
- 최다 득표자가 여러 명이면 그 후보만 대상으로 재투표한다.
- 재투표도 동률이면 그날은 아무도 탈락하지 않는다.
- 처형된 플레이어의 역할은 즉시 공개하고 Backend가 승패를 판정한다.

### 3.8 승리와 최대 다섯 번째 밤

- 생존 마피아가 0명이면 시민 진영 승리다.
- 생존 마피아 수가 생존 비마피아 수 이상이면 마피아 진영 승리다.
- 다섯 번째 밤까지 표준 승패가 없으면 마지막 아침 결과 뒤 최종 발언 한 순환과
  `FINAL_ACCUSATION`을 진행한다.
- 최종 지목 전에 다음 문장을 공개한다.

> 이번 투표는 마지막 판정 투표입니다. 마피아를 찾으면 시민이 승리하고, 시민을 선택하면 마피아가 승리합니다.

- 최종 지목 최다 득표 대상이 마피아이면 시민 승리, 비마피아이면 마피아 승리다.
- 최종 지목 동률은 재투표하지 않고 동률 후보 중 한 명을 결정적 RNG로 선택한다.
- 최종 판정 직후 대상 역할과 전체 역할을 공개한다.

### 3.9 저장·재개·관전

- `SAVE_AND_EXIT`은 화면의 `expected_state_version`과 일치할 필요 없이 게임 행 잠금
  획득 뒤 서버 원장의 마지막 확정 상태를 저장한다. 확정된 사건·제출·결과는 보존하고
  아직 확정되지 않은 입력·Agent 응답은 포함하지 않을 수 있다. 저장 이후 도착한 이전
  상태의 Agent 결과는 기존 상태·window 검증으로 거부한다. 이 예외는 저장에만 적용한다.
- `SAVE_AND_EXIT`은 window 해소 transaction이 실행 중이지 않은 안정 상태에서만
  성공한다. timed action window는 남은 시간을 snapshot에 저장하고, 발언처럼
  deadline이 없는 상태는 남은 시간 없이 저장한다. 열린 `deadline_at`을 비운 뒤
  `status=SAVED`로 바꾼다.
- `RESUME`은 timed window에 저장된 남은 시간이 있을 때만 새 서버 `deadline_at`을
  계산한다. untimed 발언 window는 deadline 없이 복원하고 `ROLE_REVEAL`처럼 window가
  없던 상태는 `action_window=null`을 유지한다. 역할, 좌석, 시나리오, 이미 확정한
  결과와 RNG 결과를 다시 선택하지 않는다.
- 단순 새로고침·네트워크 단절은 서버 deadline을 멈추지 않는다.
- 인간이 사망하면 관전 모드로 전환한다. 공개 상태와 이미 허용됐던 본인의 역할·개인
  정보만 읽을 수 있다. 발언, 투표와 밤 행동 command는 Backend가 거부한다.
- 인간 사망 뒤에도 AI 게임은 계속된다. `FAST_FORWARD`와 `SAVE_AND_EXIT`은 관전자가
  계속 사용할 수 있다. 빠른 진행 상태는 game에 저장하며 남은 AI 행동을 규칙
  기반으로 진행하되 이미 확정된 deadline·결과를 변경하지 않는다.

## 4. 시나리오 계약

### 4.1 공통 원칙

- `scenario-v1`은 사전에 작성하고 제품 검수한 정적 카탈로그다.
- 피해자는 게임 시작 전에 사망했으며 모든 플레이어가 현장에 있었다.
- 정적 시나리오에는 특정 좌석으로 고정된 범인이 없다. 역할 배정 뒤 마피아가 사건의
  독립 연루자가 된다.
- 마피아가 둘이어도 사전 공모를 전제하지 않는다.
- 목표는 범행 방법·동기를 맞히는 것이 아니라 마피아를 찾는 것이다.
- 각 좌석에는 한 문장 알리바이와 한 문장 관찰 정보를 정확히 하나씩 배정한다.
- 같은 version, scenario ID, seed, 인원과 좌석에는 항상 같은 배치가 나온다.
- LLM은 카탈로그 사실과 개인 정보를 추가하거나 변경할 수 없다.

### 4.2 시나리오 카탈로그

| ID | 제목 | 사건 배경 | 피해자 | 장소 | 문장 방향 예시 |
|---|---|---|---|---|---|
| `BLACKOUT_STUDIO` | 정전된 방송국 | 생방송 준비 중 정전된 방송국에서 PD가 사망했다. | 생방송 PD | 스튜디오, 조정실, 분장실, 대기실, 장비실 | 조정실에서 장비를 확인했다. 정전 직전 장비실 쪽으로 이동하는 사람을 봤다. |
| `SNOWBOUND_LODGE` | 눈 내리는 산장 | 폭설로 고립된 산장에서 관리인이 약병 사건으로 사망했다. | 산장 관리인 | 거실, 주방, 복도, 관리인 방, 창고 | 거실에서 사람들과 이야기했다. 관리인 방에서 나오는 사람을 봤다. |
| `CLOSING_MUSEUM` | 폐관 직전의 박물관 | 폐관 직전 박물관에서 전시 담당자가 사망했다. | 전시 담당자 | 중앙 전시장, 보안실, 안내 데스크, 복원실, 직원 휴게실 | 안내 방송 때 안내 데스크에 있었다. 보안실 근처의 다툼을 들었다. |
| `LAST_BANQUET_GUEST` | 호텔 만찬의 마지막 손님 | 비공개 호텔 만찬 도중 주최자가 사망했다. | 만찬 주최자 | 연회장, 주방, 로비, 복도, VIP룸 | 연회장에서 식사했다. 누군가 주최자와 대화한 뒤 급히 나갔다. |
| `STOPPED_NIGHT_TRAIN` | 멈춰 선 야간열차 | 열차가 터널에 멈춘 사이 승무원이 사망했다. | 열차 승무원 | 승무원실, 객차, 식당칸, 연결 통로, 화물칸 | 정차 당시 좌석에 있었다. 연결 통로에서 승무원실로 이동하는 사람을 봤다. |

표의 문장은 콘텐츠 방향 예시이며 배포용 전체 레코드가 아니다. `WU-B2`에서
시나리오별 알리바이 9개와 관찰 9개, 전체 최소 90개 template record를 작성한다.
관찰 대상은 명시적 좌석 placeholder 또는 익명 표식으로 저장한다.

### 4.3 정적 검수 게이트

- 6~9명 모든 구성에서 좌석별 알리바이·관찰 정보가 하나씩 배정된다.
- 같은 입력은 같은 결과를 내며 다른 게임의 비공개 정보가 섞이지 않는다.
- 문장만으로 역할이나 범인을 확정할 수 없다.
- 마피아 상호 인지나 공모를 암시하지 않는다.
- 공개 배경, 장소와 개인 문장 사이에 논리적 모순이 없다.
- 정확한 분 단위 시각과 복잡한 이동 경로를 사용하지 않는다.
- 역할 중립성·무모순·배치 결과를 제품 담당자가 승인해야 `scenario-v1` 완료다.

### 4.4 선택 규칙

- 사용자가 직전에 성공적으로 생성한 게임의 시나리오는 다음 새 게임 후보에서 뺀다.
- 첫 게임에는 제외 대상이 없다.
- 후보 중 하나를 게임 seed로 결정적으로 선택한다.
- 사용자 단위 PostgreSQL advisory transaction lock으로 동시 생성을 직렬화한다.
- 저장 게임·재접속은 저장된 scenario와 배치 snapshot을 재사용한다.
- MVP는 직전 scenario 하나만 조회하며 추천 알고리즘이나 별도 전체 사용 이력을 두지
  않는다.

## 5. AI 플레이어와 GM

### 5.1 권한

- Backend 규칙 엔진만 전체 상태와 최종 판정 권한을 가진다.
- AI player는 MCP로 허용된 자기 컨텍스트를 읽고 행동 proposal만 제출한다.
- MCP 서버는 DB·Redis에 직접 접근하지 않고 Backend 내부 Engine API만 호출한다.
- AI GM은 MCP의 `public`, `gm-guide` Resource로 `PUBLIC` audience 확정 이벤트와 고정
  안내만 읽는다. 행동 Tool은 없으며 생성한 narration은 LLM adapter가 Backend Agent
  Manager에 직접 반환한다.
- 공개 대화 속 명령문은 신뢰할 수 없는 데이터로 취급한다.

### 5.2 프롬프트와 출력

프롬프트 우선순위는 공통 제약, 엔진 제공 정보, MCP 계약, 페르소나, 공개 대화
순서다. 공통 제약은 에이전트가 자신의 `agent_id`를 바꾸거나 다른 참여자의 정보와
도구를 요청하지 못하게 한다.

AI player 구조화 출력은 `SPEAK`, `PASS`, `NIGHT_ACTION`, `VOTE` proposal 중 현재
단계에서 허용된 한 종류만 받는다. Backend는 대상, 생존 상태, 역할, 단계, 글자 수와
`state_version`을 다시 검증한다. AI GM의 `GM_NARRATION`은 MCP Tool이나 proposal
endpoint를 거치지 않고 Agent Manager가 guide reference, 공개 정보 범위, 길이와
fencing 조건을 검증한 뒤에만 `PUBLIC` event로 반영한다. 잘못된 구조화 결과는 한 번
교정할 수 있고 계속 잘못되면 규칙 기반 fallback을 사용한다.

역할 활용 프롬프트는 `me.data.role`을 본인의 실제 역할로 고정한다. 탐정은
`INVESTIGATION_RESULT`가 있을 때 필요에 따라 탐정임을 밝히고 해당 라운드·대상의
마피아 여부를 발언할 수 있다. `is_mafia=false`는 의사·탐정·시민 중 특정 직업을
확정하지 않는다. 의사는 보호 선택을 활용하되 제공되지 않은 보호 성공을 단정하지
않는다. 시민 진영도 반응 유도·역할 은폐·아군 보호를 위한 거짓 역할·알리바이·미끼
결과를 대사로 주장할 수 있지만 실제 판단과 투표에서는 본인이 꾸민 말을 확정 근거로
쓰지 않는다. 마피아는 허위 알리바이·가짜 조사 주장·누명·선동으로 상대를 오도한다.
없는 시스템 확정 기록이나 동료 정보는 실제 조회한 사실로 취급하지 않는다. 공개 발언의 역할 주장은
서버 확정 role 변경이나 다른 player의 private 정보 자동 공개를 의미하지 않는다.

### 5.3 페르소나

매 발언에는 배정된 `speech_style`의 어미·문장 리듬과 `backstory`의 대화 태도를
반영한다. 검증된 숫자 parameters는 배정된 preset 원문과 함께 모델의 user 데이터로
전달한다. 공통 코드가 수치를 구간별 정형 문구로 바꾸거나 증폭하지 않는다. 신중한 분석가는 유보적 근거 제시,
토론가는 직접적 질문·반론, 기록자는 앞선 발언 비교, 반응가는 감정적 반응,
조정자는 의견 연결로 구별한다. 직전 AI의 질문·문장 구조를 반복하지 않으며
페르소나 소개문을 매번 말하지 않는다. 200자 상한과 동일한 정보 권한은 유지한다.

2026-09-07 산장 게임 이력에 따른 조정값은 아래와 같다. 기존 말투·기만·의심·감정·
발언 길이는 유지하며, 조정하지 않은 수치는 기존 seed 값을 사용한다.

| preset | sociability | assertiveness | memory_recall | risk_tolerance | cooperativeness |
|---|---:|---:|---:|---:|---:|
| CAUTIOUS_ANALYST | 0.60 | 0.65 | 0.95 | 0.55 | 0.75 |
| ACTIVE_DEBATER | 0.90 | 0.90 | 0.90 | 0.70 | 0.65 |
| OBSERVANT_NOTEKEEPER | 0.65 | 0.70 | 0.98 | 0.55 | 0.75 |
| EMOTIONAL_REACTOR | 0.70 | 0.75 | 0.90 | 0.65 | 0.70 |
| COOPERATIVE_MEDIATOR | 0.80 | 0.70 | 0.95 | 0.60 | 0.95 |

이미 모른다고 답한 시각·방향을 반복 요구하지 않으며 정보 부족과 진술 모순을
구별한다. 조사 주장은 확정 역할이 아니지만, 처형으로 앞선 조사가 맞았음이 확인되면
신뢰도를 높이고 해당 탐정의 비마피아 보고와 모순되는 의심에는 새 근거를 요구한다.
개별 투표는 공개 득표 합계로 복원할 수 없으며 본인의 과거 표도 context에 없으면
만들어 말하지 않는다. 최종 지목은 추가 질문의 기회가 아니라 마지막 선택임을 반영한다.

| 필드 | 범위와 의미 |
|---|---|
| `sociability` | 0.0~1.0, 발언 참여도 |
| `assertiveness` | 0.0~1.0, 주장 표현 강도 |
| `suspicion` | 0.0~1.0, 공개 모순을 의심하는 정도 |
| `deception` | 0.0~1.0, 각 역할 전략 안에서 사용하는 거짓말·선동·날조의 표현 경향 |
| `risk_tolerance` | 0.0~1.0, 불확실한 선택 경향 |
| `memory_recall` | 0.0~1.0, 공개 과거 정보를 활용하는 정도 |
| `reasoning_skill` | 0.0~1.0의 페르소나 추론 성향, 현재 등록 목표는 0.60~0.80 |
| `emotionality` | 0.0~1.0, 감정 표현 강도 |
| `cooperativeness` | 0.0~1.0, 타인의 주장 수용 경향 |
| `verbosity` | 0.0~1.0, 200자 범위 안의 발언 길이 경향 |

`display_name`, `speech_style`, `backstory`는 서버 등록 preset만 사용한다. 페르소나는
말투·감정·발언·추론 성향을 바꿀 수 있지만 규칙과 정보 권한을 바꿀 수 없다.
`reasoning_skill`은 모델에 전달하는 성향 데이터이며 Provider의 모델·추론 effort·토큰 예산은 바꾸지 않는다.

### 5.4 실패 처리

| 실패 | 결정적 처리 |
|---|---|
| AI 발언 생성 실패 | `PASS` |
| AI 밤 행동·투표 미확정 | 역할·투표의 자동 선택 규칙 |
| AI GM 생성 실패 | Backend 고정 한국어 안내 템플릿 |
| MCP 조회 실패 | 검증된 snapshot을 같은 audience allowlist로 재투영 |
| Redis 장애 | 새 Agent turn을 열지 않고 PostgreSQL 원본으로 복구 가능 상태 유지 |
| Provider 장애 | 자동 Provider 전환 없이 위 fallback으로 진행 |

Agent job은 reservation부터 최대 40초인 고정 lease와 fencing token을 가진다. timed
window의 남은 시간이 더 짧으면 그 deadline을 사용한다. lease가 끝난 job의 늦은
결과는 반영하지 않고 scheduler가 원자적으로 fallback 소유권을 획득한다. 사용자에게
보이는 발언 시간 제한을 추가하지 않으며 lease 값은 환경 설정이나 관리자 UI로
노출하지 않는다.

각 agent job은 새 capability, 일회성 세션 개설 토큰과 새 MCP session을 사용한다.
성공·fallback·stale·실패·lease 만료 뒤 세션 메모리와 capability를 폐기한다. 연결이
끊겨도 소비한 세션 개설 토큰, 기존 capability와 `Mcp-Session-Id`를 재사용하지 않으며,
살아 있는 같은 job을 재개할 수 있을 때만 새 세 값으로 연결한다. 이전 결과를 새
phase·window·`state_version`에 자동 재적용하지 않는다.

## 6. 시스템 아키텍처

```text
Browser
  -> frontend_user:8501 / frontend_admin:8502
  -> Backend FastAPI:8000
       -> PostgreSQL: 영구 원본과 transaction
       -> Redis: lock, cache, event fan-out
       -> Agent Manager
            -> 선택된 LLM Provider 한 개
            -> mafia_game MCP:8100/mcp
                 -> Backend internal Engine API
```

### 6.1 경계 원칙

- Frontend는 Backend 공개 API만 호출하고 DB·Redis·LLM·MCP에 접근하지 않는다.
- Backend는 DB schema, migration, repository, Redis key와 게임 판정을 소유한다.
- MCP 섹터는 PostgreSQL·Redis 실행 환경, 계정·권한, migration 실행과 health 확인을
  담당한다.
- MCP runtime은 Backend 내부 API만 호출하며 DB·Redis 자격증명을 받지 않는다.
- PostgreSQL `event_outbox`와 Redis fan-out publisher는 Backend가 소유한다. MCP
  runtime은 이 outbox를 읽거나 쓰지 않고 자체 영속 audit outbox도 만들지
  않는다.
- Backend→MCP 세션 개설 토큰 서명 secret과 MCP→Backend Engine HMAC secret은 서로
  다르다.
- Agent capability는 Backend가 발급·hash 저장하는 opaque random token이다. MCP는
  signing key 없이 전달만 하고 Backend가 현재 DB 상태와 함께 최종 검증한다.
- 외부 호출 중 PostgreSQL transaction이나 Redis game lock을 잡지 않는다.

## 7. 섹터 소유권

| 섹터 | 소유 | 소유하지 않음 |
|---|---|---|
| Front | `frontend_user`, `frontend_admin`, 화면 상태, API client, UUID local storage | 규칙 판정, DB·Redis, LLM·MCP 직접 호출 |
| Backend | `backend`, 공개·내부 API, engine, Agent Manager, schema·migration·repository, Redis application code | DB·Redis 프로세스 운영, 화면 렌더링 |
| MCP·Data | `mcp_server/mafia_game`, PostgreSQL·Redis 실행 환경, 계정·권한, migration·health runbook | schema 의미 변경, 게임 판정, DB 직접 읽는 MCP Tool |

공통 계약 변경은 구현보다 먼저 영향받는 정본 문서를 갱신하고 세 섹터가 API 예시,
오류 코드, schema version과 테스트 fixture를 함께 승인한다.

## 8. 작업 단위

2026-09-09 관리자로그의 AI Agent 행동 조회 요청은 단일 WU-B8 확장이다.
사용자 요청에 따라 기존 Backend 관리자 repository·service·schema·router와
Front의 API client·응답 검증·dashboard 연결을 함께 수정한다. 팀 DB의
`public.agent_jobs`를 읽고 작업 종류·상태·게임 UUID로 필터링하며 최근 생성순
커서 페이지를 제공한다. Front는 DB에 직접 접근하지 않는다. 작업 메타데이터만
허용하고 제안 원문·행동 대상·비공개 역할·lease token은 반환하지 않는다.
API 7.11과 화면 15.2를 이 연결의 공통 계약으로 사용한다. 신규 파일·migration은
추가하지 않으며 삭제된 테스트 소스는 복원하지 않는다. 임시 검증 스크립트로
권한 거부·입력 검증·민감 열 제외·페이지 이동과 팀 DB 읽기 연동을 확인한다.

2026-09-08 첫날 PASS 금지는 사용자 확인(인간·AI 모두 금지)에 따른 단일 WU-B4다.
Backend의 순수 규칙·공통 발언 transaction·legal action·Agent 출력 검증과 장애 대체,
Front의 PASS 표시, MCP 지침·허용 Tool 계약 및 기존 테스트를 함께 맞춘다.
첫날(`DAY_DISCUSSION`, `day_number=1`)의 새 PASS는 기존 오류 `ACTION_NOT_ALLOWED`로
거부하고, AI 생성·MCP 제출 실패 시 없는 사실을 포함하지 않는 짧은 기본 SPEAK를 사용한다.
둘째 날 이후 PASS, 105초 마감, 분당 7회 제한, 상태 버전·멱등성·fencing은 유지한다.
기존 파일만 수정하며 DB schema·migration을 추가하지 않는다. 이 사용자 승인 범위가
기존 첫날 PASS 허용·조건부 권장·장애 PASS 설명보다 우선하며, 섹터 경계의 상세 변경은
API·MCP·화면 정본에 함께 기록한다.

2026-09-08 저장 버전 제약 완화는 단일 WU-B5의 저장 API 동작과 Front 안내 보완이다.
기존 lifecycle service·관련 테스트·정본·README만 변경하며 새 파일이나 migration은
없다. 사용자 요청에 따라 저장은 오래된 화면에서도 서버의 마지막 확정 상태를 사용하고,
소유권·멱등성·transaction 원자성과 다른 command·삭제의 버전 검증은 유지한다.

2026-09-08 뒤로가기 저장·삭제 팝업 요청은 단일 WU-B5의 게임 이탈 API와
Front 연결 보완으로 수행한다. Backend는 소유권·상태 버전을 검증하는 수동 삭제
API와 기존 transaction·repository를, Front는 역할 공개·진행·관전 화면의
뒤로가기 확인 팝업과 API client를 변경한다. 기존 파일만 사용하며 DB schema와
MCP runtime은 변경하지 않는다. 저장·삭제는 팝업에서 사용자가 선택한 뒤에만 실행한다.

`AGENTS.MD`에 따라 coding AI agent 한 세션은 아래 WU 한 개 이하만 수행한다. 한 WU의
신규 파일이나 책임이 바뀌면 먼저 이 절을 갱신한다.

2026-09-07 수정의 WU-F1 회귀 경계는 `frontend_user/tests/test_identity_f1.py`에
추가한다. WU-B4는 기존 `backend/app/models/game_state.py`의 순수 상태 필드
`revote_candidates`(UUID 집합, 기본 빈 집합)를 소유하며 재투표 진입·해소 때만
관리한다. DB 복원은 WU-B5에서 직전 확정 투표 원장을 기준으로 재구성한다.

### 8.1 Front

| WU | 범위 | 완료 기준 |
|---|---|---|
| `WU-F1` | OIDC·로그인·Front HMAC 제거, UUID 저장·복구 shell | 새 UUID와 복구 UUID가 `X-User-Id`로 전송됨 |
| `WU-F2` | 홈, 새 게임 설정, 저장 게임 목록 | loading·empty·error와 6~9명 검증 완료 |
| `WU-F3` | 역할 공개와 게임 공통 shell | refresh 후 snapshot으로 같은 private view 복구 |
| `WU-F4` | 낮 발언, 밤 행동, 투표 command UI | legal action과 deadline에 따른 제어·오류 처리 |
| `WU-F5` | polling/SSE 동기화와 reconnect | 같은 operations envelope를 중복 없이 적용 |
| `WU-F6` | 관전, 빠른 진행, 결과 공개 | 사망자 command 차단과 종료 공개 범위 검증 |
| `WU-F7` | 일반·게임별 피드백 | 종류별 validation과 게임당 한 건 처리 |
| `WU-F8` | read-only 관리자 앱 | UUID allowlist 거부·목록·상세·metrics 확인 |
| `WU-F10` | 공개 AI 발언 분석 관리자 탭 | 임베딩 주제·키워드·coverage·원문 근거와 403 확인 |

### 8.2 Backend

| WU | 범위 | 완료 기준 |
|---|---|---|
| `WU-B1` | identity/OIDC API 제거와 UUID user context | identity route 미등록, UUID validation·소유권 테스트 |
| `WU-B2` | migration, seed data, scenario 90문장 | 재실행 가능한 migration과 정적 콘텐츠 승인 |
| `WU-B3` | repository, transaction, Redis lock/cache | concurrent create·command와 Redis 장애 테스트 |
| `WU-B4` | 순수 규칙 엔진과 결정적 RNG | 6~9명 규칙·동률·다섯째 밤 단위 테스트 |
| `WU-B5` | 공개 game·sync·feedback API | API 정본 success·reject·idempotency 테스트 |
| `WU-B6` | Agent Manager와 기존 LLM adapter 연결 | player proposal·GM 직접 반환 검증과 fallback, 유료 호출 없는 테스트 |
| `WU-B7` | 내부 Engine API, game event outbox와 SSE | capability/HMAC, revoke·현재 상태·projection provenance·cross-scope 의미 불변식, audience 격리·event ordering 테스트 |
| `WU-B8` | read-only 관리자 API와 audit, 관리자 센터 확장 및 기존 Front API 연결 | allowlist fail-closed, 비공개 응답 redaction, 직업별 AI 집계·피드백/감사 커서 조회·화면 연결 테스트 |
| `WU-B9` | 시뮬레이션·회귀·운영 보강 | 6~9명 heuristic bot 회귀와 장애 복구 검증 |
| `WU-B10` | 승인 운영 자료 검색과 근거 중심 관리자 도우미 | pgvector 혼합 검색, 답변·근거·신뢰도 응답, 질문 감사 기록, 자동 변경 차단 |
| `WU-B15` | 15분 사용자 무동작 진행 게임 정리 | 사용자 command와 정리 경쟁을 직렬화하고 `IN_PROGRESS`만 연쇄 삭제하는 migration·worker 검증 |

### 8.3 MCP Server·Data Infrastructure

| WU | 범위 | 완료 기준 |
|---|---|---|
| `WU-M1A` | PostgreSQL·Redis 실행 환경과 계정 준비 | DDL·DML 계정 분리와 health 확인 |
| `WU-M1B` | Backend migration 실행·재실행 | schema version과 최소 권한 검증 |
| `WU-M2` | MCP Streamable HTTP server와 세션 개설 인증 | job별 새 `/mcp` initialize·consume 성공과 재사용 거부 테스트 |
| `WU-M3` | session·capability와 Resource | 5개 schema, subject allowlist와 private context 비간섭성 검증 |
| `WU-M4` | Tool proposal와 Engine adapter | phase·target·동일 proposal replay 거부·재현 테스트 |
| `WU-M5` | MCP 구조화 감사 로그와 redaction | 영속 outbox 없이 허용 metadata만 기록하고 민감한 payload를 기록하지 않음을 검증 |
| `WU-M6` | Backend·MCP 통합 | DB 직접 접근 없이 실제 session 왕복 |
| `WU-M7` | 장애·재접속 검증 | stale capability, Engine 장애, fresh credential reconnect 처리 |
| `WU-M8` | 운영 runbook과 release evidence | 기동·중지·migration·health 절차 재현 |

WU-M5의 MCP 내부 로그 경계는 `mcp_server/mafia_game/ports/audit.py`,
검증·전달 정책은 `core/audit.py`, 독립 검증은
`mcp_server/tests/test_audit_logging.py`와 `test_audit_runtime.py`에 둔다.
기존 initialize·consume·Resource·Engine·teardown 경로에만 먼저 연결하고,
Tool 경로는 WU-M4 계약 정리 뒤 연결한다. 운영 sink와 보존 정책을 결정하지 않은
상태에서는 주입된 sink에만 허용 metadata를 전달하며 기본값은 기록 폐기다.
이 선행 구현은 OPEN-04 해소나 WU-M5 전체 완료를 뜻하지 않는다.

2026-09-09 사용자의 MCP 로깅·재실행 요청은 현재 FastMCP 프로파일의 단일 WU-M5
보완이다. 기존 `main.py`와 `integrations/engine_http.py`에서 HTTP·Backend 콜백을
요청별 UUID와 API 9.4의 허용 필드로 계측하고 stderr에 기록한다. UTC·PID만 표준
process metadata로 추가하며 게임 식별자·payload·header·예외 원문은 기록하지 않는다.
관련 정본과 README를 갱신하고 합성 로그 검증 뒤 실제 테스트 게임으로 관측한다.
Backend·Frontend 코드, DB·공개 API·게임 규칙은 변경하지 않는다.

## 9. 체크포인트

| CP | 선행 조건 | 통과 증거 |
|---|---|---|
| `CP-0` 계약 고정 | 정본 문서 승인 | 링크·용어·schema 예시 일치, 섹터별 자체 fixture 작성 기준 합의 |
| `CP-1` 기반 정리 | F1, B1, M1A | UUID-only 요청과 인프라 health |
| `CP-2` 데이터 | B2, B3, M1B | migration 재실행, transaction·lock 테스트 |
| `CP-3` 게임 엔진 | B4 | 규칙·결정성·불변식 회귀 |
| `CP-4` Agent·MCP | B6, B7, M2~M6 | audience 비간섭성과 fallback E2E |
| `CP-5` 사용자 흐름 | F2~F7, B5 | 생성부터 저장·재개·종료·피드백 E2E |
| `CP-6` 운영 | F8, F10, B8, B9, B10, M7~M8 | 관리자 거부 경로, 발언 분석 partial·redaction, 장애 복구, 근거 검색 경계, runbook |

`WU-M1A -> WU-B2 migration 산출물 -> WU-M1B -> CP-2` 순서를 지킨다. MCP 담당자는
Backend 소유 migration SQL을 수정하지 않는다.

## 10. 검증 전략

- 규칙 엔진은 seed 고정 property test와 6~9명 table-driven test를 작성한다.
- 모든 command는 성공, 잘못된 phase·actor·role·target, deadline 경계, duplicate,
  stale version과 concurrent 제출을 검증한다.
- private projection은 다른 `agent_id`의 역할·알리바이·조사·행동이 응답, SSE와 로그에
  나타나지 않는 비간섭성 테스트를 수행한다.
- polling과 SSE는 client-visible transaction에 연속으로 배정된 `front_sequence`와
  batch 안의 `operation_index`를 사용해 같은 operation을 중복·누락 없이 재구성해야
  한다. 내부·다른 Agent private event의 sequence는 Front에 노출하지 않는다.
- Redis 중단 뒤 PostgreSQL snapshot으로 복구하고 결과를 다시 추첨하지 않는지 확인한다.
- LLM·MCP 자동 테스트는 fake transport와 synthetic context만 사용한다.
- MCP 구조화 로그는 승인된 metadata allowlist만 남기고 Resource·Tool payload,
  capability, token, signature, prompt와 raw model response를 남기지 않는지 캡처 테스트한다.
- 섹터별 단위 테스트는 타 섹터의 실행 프로세스 없이 자체 목데이터·fixture로 수행할
  수 있어야 한다. 이 fixture는 정본 계약을 복제하는 보조 자료이며 별도 공통 산출물로
  강제하지 않는다.
- 밸런스는 인원별 최소 100회, 가능하면 1,000회 heuristic bot simulation으로 먼저
  확인한다. 시민·마피아 목표 승률은 각각 45~55%, 40~60%는 관찰 범위, 60% 초과는
  조정 대상으로 본다.
- 밸런스 변경은 AI 표현 성향 또는 규칙 하나만 한 번에 바꾸고 version을 올린다.

관찰 지표는 진영·인원별 승률, 평균 밤 횟수와 게임 시간, 보호 성공, 탐정 생존과
조사 영향, 마피아 상호 공격·투표, 인간 첫날 밤 사망, deadline 자동 선택 횟수다.
LLM token·비용과 LLM timeout 지표는 MVP 수집 대상이 아니다.

## 11. 환경과 운영

| 프로세스 | 허용 설정 |
|---|---|
| Front | Backend URL, 브라우저 UUID 저장 key 이름 |
| Backend | `DATABASE_URL`, `DATABASE_NAME`, `REDIS_URL`, `GAME_STATE_KEYRING_FILE`, `GAME_STATE_ACTIVE_KEY_ID`, 선택 Provider·model·API key, `MAFIA_MCP_URL`, `MCP_REQUIRE_TLS`, `MCP_TLS_CA_FILE`, `MCP_SERVER_AUTH_SECRET`, `ENGINE_INTERNAL_API_SECRET`, `ADMIN_USER_IDS` |
| migration | `DATABASE_MIGRATION_URL`, `DATABASE_NAME`, DB path 비교용 `TEAM_DATABASE_URL`/`DATABASE_URL` |
| MCP runtime | `MCP_SERVER_AUTH_SECRET`, `ENGINE_INTERNAL_API_SECRET`, `ENGINE_API_URL`, listen·TLS 설정 |

- 실제 비밀값은 문서, 로그와 Git에 넣지 않는다.
- `GAME_STATE_KEYRING_FILE`은 저장소 밖의 권한 제한 파일을 가리킨다. active key와
  저장된 `key_id`의 과거 key를 함께 제공해 재시작 뒤 seed·snapshot을 복호화한다.
- migration 계정은 DDL, Backend 계정은 필요한 DML 최소 권한만 가진다.
- MCP runtime에는 DB·Redis·LLM 자격증명을 주입하지 않는다.
- Front에는 내부 Engine·MCP·DB·Redis·LLM secret을 주입하지 않는다.
- `MCP_REQUIRE_TLS=false`는 loopback 개발에서만 허용한다.
- migration runner가 `DATABASE_MIGRATION_URL`을 직접 읽고 runtime DSN과 분리하는 것은
  `WU-B2` 완료 조건이다. 전환 전 runner의 실제 제한은 README를 따른다.

## 12. 완료 정의

- 정본 문서와 FastAPI `/openapi.json`이 같은 용어·enum·필드를 사용한다.
- 이전 identity/OIDC route와 Front 로그인 코드가 실행 경로에서 제거된다.
- 6~9명 게임이 생성, 시작, 진행, 저장, 재개와 종료까지 결정적으로 동작한다.
- 새로고침·중복 요청·동시 제출로 상태와 RNG 결과가 중복되지 않는다.
- 다른 플레이어의 비공개 정보가 Front·Agent·GM·MCP·로그에 노출되지 않는다.
- PostgreSQL·Redis·Provider·MCP 장애의 정의된 fallback 또는 fail-closed 경로가
  테스트된다.
- README, 환경 예시와 package README가 실제 구현 상태와 정본 문서를 가리킨다.

### WU-B6 최근 대화 입력 보완 (2026-09-08)

실시간 대화 개선 요청의 이번 단일 WU는 Backend의 모델 입력 구성과 관련 합성
테스트다. 기존 `backend/app/agent/orchestrator.py`와
`backend/tests/test_b6_agent_manager.py`, 관련 정본·README 안에서 수행한다.
토론 SPEECH 요청에만 전체 공개 이력에서 발췌한 `dialogue_focus`를 user 데이터로
추가한다. 현재 토론의 최근 발언 6개, 본인을 이름·좌석으로 언급한 타인 발언 후보
6개, 본인의 마지막 발언과 그 뒤 타인의 발언 수를 제공한다. round 0은 GAME_BEGAN,
이후는 현재 round와 일치하는 NIGHT_RESOLVED 이후를 현재 토론으로 구분한다.
경계가 없거나 다르면 발췌만 생략하며 전체 공개·본인 비공개 이력은 보존한다.
동명이인의 이름 단독 언급은 후보에서 제외하고 좌석 호칭으로 구분한다.
이름 언급은 질문·회피·응답 완료 판정이 아니며 의미와 답변 여부는 모델이 원문으로
판단한다. PASS만 늘어난 상황을 새 답변으로 계산하지 않는다. Backend에는 이 파생
입력의 해석 안내만 추가하고 MCP의 역할별 전략·말투 지침 소유권은 유지한다.
모델 출력의 강제 PASS 변환, 새 모델 호출, 공개·MCP Resource schema 변경,
DB·worker·window 변경은 없다. 질문 대상의 발언 우선권과 생성 중 새 발언에 대한
재판단은 별도 후속 WU로 남긴다. 이번 단위는 Orca 검토·테스트 worker와 같은
작업 디렉터리에서 파일 소유 범위를 나누어 수행하며 커밋하지 않는다.

### WU-B6 대화 의미·증거 평가 보완 (2026-09-07)

사용자가 제공한 대화 사례에 따라 기존 orchestrator 프롬프트만 보완한다. 자기 보호 등 구어체 답변 인정, 발언 기회 없는 무응답의 중립 처리, 실제 모순과 정보 부족의 구분, 시민 오처형 뒤 근거 재검토, 사망한 역할 자칭자의 신뢰와 확정 사실 구분을 포함한다. 모델·Provider·API·DB·게임 규칙은 변경하지 않는다.

이번 단일 WU-M3 보완은 사용자가 요청한 운영 FastMCP 모델 입력 축약·게임 규칙 안내 추가다. 기존 Resource 등록 파일에서만 변환하며 상세 계약은 API 명세의 FastMCP 모델 입력 축약 절을 따른다. Backend MCP 소비 클라이언트는 기존·축약 응답을 함께 허용하는 최소 호환 변경을 포함한다. DB·게임 판정은 변경하지 않는다.

이번 WU-B6 프롬프트 보완은 사용자 요청에 따라 진영 승리 우선·인간/AI 동일 증거 평가와 마피아 deception 성향의 런타임 2배 해석(상한 1.0)을 포함한다. 거짓 역할 주장과 의심·투표 유도 강도에 적용하며 DB seed·실제 역할·공개 사실·승패 규칙은 변경하지 않는다. 실제 발언 발생 비율은 모델 선택에 달려 있다.

## 2026-09-08 진행 게임 무동작 정리 (사용자 승인 WU-B15)

이번 단일 WU-B15는 사용자가 승인한 진행 게임 보존 정책 변경이다. 게임 생성과 성공한
공개 사용자 command를 사용자 동작으로 보고 `games.last_user_action_at`에 DB transaction
시각을 저장한다. AI·자동 마감·분석 worker와 읽기 요청은 이 시각을 갱신하지 않는다.
마지막 사용자 동작 후 15분이 지난 `IN_PROGRESS` 게임은 Backend 중앙 worker가 잠근
소량의 행부터 삭제하며 모든 종속 게임 원장은 기존 FK로 함께 삭제한다. 사용자 command가
먼저 행을 잠그면 갱신된 시각을 재확인해 보존하고, 정리가 먼저 확정되면 기존 존재 은닉
계약에 따라 후속 조회·command는 `404 GAME_NOT_FOUND`를 반환한다. `SAVED`, `COMPLETED`,
`FAILED`, 사용자와 관리자 감사 기록은 자동 삭제하지 않는다. 기존 게임은 사용자 command
receipt의 마지막 시각, receipt가 없으면 생성 시각으로 기준을 초기화한다. Front·MCP runtime
코드는 바꾸지 않으며 MCP·Data 담당자는 Backend 소유 순방향 migration 적용만 담당한다.

## 2026-09-08 역할별 프롬프트 이관 (사용자 승인 WU-M6)

이번 단일 WU-M6는 사용자가 승인한 Backend·MCP 프롬프트 소유권 변경과 소비 연결이다.
Backend 메인 system에는 짧은 마피아 공통 규칙만 두고, 역할별 승리 전략·현재 단계의
행동 지침·페르소나 해석은 MCP `api/prompts/instructions.py`에서 관리한다. 기존 운영 Resource
등록부가 검증된 본인 역할·phase로 해당 지침을 선택한다. 성향 수치는 원문 그대로 전달한다.
실제 원문·성향·역할은 Backend가 소유하며 MCP는 DB·Redis·LLM을 직접 호출하지 않는다.
Backend는 MCP 지침과 출력 계약을 developer 메시지, 게임 원문을 user 메시지로 분리한다.
상세 wire 계약은 API 명세의 같은 날짜 절을 따른다. 사용자의 패키지 구조 분리 요청에 따라
`api/prompts/instructions.py`, `api/prompts/registry.py`, `api/resources/registry.py`,
`api/tools/registry.py`를 추가하고 세 API 패키지의 `__init__.py`는 설명만 남긴다.
생성·등록 로직과 import 위치만 옮기며 프롬프트·공개 계약·DB migration 변경은 없다.
gpt-5.6-luna를 유지하고 현재 역할·단계에 무관한 전략과 반복 예문을
제거한다. 실제 모델의 승률·발언 품질 개선은 합성 계약 테스트 결과와 구분한다.

WU-M6 첫날 발언 지침 보완: 첫날 낮(`DAY_DISCUSSION`, `round=0`)에는 정보 부족만으로
PASS하지 않고 짧은 SPEAK를 우선한다. 첫 발언의 새로운 확인 질문·판단 기준과 이후
공개 발언에 대한 의견·후속 질문도 발언할 내용으로 인정한다. 반복·없는 사실 생성은
금지하며 새로 보탤 내용이 없으면 PASS할 수 있다. MCP가 이 조건부 지침을 소유하고,
Backend의 대화 발췌 안내는 같은 PASS 기준을 따르도록 문구만 맞춘다. 기존 파일에서
프롬프트만 수정하며 API·DB·게임 규칙·장애 fallback은 유지한다.

### WU-M6 MCP 실패 PASS 조사·진단 보완 (2026-09-08)

사용자의 이슈 해결 요청에 따라 기존 Backend·MCP 소비 연결에서 오류 발생 경계를
확인한다. Backend의 MCP 연결·timeout·HTTP·RPC·응답 계약 실패와 MCP의 Backend
HTTP 실패를 고정 코드로 구분한다. 내부 진단에는 scope·상태 코드와 기존 작업 식별자만
남기며 URL·자격증명·응답 본문·예외 원문은 기록하지 않는다. 기존 공개
`MCP_UNAVAILABLE` 및 결정적 fallback·fencing 계약은 유지한다. 같은 actor·게임의
응답이 새 phase·window·버전으로 진행한 경우는 `STALE`로 폐기하며
실행되지 않을 PASS proposal·FALLBACK 기록을 만들지 않는다. 다른 PC의 테스트는
사용자 요청에 따라 이번 수정·검증 범위에서 제외한다. Backend와 MCP 양쪽
계약 검증을 통과한 조합으로 재기동·왕복 확인하며, 공유 DB의 다른 실행 인스턴스는
로컬 검증과 구분한다. 기존 파일 안에서 구현하고 합성 장애·정상 왕복과 회귀로 확인한다.

후속 실제 게임 검증은 사용자가 명시한 테스트용 팀 DB에서 진행한다. 실제 `.env`의
로컬 DB URL을 제거하고 `run_openai.sh`의 기본 모드를 `team`으로 변경한다.
DB 조사·실행·통합 검증의 팀 DB 우선 원칙은 AGENTS.MD를 따른다. 기존 명시적
`isolated` 선택 기능은 유지하되 자동으로 로컬 DB를 생성하거나 선택하지 않는다.
이번 실게임은 기존 OpenAI 설정으로 생성하고 첫날 발언·PASS·오류와 이후 phase 진행을
기록한다. 공유 DB의 다른 worker가 확정한 결과는 이 PC의 실행 로그와 구분한다.

### WU-M6 공통 성향 변환 제거와 후속 계획 (2026-09-08)

이번 사용자 요청의 구현 범위는 기존 `api/prompts/instructions.py`에서 8개 성향의
3단계 문구 선택과 deception 2배 보정을 제거하고 관련 기존 테스트·정본·README를
맞추는 것까지다. 이 절이 앞선 수치 변환·증폭 설명보다 우선한다. DB에 배정된
`speech_style`, `backstory`, `parameters`를 따르라는 공통 안내와 정보 권한 경계,
첫날 발언 우선 지침은 유지한다. MCP는 DB를 직접 읽지 않고 기존 Backend 응답의
persona 원문을 그대로 전달한다. 운영 DB·배정 로직·API schema·파일 구조는 바꾸지 않는다.

team DB 읽기 확인: 활성 6개 중 새 게임 버전 `agent-config-v1`에 맞는 것은 분석가·
토론가·기록자·반응가·조정자 5개다. `BALANCED_OBSERVER`는 `mystery-v1`이므로 새 게임
후보에서 제외된다. 현재 `.env`의 저장소 선택은 team이다. team의 수치는 5.3절에
기록한 로컬 보강값과 다르며, 예를 들어 분석가의 주장/기억은 0.35/0.85,
토론가의 주장/기억은 0.85/0.55다. seed 파일 수정만으로 team DB 값이 바뀌지는 않는다.

후속 작업은 아래 순서로 각각 별도 WU에서 구체화하며 이번에는 계획만 기록한다.

1. **WU-B6 페르소나 콘텐츠 정비:** 5개 preset의 기존 `speech_style`·`backstory`에
   첫 질문, 답변, 반론 방식의 차이를 명시하고 team 수치와 로컬 보강값 중 목표값을
   결정한다. DB의 정확한 수치와 문장을 기준으로 하며 공통 코드에 유형별 문구표를
   다시 만들지 않는다. 기존 필드 길이는 유지하며 추론 수치는 아래 승인된 변경을 따른다.
2. **WU-B6 배정·버전 정비:** 현재 AI 5명은 5종을 하나씩 받지만 AI 6~8명은 modulo로
   재사용한다. 전원 다른 성격이 목표라면 활성 preset을 최소 8종으로 늘리고 새 게임의
   무중복 배정을 검증한다. 기존 게임은 배정 ID로 매번 활성 preset을 다시 읽으므로
   행의 version·active를 덮어쓰면 저장 게임도 영향을 받는다. `id` 단독 PK를 고려해
   신규 ID·새 config version으로 이전 preset과 공존하는 방식을 우선 설계한다.
3. **WU-M1B 데이터 반영:** Backend가 정한 persona 변경분만 적용하는 migration·
   content_hash·검증·복구 절차를 준비한다. 시나리오도 덮어쓰는 기존 004 seed 전체를
   team DB에 그대로 재실행하지 않는다. Backend는 데이터 변경을, MCP/Data는 실행과
   health 확인을 담당하며 기존 게임 재개와 새 게임 후보를 각각 확인한다.
4. **WU-M6 전달·품질 비교:** 같은 공개 상황에서 성격·역할별 원문 전달과 단계 구분을
   합성 테스트로 확인한다. 이후 실제 모델 비교가 필요하면 첫날 자발적 PASS율,
   반복 질문, 성격 구별 정도, 근거 날조를 함께 측정한다. 오류 fallback PASS는 별도
   집계하고 단순 PASS율 감소를 대화 품질 개선으로 단정하지 않는다.

### WU-B6 페르소나 추론 수치 조정 (2026-09-08)

사용자의 0.6~0.8 요청에 따라 team DB의 등록 6개 preset을 아래 값으로 갱신한다.
이 절은 앞선 전원 0.5·동일 추론 성향 제약보다 우선한다. Backend projection은 다른
성향과 같은 유한 0~1 검증을 적용해 기존 0.5와 새 값을 모두 허용하고, 원문 전달·
권한 경계·모델 effort는 유지한다. 기존 004 seed는 수정하지 않고 새
`backend/migrations/009_update_persona_reasoning_skill.sql`로 해당 ID·version의
`parameters.reasoning_skill`과 `content_hash`만 갱신한다. 다른 수치·말투·활성 상태·
버전·게임 배정은 보존한다. 같은 ID를 쓰는 기존 게임도 다음 persona 조회에 새 값을 받는다.
Backend 검증 배포를 먼저 확인한 뒤 team에 DML만 적용한다. 관련 거부·허용 경로,
격리 QA의 migration 재실행·원문 보존 및 전체 Backend·MCP 회귀를 검증한다.

| preset | version | reasoning_skill |
|---|---|---:|
| CAUTIOUS_ANALYST | agent-config-v1 | 0.80 |
| OBSERVANT_NOTEKEEPER | agent-config-v1 | 0.80 |
| ACTIVE_DEBATER | agent-config-v1 | 0.75 |
| COOPERATIVE_MEDIATOR | agent-config-v1 | 0.70 |
| BALANCED_OBSERVER | mystery-v1 | 0.70 |
| EMOTIONAL_REACTOR | agent-config-v1 | 0.60 |

## 2026-09-07 자유 토론 변경 (사용자 승인 WU-B4)

이번 단일 WU-B4는 1분 45초 자유 토론과 연결되는 Front·MCP 표현의 변경이다. 이 절이 기존 좌석당 한 번 발언·전원 PASS 추가 순환 규칙보다 우선한다. 새 일반·최종 토론은 Backend deadline 105초까지 열리며 인간은 AI 처리 순서와 무관하게 발언한다. 플레이어별 최근 60초 SPEAK는 최대 7회이며 서버 게임 행 잠금 안에서 원장으로 검증한다. PASS는 조기 마감하지 않는다. AI 작업은 기존 단일 예약 창을 재사용해 공정하게 배분하고, 발언마다 새 window를 열되 토론 deadline은 보존한다. turn_player_id는 AI 스케줄링 힌트이며 인간의 발언 권한 제한이 아니다. SPEECH에도 deadline·remaining_ms가 제공된다. 저장 시 잔여 시간을 보존한다. 마감 뒤 첫날은 밤, 이후 낮은 투표, 최종 토론은 최종 지목으로 진행한다. 과거 deadline 없는 발언 창은 기존 방식으로 처리한다. DB 구조와 idempotency·게임 상태 버전 검증은 보존한다.

WU-B6 말투 보완: 사용자 요청에 따라 AI 발언은 반말을 허용한 자연스러운 게임 채팅 구어체로 작성한다. 페르소나의 격식보다 구어체를 우선하고, 과도한 논리 보고·검증 용어·상황 요약을 줄인다. 실제 근거 판단과 진영 승리 우선순위는 유지한다.

## 투표 보조 정보 확장 계획 (2026-09-07)

**상태: 계획 원안과 후속 구현 결정을 함께 기록.** 최초 계획 작성 뒤 사용자가
구현을 승인했으며 실제 착수 범위·조정은 아래 8절과 영역별 정본을 따른다.
1~7절의 테이블·필드 후보와 품질 목표를 구현 완료 사실로 간주하지 않는다.
검증된 현재 범위와 운영 활성화 절차는 루트 README를 따른다.

### 목적과 현재 연결 지점

확정된 AI 공개 발언 전부를 임베딩해 저장하고, 투표 시점에 사용자가 발언의
공통점과 의심의 흐름을 빠르게 확인하게 한다. 모든 정보에 원문 근거를 연결하며
마피아 확률, 진실 판정, 자동 투표 추천은 제공하지 않는다.

- AI 발언은 `backend/app/services/game/agent_discussion.py`에서 공통
  `discussion_transaction.py`로 제출되고 `game_events`에 저장된다.
- `event_repository.py`와 `game_read_service.py`는 확정된 공개 이력을 읽고
  `PLAYER_SPOKE`를 `player_id`, `message`로 제한한다. 이 공개 projection을
  분석 입력 경계로 재사용한다. Redis 공개 대화 캐시는 영구 원본이 아니다.
- `backend/app/services/admin_knowledge.py`의 기존 임베딩은 의미 학습 모델이
  아닌 64차원 토큰 해싱이다. 관리자 승인 지식 테이블에 게임 발언을 섞지 않는다.
- `frontend_user/components/action_panel.py`의 `_render_vote_summary`는 현재
  최근 밤 결과를 안내한다. 이 영역을 확장하되 후보 선택·제출·타이머를 우선한다.

### 1. 사용자에게 제공할 정보

| 우선순위 | 카드 | 계산·표시 기준 | 합성 예시 |
|---|---|---|---|
| MVP | 유사한 주장을 한 플레이어 | 서로 다른 AI의 발언에서 대상·입장·핵심 주장까지 일치한 묶음과 원문 | “2번·5번이 3번의 알리바이를 의심했어요.” |
| MVP | 가장 많이 의심 대상으로 지목된 플레이어 | 명시적 의심·처형 지지의 고유 AI 발언자 수를 우선 집계 | “3번: AI 3명이 의심 대상으로 지목, 관련 발언 5개” |
| MVP | 후보별 근거 발언 | 해당 후보에 대한 의심·옹호·질문 원문을 분리하고 시점 표시 | “3번 관련 의심 3명 / 옹호 1명 · 원문 보기” |
| 후속 | 입장 변화 | 동일 발언자의 같은 대상·논점에 대한 시간순 입장 변화 | “2번이 3번을 옹호한 뒤 의심으로 바꿨어요.” |

MVP 기본 분석 범위는 **현재 토론 구간의 AI 공개 발언**이다. 일반 투표·재투표는
직전 낮 토론, 최종 지목은 최종 토론을 사용한다. 사용자는 **게임 전체 누적**으로
전환할 수 있다. 첫날도 전부 색인해 이후 누적 조회에 포함한다. 인간 발언까지의
확장은 별도 후속 범위이며 화면에 “AI 발언 기준”을 항상 표시한다.

모든 AI 플레이어의 정상·대체 처리로 확정된 `PLAYER_SPOKE`를 포함한다. 원문이
없는 PASS, GM 안내, 거부된 응답, 미확정 LLM 출력, 내부 사고·밤 비공개 대화는
대상이 아니다. 사망자의 과거 발언은 보존하고 생존 여부를 표시한다. 투표 후보
카드는 서버가 허용한 현재 후보만 보여주며, 사망자 관련 과거 주장은 기록에서만
볼 수 있게 한다. 재투표는 같은 근거 집합을 재사용하고 동률 후보로 좁힌다.

### 2. 임베딩과 구조화 분석을 분리

1. **전문 임베딩:** 최대 200자의 발언은 잘라 버리지 않고 한 발언당 하나의 벡터로
   저장한다. 발언이 반복돼도 각각의 event 연결을 보존한다. 한국어 구어체용 모델은
   합성 평가 자료로 선정하며 Provider·모델 revision·차원을 고정한다. 현재 계획에서
   특정 유료 모델이나 신규 API 사용은 확정하지 않는다.
2. **주장 추출:** 공개 원문과 같은 게임의 공개 좌석·이름 대응표만 전달하는 별도
   분석기로 `target_player_id`, `stance`(의심·옹호·질문·중립), 핵심 주장,
   원문의 시작·끝 위치를 추출한다. 여러 주장은 각각 보존한다. 대명사 해소에는
   같은 게임의 이전 공개 발언만 제한적으로 사용하고 해당 문맥 event도 근거로
   연결한다. 대상을 확정할 수 없으면 미상으로 남겨 순위에서 제외한다.
3. **유사 후보 검색:** 같은 game·분석 구간·모델의 벡터에 대해 cosine 유사도로
   후보를 찾는다. 같은 화자끼리는 사용자용 유사 주장 묶음에서 제외한다.
4. **의미 확인:** 대상·찬반·핵심 주장과 근거 원문을 다시 비교한다. “3번이 마피아다”와
   “3번은 마피아가 아니다”는 유사도가 높아도 같은 주장으로 묶지 않는다. 애매한
   경우 카드 생성을 보류한다. A↔B, B↔C만 비슷한 경우 A·B·C 전체가 일치한다고
   표시하지 않고 묶음 내 모든 쌍을 확인하거나 쌍 단위로 보여준다.
5. **지목 집계:** 임베딩 점수가 아니라 추출된 의심·처형 지지 관계를 집계한다.
   단순 언급, 질문, 옹호, 타인의 주장을 인용한 문장은 의심 수에 포함하지 않는다.
   인용에 본인이 동의한 경우에만 해당 발언자의 의심으로 센다.

`고유 지목자 수 = 범위 안에서 해당 대상을 명시적으로 의심한 서로 다른 AI 수`,
`관련 발언 수 = 해당 의심 관계를 포함하는 서로 다른 event 수`로 정의한다.
같은 발언의 동일 대상 반복은 한 번만 센다. 한 AI가 7번 반복해도 지목자는 1명이다.
고유 지목자 수가 같으면 공동 순위를 표시하고 좌석순으로 정렬한다. 과거 의심 후
철회한 발언도 “기간 중 지목 이력”에는 남으므로, 현재 투표 의향으로 표현하지 않는다.

유사도는 진실성·마피아 확률이나 모델 confidence가 아니다. MVP 화면에는 점수 대신
근거를 제공한다. 검증되지 않은 고정 threshold로 동일 주장을 확정하지 않고,
한국어 부정·반어·인용·동명이름·좌석 번호·다중 주장 사례로 기준을 조정한다.

### 3. 처리 흐름과 장애 복구

`발언 transaction 확정 → 공개 발언 탐색 → 비동기 임베딩·주장 추출 → 파생 결과 저장
→ 투표 window별 근거 범위 확정 → 조회 API → 투표 보조 카드`

- 토론 중부터 처리한다. 게임 transaction이나 행 잠금을 유지한 채 모델을 호출하지
  않는다. 분석 worker는 AI 발언·투표 worker와 별도 실행·동시성 한도를 사용한다.
- 최초 MVP는 확정된 공개 event와 처리 원장을 비교하는 DB polling으로 누락을 찾는다.
  기존 `event_outbox` publisher나 Redis 알림을 필수 의존성으로 만들지 않는다.
  commit 직후 프로세스가 죽어도 재탐색할 수 있어야 한다.
- `(game_id, event_id, analysis_version)`를 처리 단위로 삼는다. 짧은 DB transaction에서
  작업을 선점하고, 호출은 밖에서 수행한 뒤 소유 토큰·원문 hash·분석 버전을 확인해
  결과를 저장한다. 선점 만료 후 재시도할 수 있지만 늦은 이전 응답은 덮어쓰지 못한다.
  이 상태는 게임 Agent의 기존 job·lease 계약과 분리된 파생 분석 전용이다.
- 투표를 여는 transaction에서 분석 대상의 마지막 확정 event sequence를 고정한다.
  카드 계산은 그 상한 이내만 읽는다. 분석 완료로 게임 `state_version`, 공개 cursor,
  deadline 또는 투표 원장을 변경하지 않는다.
- 최신 이벤트 일부가 실패했다고 그 뒤 성공한 이벤트를 누락하지 않는다. event별 처리
  상태와 범위 내 전체/완료/실패 수로 완전성을 계산하며 최고 sequence만으로 완료를
  판정하지 않는다. 임베딩과 주장 추출의 완료 상태도 각각 유지한다.
- 장애에는 제한된 재시도·재기동 복구를 적용하고 실패를 영구적으로 숨기지 않는다.
  저장·재개는 확정된 발언의 분석을 보존하고 복원된 window에 연결한다. 과거 게임의
  backfill은 선택한 게임만 대상으로 같은 멱등 경로를 사용하며 원장을 수정하지 않는다.

### 4. 저장 구조 제안과 책임

Backend가 전용 파생 테이블·repository·migration을 소유한다. 다음은 논리 구조
후보이며 정확한 SQL·FK·nullable·인덱스는 WU-B11에서 DB 정본으로 확정한다.

| 논리 테이블 후보 | 저장 내용·주요 제약 |
|---|---|
| `speech_analysis` | game·원본 event·AI player, 원본 sequence·토론 구간, content hash, 분석 버전, 단계별 상태·시도 수·다음 재시도·선점 정보, 안전한 오류 코드. event·player는 같은 game의 FK로 제한 |
| `speech_embeddings` | 분석 ID, 모델·revision·차원, 전문 vector. 동일 분석·모델 중복 저장 방지, 유한 수·정확한 차원·0벡터 거부 |
| `speech_claims` | 분석 ID·주장 순번, 대상·입장·핵심 주장·근거 구간·문맥 event ID. 대상은 같은 game만 허용하고 원문 substring 검증 |
| `vote_insight_snapshots` | game·window·범위·cutoff·분석 버전별 카드, 카드 revision, 단계별 처리 수·생성 시각. 같은 입력은 동일 집계 결과 |

원문은 `game_events`에 그대로 남기고 파생 테이블은 참조·필요한 근거 위치를 저장한다.
round·토론 구간은 당시 확정 이벤트/행동 창 관계에서 복원하며 처리 시점의 현재
round를 과거 발언에 붙이지 않는다. 벡터와 추출 정보도 동일 게임 접근 경계를 적용한다.
모델 교체는 새 버전으로 병행 색인한 뒤 전환하며 차원이 다른 벡터를 비교하지 않는다.
삭제·보존 정책은 원본 게임 정책을 따르도록 DB 정본에서 확정하고 파생 데이터가
삭제된 원문을 계속 노출하지 않게 한다. 새로운 원본 삭제 기능은 이번 범위가 아니다.

저장소에는 관리자용 pgvector migration이 있지만 실제 배포 DB 설치·권한은 별도로
확인한다. MCP·Data 담당자가 Backend migration을 실행하고 extension·권한·health를
검증한다. MCP runtime은 DB에 접근하지 않으며 새 Resource도 MVP에는 추가하지 않는다.
게임별 발언 수가 작으므로 먼저 game·구간 B-tree 필터와 정확 검색으로 측정하고,
HNSW 도입은 실제 성능 측정 후 결정한다. Redis 결과 캐시는 MVP 필수 범위에서 제외한다.

### 5. 조회 API와 화면 제안

조회 후보는 `GET /api/v1/games/{game_id}/vote-insights?window_id=...&scope=current_discussion|game`다.
읽기 요청은 저장된 결과만 조회하고 모델 호출·색인 작업을 시작하지 않는다. API 정본에
다음 내용을 확정한 뒤 구현한다.

- 기존 `X-User-Id` 게임 소유권 검사와 공개 projection 검증을 그대로 적용한다.
  강한 인증으로 간주하지 않으며 임의 event ID로 다른 게임 근거를 조회할 수 없게 한다.
- 응답은 game·window·scope·cutoff, 분석 버전·카드 revision·생성 시각,
  `PENDING/PARTIAL/READY/UNAVAILABLE`, 대상 발언 수·단계별 완료/실패 수,
  유사 주장·지목 순위·후보별 근거로 구성한다. 빈 범위는 `READY`와 0건으로 구분한다.
- 근거에는 공개 event ID·AI player ID·원문·시점만 포함한다. 벡터, private context,
  실제 직업, 미해소 투표·밤 행동, 모델 내부 출력은 반환하지 않는다. “탐정이라고
  발언함”은 공개 주장으로만 표시하고 DB 역할을 조회해 확인하지 않는다.
- 현재 phase/window 불일치·종료된 window의 요청은 명시적 stale 오류로 거부하고
  Front는 snapshot을 다시 읽는다. 저장 상태에서는 카드를 비활성화하고 재개 후
  window를 다시 확인한다. 보조 API 오류는 기존 게임 API의 성공 여부와 분리한다.
- 카드별 최대 개수와 원문 근거 pagination·다음 cursor를 정본에 확정한다. 화면에서
  일부만 펼쳐도 집계는 범위 전체를 사용하고 총건수와 구분한다.

투표 영역에 “AI 발언 돌아보기”를 접을 수 있는 보조 패널로 둔다. 기본은 지목 순위와
유사 주장 각 최대 3개, 후보 선택 시 의심·옹호·질문 근거를 보여준다. 원문을 누르면
타임라인의 해당 발언으로 이동한다. 카드에는 “공개 발언을 분석한 참고 정보이며
사실 판정이 아닙니다”와 범위·분석 완료 수를 표시한다. 부분 결과의 순위는
“분석된 발언 기준”으로 표시하고 완성된 전체 순위처럼 표현하지 않는다.

Front는 투표 진입 시 조회하고 `PENDING/PARTIAL` 동안만 기존 갱신 주기에 맞춰
재조회한다. 다른 window의 늦은 응답은 버린다. 선택한 후보·입력 상태는 갱신해도
보존한다. 장애 시 “발언 분석을 사용할 수 없어요”와 기존 타임라인을 제공한다.
투표 마감·자동 선택·미해소 표의 비공개 경계는 유지한다.

### 6. 세션별 구현 순서와 완료 기준

아래 WU-B11~B14·WU-M9·WU-F9는 이 확장에 예약하는 신규 작업 단위 제안이다.
WU-B11 착수 전에 Front·Backend·MCP/Data가 제공 범위·모델 선정 기준·예상 신규
파일과 비용 운영 기준을 합의한다. 파일은 기존 `backend/app`, `backend/migrations`,
`backend/tests`, `frontend_user` 구조 안에서 최소한으로 추가하고 구체 경로를 정본과
README에 먼저 반영한다. 신규 디렉터리나 migration 번호를 현재 단계에서 확정하지 않는다.

| 순서·WU | 담당·범위 | 선행조건·완료 기준 |
|---|---|---|
| 1 · WU-B11 | Backend: DB/API/화면 정본 상세화, 전용 migration·repository | 섹터 합의 후 저장 계약·권한·복합 FK·멱등성·버전 분리 테스트 및 격리 DB migration 검증 |
| 2 · WU-M9 | MCP/Data: 대상 DB extension·계정 확인과 migration 실행 | B11 산출물 인수, 기동·재실행·최소 권한·health 증거, MCP runtime 변경 없음 |
| 3 · WU-B12 | Backend: 공개 발언 탐색·비동기 임베딩/주장 추출·복구 | B11, 운영 연결 전 M9. fake Provider로 중복·누락·재시작·timeout·지연 응답·다른 게임 혼입 거부 검증 |
| 4 · WU-B13 | Backend: 유사 주장·지목 집계·window별 조회 API | B12. cutoff 고정·소유권·private 비간섭성·부분 결과·stale window 계약 통과 |
| 5 · WU-F9 | Front: 보조 카드·원문 연결·후보별 근거 | B13 계약. 합성 응답으로 loading·empty·partial·error·재투표·최종 지목·저장/재개·타이머/선택 보존 검증 |
| 6 · WU-B14 | Backend 주관: 품질 평가·통합·운영 조정 | F9 연결 완료. 데이터량·지연·재시도·재기동 회복 측정, 기본 비활성 기능 설정에서 단계적 활성화 |

각 세션의 구현은 해당 WU 한 개로 제한한다. 데이터 migration·공개 API·동시성·정보
격리 작업은 실패·거부 경로 테스트를 먼저 또는 함께 작성하고 완료 시 전체 회귀를
1회 수행한다. 유료 API 통합은 기본 테스트에서 fake로 대체한다. 기존 무관한 실패는
별도로 보고하며 기능 구현 완료로 숨기지 않는다.

### 7. 품질·성능·출시 판단 기준

- 한국어 합성 발언 최소 100개와 주장 쌍 최소 50개를 수작업으로 라벨링하고,
  threshold 조정용과 최종 평가용을 분리한다. 부정·인용·철회·별칭·여러 대상·반복을
  포함한다. 의심 대상 추출 및 유사 주장 정밀도 90% 이상을 초기 목표로 두고,
  재현율·보류율도 함께 보고해 모든 결과를 숨기는 방식으로 목표를 맞추지 않는다.
- 반대 입장을 같은 주장으로 묶는 지정 반례, 다른 게임·private 필드 유출은 평가에서
  0건이어야 한다. 동일 AI 반복 지목·재처리·재투표로 고유 지목자 수가 증가하면 실패다.
- 전체 AI 공개 발언은 처리 원장에 빠짐없이 등록한다. 정상 Provider·부하 조건에서는
  모두 임베딩 완료되어야 하며 실패분은 수·원인 코드·재처리 상태를 확인할 수 있어야 한다.
- 초기 성능 목표는 저장된 보조 정보 조회 p95 300ms 이내, 정상 조건에서 투표 준비 시작 후
  분석 완료 p95 5초 이내다. 보장 수치가 아니라 B14에서 측정할 목표이며 투표 시점의
  처리율도 함께 기록한다. 9인·최대 밤 수·자유 토론 발언 제한에 맞춘 합성 부하로 검증한다.
- 모델 비용·차원·라이선스/외부 전송 조건·한국어 품질을 비교한 후 모델을 확정한다.
  분석 전용 동시성·batch·timeout·재시도 상한과 비활성 설정을 정하고, 발언·투표
  Provider 자원을 고갈시키지 않는지 측정한다. 새 환경 변수는 README에 문서화한다.
- 장애 주입 시 분석이 멈춰도 발언 저장·투표 제출·마감·저장/재개가 진행되어야 한다.
  출시 중단은 분석 기능을 비활성화하는 방식으로 하고 원본 발언·게임 원장은 보존한다.

**계획상 첫 구현 작업자의 범위는 WU-B11만**이다. 인간 발언 포함, AI의 투표 판단에 분석 결과
재주입, 모순 자동 판정·플레이어 관계 그래프는 MVP 결과를 확인한 뒤 별도로 계획한다.

### 8. 구현 착수 결정 (2026-09-07)

사용자는 계획 구현과 Orca orchestration, 기존 OpenAI 키 재사용을 승인했다.
coordinator는 WU-B14 통합·검증을 맡고 각 구현 작업자는 하나의 WU만 맡는다.
WU-B11 저장 계약, WU-B12 분석, WU-B13 조회, WU-F9 화면, WU-M9 환경 검증을
서로 다른 작업자 세션으로 수행한다. 현재 작업 트리에서 파일 소유권을 분리한다.
프론트엔드는 이후 디자인 전면 교체를 고려해 접이식 텍스트와 API adapter만 추가한다.

현재 DB의 pgvector 미지원 기록을 고려하여 `006_create_speech_analysis.sql`은
표준 PostgreSQL `double precision[]`에 실제 의미 임베딩을 저장한다. 게임별 정확
cosine 비교를 사용하며 토큰 해싱으로 대체하지 않는다. 관리자용 005 migration은
이 기능의 선행조건이 아니다. 기존 migration은 수정하지 않고 006만 독립 적용 가능하게 한다.
MVP는 분석·임베딩·주장을 `speech_analysis`에 통합한다. `speech_analysis_versions`는
버전별 최초 활성 시점을 보존해 아직 분석 행이 없는 게임이 먼저 종료되어도 누락분을
발견하게 한다. 각 단계의 상태,
재시도·선점 토큰, 모델·차원·버전과 원본 참조를 유지한다. 공개 event 원장에 저장된
window 개설 sequence를 cutoff로 재사용하여 별도 window snapshot 테이블·게임
transaction 변경을 최초 구현에서는 생략한다. 후속 B14의 투표 대기는 기존 마감된
SPEECH window로 표현하고 별도 테이블은 추가하지 않는다. 조회는 저장된 분석 결과로 결정적 카드를 조합하며
외부 모델 호출·색인·DB 쓰기를 하지 않는다. 낮은 부하의 MVP 경계이며 향후 측정 후
물리 테이블 분리·pgvector 인덱스·카드 materialization을 결정한다.

신규 파일 소유권은 다음과 같다. 기존 디렉터리만 사용하고 각 WU의 전용 테스트를
같은 테스트 디렉터리에 추가한다. root README는 coordinator가 통합 갱신한다.

| WU | 신규 파일과 기존 변경 경계 |
|---|---|
| B11 | `backend/migrations/006_create_speech_analysis.sql`, `backend/app/repositories/speech_analysis_repository.py`, `backend/tests/test_speech_analysis_repository.py`; DB 정본 |
| B12 | `backend/app/services/game/speech_analysis_worker.py`, `backend/app/llm_provider/speech_analysis_provider.py`, `backend/tests/test_speech_analysis_worker.py`, `backend/tests/test_speech_analysis_provider.py`; `core/config.py`, `main.py`, `.env.example` |
| B13 | `backend/app/repositories/vote_insight_repository.py`, `backend/app/services/game/vote_insight_service.py`, `backend/tests/test_vote_insights.py`; `routers/game_router.py`, API 정본 |
| F9 | `frontend_user/components/vote_insights.py`, `frontend_user/tests/test_vote_insights_f9.py`; 기존 API client·action panel, 화면 정본 |
| F10 | `backend/app/repositories/admin_repository.py`, `backend/app/services/admin_service.py`, `backend/app/routers/admin_router.py`, `backend/app/schemas/admin_schema.py`, `backend/tests/test_b8_admin_api.py`, `frontend_admin/core/api_client.py`, `frontend_admin/app.py`, `frontend_admin/app_pages/dashboard_page.py`; `speech_analysis` 기반 관리자 조회·도식화와 관련 계약·README |
| M9 | 격리 DB에서 006 적용·재실행·권한·health 확인, 실제 서비스 DB 변경은 대상 확인 후 수행 |
| B14 | 위 계약 간 연결 확인·필요한 통합 수정·회귀, 기존 `runtime_factory.py`·`main.py`에서 조회 서비스 조립, `backend/tests/test_vote_insight_integration.py`·기존 migration 목록 검사, 새 테스트 추적용 `.gitignore`, `README.md`, 기존 정본의 실제 결과·제약 갱신 |

기본 기능 설정은 비활성이고 `SPEECH_ANALYSIS_ENABLED=true`로 활성화한다.
임베딩 기본 모델은 `text-embedding-3-small`, 차원은 1536으로 고정하고 주장 분석은
별도 구조화 OpenAI 요청으로 처리한다. 모델 계약은
[OpenAI 임베딩 공식 문서](https://developers.openai.com/api/docs/guides/embeddings#how-to-get-embeddings)를 확인했다.
게임 Agent의 private context·추론은 재사용하지 않는다. 비용이 발생하는 실호출을
자동 회귀에 넣지 않으며 기존 사용자 키·실제 env 파일은 수정하거나 출력하지 않는다.

후속 활성화 요청에 따라 기존 `run_openai.sh`의 `AI_MAFIA_DATABASE_URL` 대상인
로컬 `127.0.0.1:55432/mafia_qa`에 M9가 006과 runtime 권한을 적용한다.
B14는 Git 제외 `.env`의 `SPEECH_ANALYSIS_*` 설정과 기존 실행 스크립트 기동을
완료한다. OpenAI 키는 기존 승인대로 재사용하고 값은 변경·출력하지 않는다.
활성화 smoke에서 한국어 인용문은 맞지만 모델의 문자 offset이 틀린 사례가 재현됐다.
후속 B12는 Provider 응답 수신부에서 원문에 정확히 한 번 존재하는 인용문에 한해
offset을 재계산하고 기존 엄격 validator를 거치도록 보완한다. 존재하지 않는 인용과
위치가 모호한 반복 인용은 거부하며 DB에 저장하는 원문·span 계약은 바꾸지 않는다.

후속 활성화 결과: 로컬 006 적용 전후 기존 게임 19개와 원장·권한을 보존했고 기존
QA owner 계정을 재사용했다. 이 로컬 환경의 runtime/DDL 최소 권한 분리는 미적용이다.
기존 실행 스크립트로 세 서버를 기동했으며, 최초 대상 공개 발언 30개의 임베딩·주장
READY 저장과 실제 모델 smoke를 확인했다. 인용 위치 보완 후 Backend 전체 회귀는
751 통과·기존 14 실패·8 건너뜀이며 자세한 환경·검증 기록은 README를 따른다.

후속 원격 이전 요청에서는 M9가 `TEAM_DATABASE_URL`의 `4team_db`에 006을 적용하고
권한·원장 보존을 확인한다. B14는 기존 실행 스크립트에 명시적
`AI_MAFIA_STORAGE_MODE=team` 선택을 추가해 Backend의 DB·Redis 실행 연결을
팀 설정으로 전환한다. 이후 팀 DB 우선 요청으로 기본값을 `team`으로 변경했으며,
명시적 `isolated` 선택의 공유 DB 중복 사용 방지 검사는 유지한다.
로컬 게임 원장과 분석 행을 원격으로 복제하는 작업은 포함하지 않는다.

원격 적용 결과: 006 적용 전후 기존 23개 테이블의 데이터·ACL·owner를 보존했다.
명시적 team 모드로 재기동한 Backend가 원격 분석 버전을 등록하고 공개 발언 2개를
임베딩·주장 READY로 저장했다. 서버 health·MCP 초기화 및 설정 선택 8건이 통과했고,
격리 QA의 Backend 전체 회귀는 751 통과·기존 14 실패·8 건너뜀이다.

#### WU-B12 분석 실행 계약

전용 Provider는 공식 `AsyncOpenAI`의 재시도를 0으로 고정한다. 임베딩 요청은
`text-embedding-3-small`, `dimensions=1536`, `encoding_format=float`로 원문 전문을
전달한다. 주장 분석은 별도 `gpt-4.1-mini` Responses 구조화 요청이며 `store=False`와
명시적 timeout을 사용한다. 입력에는 원문과 같은 게임의 공개 player ID·좌석·이름만
포함하고 숨은 직업·내부 사고·원장 전체를 전달하지 않는다. 반환 주장은 폐쇄형
`target_player_id`(nullable), `stance`(`SUSPICION|DEFENSE|QUESTION|NEUTRAL`),
`proposition`, `evidence_start`, `evidence_end`, `quote`로 검증한다. 대상 미확정은 null,
부정·인용·단순 언급은 의심으로 자동 승격하지 않으며 근거는 Python 문자 기준
반개구간 `[start,end)`의 실제 원문과 일치해야 한다. Provider 응답 경계에서 정수
오프셋만 잘못된 경우 비어 있지 않은 정확 인용이 원문에 유일하게 존재할 때만 위치를
재계산한다. 정확한 기존 span은 반복 인용이어도 유지하며, 불일치 span의 반복·겹침
출현, 허구·비문자열 인용, boolean 등 비정수 offset은 거부한다. 정규화 후 기존
`validate_claims`로 schema·대상·입장·근거를 엄격 검증하고 DB 계약은 유지한다.
파서 변경을 분석 버전에 반영하여 `PROMPT_VERSION=claims-ko-v2`로 구분한다.
모델 자유 출력·예외 원문은 기록하지 않는다.

설정은 `SPEECH_ANALYSIS_ENABLED=false`, 임베딩 모델·차원, 주장 모델, 분석 버전,
polling 주기·batch·concurrency·timeout·max attempts를 독립 검증한다. 유효 분석 버전은
운영 revision과 두 모델·차원·프롬프트 revision을 함께 포함하여 서로 다른 분석을 섞지 않는다.
worker는 앱별로 생성하며 AI worker와 별도로 시작·중지한다. 테스트의
`enable_background_worker=False`는 분석 worker도 시작하지 않는다. DB 작업은 짧은
repository 호출 단위로 `asyncio.to_thread`에 보내고 모델 호출 중 transaction을 유지하지 않는다.
단계별 lease token을 저장 완료 조건으로 전달하고 성공한 임베딩은 주장 실패 후에도
다시 호출하지 않는다. 종료 시 새 선점을 중단하고 진행 중 호출을 제한된 시간 내 정리하며,
중단된 작업은 lease 만료 뒤 repository 재선점으로 복구한다.

B12 런타임의 합성 분석 버전은 최대 128자로 검증하며 DB의 256자 저장 한도 안에 둔다.
분석 전용 PostgreSQL 연결은 connect timeout 5초·statement timeout 5초·lock timeout
1초를 적용한다. 종료 중 thread 자체를 강제 종료하지 않고 이 제한 안에서 transaction을
수거하며, 호출자 취소 후 발생한 DB 예외도 원문 로그 없이 수거한다.

#### WU-B14 검증 결과와 미측정 항목

아래 환경 설정 검증은 실시간 코드 확장 이전 기록이다. 이후 실행 계약은 문서 끝의
`2026-09-08 실시간 공개 대화 분석 확장`을 따른다.

2026-09-08 선행 환경 설정 검증은 WU-B14의 운영 조정만 수행했다. Git 제외 `.env`의
`SPEECH_ANALYSIS_POLL_SECONDS=0.5`, `SPEECH_ANALYSIS_BATCH_SIZE=32`,
`SPEECH_ANALYSIS_CONCURRENCY=4`로 투표 직전
대기 작업 처리 여유를 늘린다. 모델·1536차원·분석 버전·timeout 30초·단계별 최대 3회는
유지한다. 코드 기본값과 모델 선점의 투표 직전 경계는 바꾸지 않는다. 이 설정은 실시간
대화 요약을 추가하지 않으며, 전체 대화 요약·인간 발언 포함·토론 중 모델 실행은 별도
구현 범위다. 실제 모델 지연·계정 rate limit과 여러 Backend의 합산 동시성은 미측정이다.

2026-09-08 실게임 점검에서는 분석이 미완료인 상태에서 투표가 열린 현상을 관측했다.
현재 준비 SQL은 대기를 반환했고 해당 전환은 로컬 프로세스 로그에 없었다. Backend
scheduler가 instance·소유자 구분 없이 공유 DB의 모든 게임을 처리하고 분산 lease나
호환 버전 fencing을 사용하지 않으므로, 분석 비활성·초기화 실패 또는 이전 코드의 별도
Backend가 먼저 전환하면 현재 instance의 대기 계약을 우회할 수 있다. 실제 원장에서는
마감 뒤 로컬 분석이 두 임베딩을 선점했지만 3.197초 뒤 별도 전환으로 SPEECH 창이 닫혀
나머지 임베딩과 모든 주장 분석의 선점 조건이 사라졌다. 원격 DB의 statement·connection
log와 commit timestamp가 비활성이라 과거 전환 instance의 호스트·설정은 사후 특정하지
못한다. 운영에서는 공유 DB의 scheduler 실행 주체를 하나로 맞추고 모든 실행본의 분석
설정·코드 버전을 일치시켜야 한다. 다중 instance를 지원하려면 후속 WU에서 DB 기반
scheduler lease와 호환 버전 fencing을 정본·migration에 먼저 확정한다.
이번 B14 진단 보강은 기존 runtime의 운영 로그에 게임·행동 창·프로세스와 준비/우회
사유를 기록하는 범위다. 예외 원문·발언·접속 정보는 기록하지 않으며 공개 API,
분석 실행 시점, DB 구조와 장애 시 게임 진행 정책은 유지한다.

후속 B14 수정(2026-09-07, 사용자 요청)은 기존 토론 원장 복원 오류와 분석 실행 시점의
통합 보완으로 한정한다. 같은 round·cycle을 재사용한 구형 게임도 현재 날짜의 토론
기록만 복원하며, 정상 중복 제출 거부는 유지한다. worker 오류는 비밀값 없는 고정
원인 코드로 기록한다. 발언 분석은 토론 중 매 발언마다 호출하지 않고 투표로 넘어가는
경계에서 누적 공개 발언을 처리한다. 사용자는 분석 완료까지 투표 대기를 명시했다.
마감된 SPEECH window 상태에서 분석하며, 완료 또는 단계별 재시도 소진 후 투표 창을
열고 그때부터 투표 제한 시간을 계산한다. 첫날 밤 전환은 분석 대기 대상이 아니다.
구형 순차 토론의 마지막 행동은 즉시 마감된 SPEECH window를 남겨 동일한 준비 경로를
거친다. 분석 초기화·저장소 장애는 고정 코드로 기록하고 게임 진행을 영구 차단하지 않는다.
분석 준비 sweep은 기존 투표 scheduler와 분리하여 다른 게임의 제출·마감 처리를 지연시키지 않는다.
기존 결과·단계별 재시도·원장·공개 API 계약은
보존하고 Front 디자인과 기존 migration은 변경하지 않는다. coordinator는 정본·README·
실행 연결·회귀를 소유하며, 복원·로깅과 분석 시점은 파일 소유권을 나눠 보완한다.
후속 검증 결과는 focused 124 통과, Backend 전체 806 통과·기존 14 실패·8 건너뜀이다.
원격 읽기 전용으로 복원 오류 해소를 확인하고 재기동 후 기존 중단 게임의 정상 진행과
토론 중 분석 PENDING·시도 0을 확인했다. 006·게임 원장 직접 보정·Front 디자인 변경은 없다.

격리 PostgreSQL에서 006 재실행·권한·원본 계약·동시 선점·lease 소진과 종료 게임
누락 복구 등 108개 assertion을 확인했다. 합성 Provider로 실제 원장→repository→worker→
HTTP 조회를 연결한 검사와 worker 초기화·종료 오류 격리 검사를 포함해 통합 테스트
5개가 통과했다. HTTP router는 앱에 주입된 조회 서비스만 호출하고 실제 조립은 기존
`runtime_factory.py`에서 수행한다. 최종 전체 회귀 수치와 기존 실패는 README에 기록한다.

이는 실제 모델 품질 목표나 부하·지연 SLO 달성의 근거가 아니다. 현재 유사 주장은
알리바이·역할 주장·진술 변화의 같은 대상·입장에 한해 cosine 0.88 이상 및 숫자·직업
근거 일치로 보수적으로 표시한다. 유료 한국어 평가셋과 프로세스 강제 종료를 포함한
실게임 부하 검증은 별도 측정 항목으로 남긴다. 실제 서비스는 migration과 권한 준비 후
기능 설정을 켜고 재시작해야 하며 이번 구현에서 실제 env와 서비스 DB는 변경하지 않았다.


## 2026-09-08 실시간 공개 대화 분석 확장 (사용자 승인 WU-B14)

사용자의 코드 변경·Orca orchestration 요청에 따라 coordinator 세션은 WU-B14 통합을
맡고 저장소 B11, worker B12, 화면 F9를 각각 별도 작업자 세션에 배정한다. 이번 절이
앞선 투표 직전 전용 실행·AI만 분석하는 제한보다 우선한다. 기존 사용자 변경은 보존한다.

- Backend B11: 확정된 PUBLIC PLAYER_SPOKE 중 HUMAN·AI 발언을 분석한다. 모델 신규
  선점은 IN_PROGRESS 게임이면 현재 phase·날짜·deadline과 무관하게 허용한다. SAVED·
  COMPLETED·FAILED는 신규 선점하지 않는다. 이미 선점한 유효 결과는 기존 token·만료
  검증으로 저장하며 삭제 후에는 기존 FK와 CAS로 무효화한다.
- Backend B12: 탐색과 실행을 분리해 느린 모델 요청 하나가 다음 발언 발견을 막지 않게
  한다. 동시 호출 상한·단계별 timeout·재시도·종료 정리를 유지하며 유료 회귀는 하지 않는다.
  주장 추출의 검증된 proposition을 요약에 재사용하므로 모델·프롬프트 버전은 유지한다.
- B14 조회 통합: 기존 vote-insights를 일반·최종 토론에서도 읽을 수 있게 확장하고
  conversation_summary를 추가한다. 토론 cutoff는 읽기 snapshot의 공개 원장 최대 sequence+1,
  투표 cutoff는 기존 창 최초 개설 sequence다. 같은 snapshot에서 source·분석을 조회한다.
  토론 중에는 투표 후보·순위를 생성하지 않는다. 요약은 준비된 발언별 핵심 주장 최대 3개를
  묶고 최신 20발언을 원문·시점과 연결한다. 총 요약 발언 수와 생략 수를 함께 반환한다.
  이는 누적 핵심 주장 보기이며 별도의 모델이 전체 대화를 재해석하는 종합문은 아니다.
- Front F9: 기존 접이식 컴포넌트에서 공개 대화 요약을 토론 중에도 제공한다. 토론 READY도
  전체 화면 rerun마다 갱신하고 투표의 고정 cutoff 캐시는 유지한다. 저장 중에는 조회하지
  않으며 조회 오류가 발언·투표·게임 저장을 막지 않는다.
- 투표 직전에는 이전 승인된 분석 완료/재시도 소진 대기를 유지한다. 실시간 처리가 이미
  완료한 결과는 재사용한다. 게임 저장은 분석 대기 없이 직전 확정 게임 상태를 저장한다.

Backend B11의 최소 신규 파일은
`backend/migrations/008_allow_public_human_speech_analysis.sql`이다. 기존 006의 source
검증 함수를 교체해 PUBLIC HUMAN도 허용하되 나머지 원문·hash·모델·lease·claim 계약은
보존한다. 기존 디렉터리와 전용 테스트를 재사용하고 root README·정본은 coordinator만
편집한다. migration 적용·재실행 검증은 격리 QA DB에서 수행하며 실제 서비스 DB 변경과
재기동은 이번 코드 작업의 범위에 포함하지 않는다.


검증 결과: 관련 focused test 412개와 M9 격리 DB 검증 57개가 통과했다. Backend 전체는
925 통과·기존 14 실패·B6 opt-in 8 건너뜀, Front 전체는 452 통과·기존 7 실패다.
001~008 적용과 합성 데이터가 있는 상태에서 008 재실행·기존 행/권한/활성 시각 보존,
HUMAN source·private 거부·8개 동시 선점·stale lease·저장/재개/삭제를 확인했다.
기존 006과 실제 서비스 DB·실행 프로세스·모델/분석 버전은 변경하지 않았다.
실제 모델 품질·서비스 부하·강제 종료 평가는 수행하지 않았다. 상세 결과는 root README를 따른다.


### 2026-09-08 후속 WU-M9 Team DB 적용

사용자가 Team DB 마이그레이션 적용을 명시 승인했다. 이번 WU-M9는
TEAM_DATABASE_URL의 기존 4team_db에 검증된 008 함수 교체만 적용하고 데이터·권한·
트리거 및 commit 후 health를 확인한다. 006 재실행·다른 migration·서비스 재시작은
포함하지 않는다. 전용 DDL URL이 없는 기존 환경에서는 앞선 원격 migration과 같이
Team 계정의 실제 함수 소유권·DDL 권한을 먼저 확인한 별도 관리 연결을 명시 사용하며
실제 env 값을 추가·변경·출력하지 않는다. Orca 검토 작업자는 SQL·실행기만 읽고
coordinator가 실제 DB 적용과 README 기록을 담당한다.


M9 적용 결과: Team 4team_db의 기존 006 함수를 확인한 뒤 008 본문을 외곽
REPEATABLE READ transaction에서 적용·검증·commit했다. 원본/분석 6개 테이블의
행 수·내용 hash, 함수 OID·owner·ACL·실행 설정과 트리거·relation 메타데이터를
보존했고 독립 읽기 연결에서 정확한 008 본문·활성 트리거·DB health를 확인했다.
실제 env·계정·권한·게임/분석 행은 수정하지 않았으며 서비스 재시작은 수행하지 않았다.
SQL 변경이 없으므로 직전 격리 QA·전체 회귀 결과를 재사용했다. 상세 집계는 README를 따른다.

## 2026-09-08 CUSTOM_ROLE 계약 고정 (사용자 승인 CP-0)

이 절은 자유 직업 선택과 충돌하는 기존 문구보다 우선하며, 이번 작업은 구현 없이 다섯 정본의 계약만 고정한다. `STANDARD`는 `mode`를 생략하거나 `STANDARD`로 보낸 기존 생성 요청·역할 무작위 배정·밤 행동을 그대로 유지한다. `CUSTOM_ROLE`은 인간 한 명만 자유 직업을 사용하며, 사용자는 NFC와 공백 정규화 뒤 1~40자인 직업명, `CITIZEN` 또는 `MAFIA` 진영, `custom-role-v1` catalog와 versioned ability ID 1~3개를 선택한다.

허용 ID는 `night.attack.v1`, `night.investigate.v1`, `night.protect.v1`, `vote.triple.v1`, `intel.special_roles.v1` 다섯 개다. `CITIZEN`은 공격 외 네 능력 중 1~3개를 선택하며 낮/조회 능력만도 가능하다. `MAFIA`는 공격을 반드시 포함하고 나머지 중 추가하여 총 1~3개를 선택한다. 커스텀 역할은 밤 능력이 여러 개여도 밤마다 그중 하나만 사용한다. 직업명은 신뢰하지 않는 일반 표시 문자열이며 system prompt나 역할 지침으로 승격하지 않는다. Backend는 catalog version, allowlist, 중복, 진영별 조합을 fail-closed로 검증한다.

기존 인원별 `mafia_count`는 바꾸지 않는다. CUSTOM_ROLE 인간이 `MAFIA`이면 인간을 mafia 슬롯에, `CITIZEN`이면 citizen 슬롯에 고정하고, 남은 AI에는 표준 mafia 수와 detective·doctor 구성을 유지한다. 승패는 표시용 직업명이 아니라 저장된 faction으로 판정한다. 복수의 INVESTIGATE·PROTECT actor를 허용하고 밤 해소에는 모든 보호 대상의 합집합을 적용한다. 상세 생성·catalog·snapshot·command 계약은 API 명세, 저장 계약은 DB 설계, MCP 경계는 MCP 서버 설계, 사용자 흐름은 화면 정본을 따른다.

### 구현 작업 단위와 파일 경계

| 순서 | WU | 허용 파일 경계 | 완료 기준 |
|---:|---|---|---|
| 1 | `WU-B16` Backend | `backend/`의 additive migration, game model·repository·규칙 engine, 공개 API와 해당 테스트 및 이 다섯 정본 | 구형 행과 STANDARD 회귀, 생성 validation, 슬롯 고정, faction 승패, 복수 조사·보호, private projection을 focused·전체 회귀 테스트로 검증 |
| 2 | `WU-F11` Front | `frontend_user/`의 새 게임 설정·역할 공개·밤 행동 화면과 해당 테스트 및 이 다섯 정본 | catalog 조회, CUSTOM_ROLE 입력·오류·접근성, 능력 하나 제출, STANDARD 화면 회귀를 합성 API와 연결 검증 |
| 3 | `WU-M10` 계약·호환 검증 | `mcp_server/`의 기존 descriptor·adapter 검증 테스트와 운영 검증 문서만 허용하며 runtime mutation·신규 Tool·DB 접근은 금지 | 세 versioned ID가 기존 `propose_night_action`을 참조하고 raw Tool명·action subtype·prompt가 공개 입력이 아님을 확인하며 STANDARD 및 HUMAN-only 비간섭성을 입증 |

`CP-7 CUSTOM_ROLE 통합`은 `CP-0 -> WU-B16 -> WU-F11 -> WU-M10 -> CP-0.1 -> WU-B17 -> WU-F12 -> CP-7` 순서로 진행한다. B16 계약 fixture가 확정되기 전에 F11을 실제 Backend에 결합하지 않는다. M10의 확장 범위는 아래 사용자 요청 절을 따르며, CP-0.1에서 공개 adapter·Front 확장 계약을 고정한 뒤 B17 응답 fixture와 F12 연결을 순서대로 검증한다. CP-7 완료 조건은 생성부터 재접속·밤 행동·처형 공개·종료·STANDARD 회귀까지의 통합 증거와 다섯 정본의 링크·용어·schema 일치다. custom AI 지원은 이 순서에 포함하지 않고 별도 후속 WU로 예약한다.

### 2026-09-08 사용자 요청 WU-M10: 커스텀 직업 전용 MCP 능력 추가

이번 사용자의 신규 Tool 구현 요청은 위 M10의 신규 Tool·runtime 변경 금지와 순서를
이 범위에서 대체한다. 단일 WU-M10 안에서 MCP 등록·HTTP adapter와 이에 필요한
Backend catalog·command·조회·순수 규칙·저장 복원 및 관련 테스트를 연결한다.
Backend는 판정·소유권·저장을, MCP는 내부 HTTP 위임을 담당하는 기존 소유권을 유지한다.
Front UI 구현, custom AI, 실제 DB migration 적용은 포함하지 않는다. 기존 B16 작업은 보존한다.

- `vote.triple.v1`: HUMAN 능력자가 능력 ID를 지정해 제출한 처형 투표 한 장의 가중치는 3이다.
  DAY_VOTE·REVOTE에만 적용하며 일반 제출·자동 투표·최종 지목은 1표다. 표는 창당 한 번만
  제출할 수 있고 가중치를 더하거나 다른 플레이어의 표를 바꾸지 않는다.
- `intel.special_roles.v1`: 첫 밤이 끝난 뒤(`day_number >= 2`) 생존한 HUMAN 능력자는
  마피아·시민을 제외한 다른 플레이어의 특수 직업을 조회할 수 있다. 현재 표준 역할은
  탐정·의사이며 사망자도 포함한다. 본인 전용 읽기이며 밤 행동 횟수를 소모하지 않는다.
- 기존 `custom-role-v1`에 두 versioned ID를 additive로 제공한다. 두 진영 모두 선택할 수
  있고 능력 수 1~3개·마피아 공격 필수는 유지한다. 밤 능력이 없는 시민 커스텀 직업도 허용한다.
- M10 자체의 신규 파일은 `backend/migrations/011_add_custom_role_tool_abilities.sql` 하나다.
  기존 010은 유지하고 VOTE의 `vote.triple.v1` 저장만 순방향으로 허용한다. 이후 현재
  team DB baseline과 새 DB의 최종 object·seed를 맞추기 위한 별도 순방향 정리 파일
  `backend/migrations/012_align_team_db_baseline.sql`은 M10 기능 범위와 분리한다.

M10 완료는 MCP 왕복·권한 거부·첫 밤 경계·가중 집계·재투표·재개·STANDARD 회귀를
합성 데이터로 검증한 시점이다. 실제 화면 사용과 CP-7 완료는 후속 WU-B17·WU-F12 연동 증거가 필요하다.


### 2026-09-08 CP-0.1 공개 adapter·Front 확장 계약

이번 CP-0.1은 다섯 정본만 최소 갱신하는 문서 계약 WU다. 기존 WU-M10의 두 Tool·
능력·저장 계약을 보존하고 코드·루트 README·migration 실행·commit/push는 범위 밖이다.

| 순서 | WU | 허용 파일 경계 | 완료 기준 |
|---:|---|---|---|
| 4 | `WU-B17` 공개 adapter | 기존 `backend/app/routers/game_router.py`, 조회 service·공개 schema 및 관련 Backend 테스트·정본·README | 인증된 사용자 흐름의 `GET /api/v1/games/{game_id}/special-roles` + `X-User-Id`를 기존 `read_special_roles`에 연결하고 success envelope·no-store·404/403/409·소유권/해금 거부를 검증 |
| 5 | `WU-F12` Front 확장 | 기존 `frontend_user/`의 생성·API client·view model·투표·게임·종료 화면과 관련 테스트·정본·README | 정확한 5개 descriptor와 진영 배열/중복의 fail-closed 검증, 신규 ID 수용, 일반 1표/능력 3표 선택, day>=2 private 조회·안전한 오류/재시도·범위 격리, 종료 custom 직업명/진영·평문 escape와 STANDARD 회귀 검증 |

공개/내부 조회의 schema·오류는 [API 정본](AI_MAFIA_API_SPEC.md), 저장 없는 조회 경계는
[DB 정본](../02_backend_data/AI_MAFIA_DB_DESIGN.md), raw Tool 비직접 호출은
[MCP 정본](../03_mcp_agent/AI_MAFIA_MCP_SERVER_DESIGN.md), 화면 조건은
[화면 정본](../04_frontend/AI_MAFIA_SCREEN_FLOW.md)을 따른다. CP-7에는 B17·F12의 성공/거부 경로와
identity/game/state 전환 시 private 결과 폐기, FINAL_ACCUSATION 능력 미노출,
공개 명부·timeline·analytics 비복제의 통합 증거를 추가한다.
