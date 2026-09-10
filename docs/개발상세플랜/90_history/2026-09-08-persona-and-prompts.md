# 페르소나·프롬프트 변경 이력 (2026-09-07 ~ 2026-09-08)

루트 README의 변경 기록에서 옮긴 문서입니다. WU-M6 역할별 프롬프트 정리,
WU-B6 페르소나 추론 수치 조정(migration 009), 첫날 발언 지침, system 메시지
축소, `dialogue_focus` 추가와 관련 검증을 기록합니다.

## 역할별 AI Agent 프롬프트 (WU-M6)

### 자연스러운 대화·전략적 블러핑 재설계 (2026-09-08)

이번 사용자 요청은 기존 MCP 소유 프롬프트의 재설계다. 아래 공격적 토론 보완의
게임 내 블러핑 허용은 유지하되, 모든 성격에 매번 압박·도발을 요구하는 지침은 이
절로 대체한다. 실제 게임 규칙·모델·DB·정보 접근 권한을 바꾸는 작업은 아니다.

검토한 경로와 문제:

- [`instructions.py`](../../../mcp_server/mafia_game/api/prompts/instructions.py)의 역할별
  토론과 공통 말투가 모두 추궁을 강조해 성격 차이·수긍·짧은 답변을 약화시키고 있었다.
  고정된 도발 예문도 같은 표현의 반복을 유도할 수 있었다.
- [`resources/registry.py`](../../../mcp_server/mafia_game/api/resources/registry.py)는 AI
  입력에서 개인 알리바이·관찰을 제외하는데 첫 발언 지침은 이를 참조하도록 요구했다.
  첫 발언은 실제 공개 발언에 대한 반응이나 새로운 확인 질문·판단 기준으로 바꿨다.
- MCP Prompt와 Resource는 같은 렌더러를 사용하고,
  [`orchestrator.py`](../../../backend/app/agent/orchestrator.py)는 지침을 developer에
  한 번만, 원문을 user 데이터에 전달한다. Backend 공통 규칙·출력 schema·교정,
  Provider, 공개 발언 분석용 별도 추출 프롬프트는 수정하지 않았다.

재설계 내용:

| 범위 | 지침 |
|---|---|
| 공통 대화 | 본인에게 온 말에 반응하고 한 번에 쟁점·목적 하나를 선택한다. 의심 대상과 설득할 사람을 구분하고 짧은 인정·방어·조건부 협력을 섞는다. |
| 시민 | 타당한 답에는 의심을 낮추고 동조·표 몰이의 이득을 비교한다. 미끼 역할 자칭·거짓 확신은 선택지이며 아군 오처형 위험이 커지면 거둔다. |
| 탐정 | 본인 실제 조사만 확정 정보로 쓰고 공개 시점을 판단한다. 미끼 주장은 실제 조사와 분리하고 조사 대상은 다음 투표를 바꿀 정보 가치로 고른다. |
| 의사 | 보호 계획을 매번 예고하지 않는다. 보호하고 싶은 호감과 역할 판단을 구분하고, 탐정·설득의 중심·자기 생존의 가치를 비교한다. |
| 마피아 | 검증 가능한 사실·작은 양보로 신뢰를 얻고 필요한 왜곡을 섞어 표를 모은다. 밤에는 공격할 사람뿐 아니라 낮에 처형으로 몰 후보를 살려 둘지도 비교한다. |
| 말투 | 200자 안에서 필요한 만큼만 말하며 매번 질문·보고서식 요약으로 끝내지 않는다. 페르소나·현재 압박에 맞게 표현하되 공격성·고정 예문·의도적 오독을 강제하지 않는다. |

첫날 SPEAK 의무, 이후 내용 없는 경우의 PASS, 재투표 후보 제한과 최종 단계 결단을
유지한다. 본인 이름·좌석은 `me.data.player_id`와 `public.data.players`로 확인하고,
허용 대상·행동은 실제 envelope의 `turn.data.valid_targets`·`turn.data.allowed_tools`를
참조한다. 서버 확정 사실·타인의 주장·본인의 블러핑을 구분하며 없는 과거 원장·개별
투표·동료 마피아 신원을 실제 조회한 정보로 보충하지 않는다. 페르소나 원문과 수치는
수정하거나 지침에 보간하지 않는다. 등록명·URI·함수 서명·API/DB schema는 그대로다.

검증 결과:

- 새 문구·정보 경계 사례 22개를 기존 MCP 등록 테스트에 추가했다. 변경 전에는 새
  기대 문구 18개가 실패하고 기존 원문 비간섭성 4개는 통과했다. 재설계 후 등록·ASGI
  왕복 테스트는 72개 통과했다.
- 최종 관련 테스트는 **289개 통과·SQL opt-in 11개 건너뜀**이다. 역할·단계 분리,
  첫날 PASS 교정·기본 발언, MCP client 지침 검증과 Provider 전달까지 포함한다.
- 실제 `model_context`와 `AgentOrchestrator._request`를 연결한 별도 합성 확인 56개가
  통과했다. 네 역할·여섯 단계, 일반 토론의 첫날/이후, 최초/교정 요청을 조합해
  developer 지침 1회 전달, user 원문 보존·주입 문자열 비승격, 첫날 SPEAK schema를 확인했다.
  이 확인은 모델 생성이나 실제 게임 플레이가 아니다.
- 역할 지침 24개 조합은 890~1,707자, 토론 페르소나 지침은 545자로 각각 2,400자
  한도를 지킨다. 비토론 페르소나 지침은 빈 문자열이다.
- Backend·MCP 비DB 전체 회귀는 **1,134개 통과·기존 실패 6개·SQL opt-in 17개 건너뜀**이다.
  실패는 Agent/Redis import 경계 2개, 직접 SQL 경계 1개, Backend MCP context 대역
  3개다. 수정 전 HEAD 프롬프트를 메모리에 로드해 실패 6개를 재실행해 동일하게
  재현했으며, 작업 파일을 되돌리거나 무관한 Backend 구현을 수정하지 않았다.
- 프롬프트 파일 Ruff는 통과했다. 기존 등록 테스트 파일의 import 정렬 3개·긴 줄
  5개 경고는 HEAD와 동일하며 새 코드의 경고는 없다. 변경 diff의 공백 검사를 통과했다.

관련 테스트 재실행 예시(저장소 루트, 별도 터미널의 합성 설정):

```bash
export TEAM_DATABASE_URL='postgresql://test:synthetic@127.0.0.1:1/mafia_tests'
export DATABASE_URL="$TEAM_DATABASE_URL" DATABASE_MIGRATION_URL='' DATABASE_NAME=mafia_tests
export REDIS_URL='redis://127.0.0.1:1/15' TEST_DATABASE_URL=''
export GAME_STATE_KEYRING_FILE='' GAME_STATE_ACTIVE_KEY_ID='' ADMIN_USER_IDS=''
export LLM_PROVIDER=dummy OPENAI_API_KEY='' GEMINI_API_KEY='' SPEECH_ANALYSIS_ENABLED=false
export B6_LOCAL_QA=0 VOTE_INSIGHT_TEST_DATABASE_URL='' PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
export PYTHONPATH=.:mcp_server
.venv/bin/python -B -m pytest -c pyproject.toml -p pytest_asyncio.plugin -p anyio.pytest_plugin \
  -p no:cacheprovider mcp_server/tests/test_fastmcp_registration.py \
  mcp_server/tests/test_fastmcp_roundtrip.py backend/tests/test_b6_agent_manager.py \
  backend/tests/test_fastmcp_agent_client.py backend/tests/test_llm_provider.py -q --tb=short
.venv/bin/python -B -m pytest -c pyproject.toml -p pytest_asyncio.plugin -p anyio.pytest_plugin \
  -p no:cacheprovider backend/tests mcp_server/tests \
  --ignore=backend/tests/test_b5_game_api.py \
  --ignore=backend/tests/test_postgres_game_flow.py \
  --ignore=mcp_server/tests/test_process_backend_roundtrip.py -q --tb=short
```

DB에 게임을 생성하는 위 세 파일, opt-in SQL, 변경 없는 Front 회귀와 유료 모델
호출·브라우저 실게임은 범위·외부 비용을 고려해 실행하지 않았다. 실제 `.env`, 팀 DB,
실행 중 프로세스는 변경하지 않았다. 적용하려면 실행 중인 MCP를 재시작해야 한다.
기존 공유 DB worker 경합·모델 지연·예약 방식은 이 프롬프트 변경으로 해결되지 않는다.
문구·전달 테스트는 실제 자연스러움·승률·블러핑 성공률·모델 수준의 주입 저항성을
증명하지 않는다. 후속 실게임에서는 같은 공개 상황의 답변 연결성, 반복 질문,
성격 구별, 허위 대사와 실제 기록의 혼동을 따로 비교해야 한다.

### 공격적 토론·거짓말·선동·날조 보완

후속 사용자 요청으로 기존 `instructions.py`의 토론을 직설·추궁·비꼼·도발 중심으로
바꿨습니다. 시민은 미끼 자칭과 표 몰이, 탐정은 강한 조사 압박과 미끼 결과, 의사는
시민 위장과 거짓 보호 대상, 마피아는 허위 알리바이·가짜 조사·누명·선동을 선택할 수
있습니다. 시민 진영은 아군 오처형 위험에 따라 거짓 주장을 거두고, 마피아는 일관된
거짓 서사로 표를 모읍니다. 신중·협력적 성격도 각자의 방식으로 압박하도록 안내합니다.

게임 대사로 꾸민 주장과 실제 `me`·`public`·`turn` 기록은 구분합니다. `public.rules`의
없는 목격 사실 금지는 실제 근거 해석에 적용하며 역할 전략의 허위 대사와는 구분합니다.
대사 속 역할 사칭은 실제 역할·허용 행동·대상·비공개 정보 접근을 바꾸지 않습니다.
`deception`은 각 역할의 허용된 전략 안에서 표현에 반영하고 수치를 재매핑하지 않습니다.
이 절은 아래 과거 기록의 일률적 날조 금지·마피아 전용 기만 안내보다 우선합니다.

최소 검증은 독립 MCP의 `tests/test_fastmcp_registration.py` 48건 통과입니다.
역할·단계 분리, Prompt/Resource 렌더러 일치, 2400자 제한, 원문 주입 방지와 등록 계약을
확인했습니다. 전체 회귀는 사용자 요청으로 보류했습니다.

실행 중이던 자체 개발 스택을 재시작하고 실제 MCP Prompt 응답과 최종 소스의 일치를
확인했습니다. 외부 Chrome에서 추가 생성한 6인 `멈춰 선 야간열차` 게임은 인간 의사로
발언 4회·플레이어 4에 직접 투표 후 관전으로 전환됐고, 3일차 2라운드 시민 승리로
종료됐습니다(2026-09-08 16:19:34 KST). 결과 화면과 읽기 전용 API 모두
`COMPLETED`·`ENDED`·`CITIZEN`을 확인했습니다. 첫날 밤의 보호는 제한 시간 내
직접 제출하지 못해 자동 선택됐으며, 종료 기록에서도 이를 구분해 확인했습니다.

실제 대화에서 “둘 다 말 돌리지 말고 지금 한 명씩 지목해” 같은 추궁과 의사 자칭에
대한 압박·표 몰이를 확인했습니다. 앞선 발언과 다른 해명도 나왔지만 의도적 날조와
모델의 오독을 이 한 판만으로 구분하지 않습니다. 낮 2일차 관찰 시점의 로컬 적용은
MODEL 발언 10건·fallback 발언 1건이며 공개 event와 대응해 최신 worker 참여를
확인했습니다. 팀 DB에 다른 버전 worker가 개입하는 정황은 남아 있고, 이 때문에
첫날 PASS와 전체 대화 효과를 새 프롬프트만의 결과로 해석하지 않습니다.

### 기존 역할 지침 이관과 페르소나 전달 기록

시민·탐정·의사·마피아의 세부 지침과 승리 계획은 MCP의
[`ROLE_PLANS`](../../../mcp_server/mafia_game/api/prompts/instructions.py)에서 관리합니다.
각 Agent에는 Backend가 검증한 본인 역할과 현재 단계(토론·밤·투표)에 해당하는
전략만 제공합니다. 성격별 `speech_style`·`backstory`·`parameters`는 DB에 배정된
값을 그대로 모델에 전달합니다. 공통 코드의 성향별 3단계 문구 선택과 마피아 기만
성향 2배 보정은 제거했습니다. 토론에는 해당 페르소나를 따르라는 공통 안내만
더하고, 토론 외에는 이 안내를 생략합니다. 기존 첫날 발언 우선 지침은 유지합니다.

2026-09-08 team DB의 `public.agent_personas`를 읽기 전용으로 확인했습니다. 활성
6개 중 현재 새 게임 버전 `agent-config-v1`에 맞는 5개는 아래와 같습니다.

| 성격 | DB의 말투 요지 | 참여도 | 주장 강도 | 기억 활용 |
|---|---|---:|---:|---:|
| 신중한 분석가 | 근거를 먼저 확인하고 단정하지 않음 | 0.45 | 0.35 | 0.85 |
| 적극적 토론가 | 빠른 발언, 질문과 반론 | 0.90 | 0.85 | 0.55 |
| 관찰형 기록자 | 짧게 이전 발언과 현재 상황 비교 | 0.55 | 0.40 | 0.95 |
| 감정적인 반응가 | 놀람과 의심을 솔직하게 표현 | 0.70 | 0.60 | 0.50 |
| 협력형 조정자 | 의견을 요약하고 부드럽게 연결 | 0.80 | 0.45 | 0.70 |

나머지 `BALANCED_OBSERVER`(차분한 관찰자)는 `version=mystery-v1`이라 현재 새 게임
배정에서 제외됩니다. 조회 당시 모든 preset의 `reasoning_skill`은 0.5였으며, 이후
사용자 요청에 따른 0.60~0.80 조정은 아래 절을 따릅니다. 팀 DB의 다른 수치는 아래
로컬 게임 복기에 따른 seed 보강값과 다르며, 이번에는 DB를 변경하지 않았습니다.

전달 경로는 `creation_service.py`의 seed 기반 배정 → `game_players.persona_id` 저장
→ `actor_context.py`의 배정 preset 재조회 → `projections.py`의 문자열·10개 수치 검증
→ MCP Resource 원문 보존 → `orchestrator.py`의 user 메시지입니다. MCP가 만든 공통
안내만 developer 메시지에 들어갑니다. 성격 전용 모델이나 별도 대화 세션을 생성하는
구조는 아닙니다. AI가 5명이면 5종을 하나씩 쓰고, 6~8명이면 같은 preset을 재사용합니다.

후속 작업은 **DB의 성격별 문장·목표 수치 정비 → 최소 8종과 버전 공존 설계 →
persona만 DB 반영 → 전달·대화 품질 비교** 순서입니다. 구체적인 WU·기존 게임 보존
조건은 [마스터플랜의 공통 성향 변환 제거와 후속 계획](../01_core/AI_MAFIA_MASTER_PLAN.md#wu-m6-공통-성향-변환-제거와-후속-계획-2026-09-08)에 기록했습니다.
이번 공통 성향 지침 삭제는 MCP를 재시작하면 적용됩니다.

검증: team DB 활성 6개 행의 Backend persona 검증·수치 보존을 확인했고, 아래
합성 테스트 49개가 통과했습니다. 작은 프롬프트 변경이라 전체 회귀·유료 모델 실행은
생략했습니다. 성격 표현과 첫날 PASS율의 실제 변화는 아직 측정하지 않았습니다.

```bash
PYTHONPATH=.:mcp_server .venv/bin/python -m pytest -q \
  mcp_server/tests/test_fastmcp_registration.py backend/tests/test_b6_agent_manager.py \
  -k 'persona or prompt or model_context'
```

## 페르소나 추론 수치 조정 (WU-B6, migration 009)

사용자 요청에 따라 `reasoning_skill`을 분석가·기록자 0.80, 토론가 0.75,
조정자·차분한 관찰자 0.70, 반응가 0.60으로 team DB의 6개 행을 갱신했습니다. 모델에 전달하는 성향
데이터이며 모델 종류·추론 effort·출력 토큰 예산이나 실제 정답률을 뜻하지 않습니다.
Backend의 전원 0.5 제한은 제거하고 기존 값과 새 값을 유한 0~1 범위에서 허용합니다.

[`009_update_persona_reasoning_skill.sql`](../../../backend/migrations/009_update_persona_reasoning_skill.sql)은
지정된 ID·version의 추론 수치와 내용 SHA-256인 `content_hash`만 갱신합니다.
다른 성향·말투·version·active는 보존합니다. 004 seed는 기존 이력으로 남기며 새 설치는
009까지 순서대로 적용해야 합니다. 기존 DB에는 009만 적용해 다른 콘텐츠를 보존합니다.
이 파일은 DDL 없는 DML이므로 대상 테이블 UPDATE 권한으로 실행할 수 있습니다.
Backend의 새 검증 코드를 먼저 반영해야 하며, 같은 team DB를 쓰는 다른 Backend에도
적용해야 합니다. 이미 저장·진행 중인 게임도 다음 persona 조회부터 새 수치를 읽습니다.

격리 QA 검증은 기존 `backend/tests/test_postgres_game_flow.py`의
`test_persona_reasoning_migration_preserves_other_fields_and_is_idempotent`에서 수행합니다.
임시 테이블만 사용해 적용 실패의 rollback, 원문 보존, hash 일치, 재실행과 version
경계를 확인합니다. persona 허용·거부 검증은 `backend/tests/test_mcp_registry_api.py`에 있습니다.

검증 결과: 관련 허용·거부 및 기존 seed 검사 16개 통과, 실제 PostgreSQL migration의
원문 보존·재실행 확인 통과입니다. 전체 Backend·MCP 회귀는 격리 QA 보완 후 합산
1,014개 통과·기존 실패 14개·선택적 SQL/통합 검증 14개 건너뜀입니다. 첫 전체 실행은
995개 통과·33개 실패였고, QA에 빠진 기존 007을 적용한 뒤 영향받은 19개만 재실행해
모두 통과했습니다. 남은 실패는 기존 Agent activity 대역, Agent/Redis/SQL 계층 경계,
MCP public context 대역 문제이며 변경하지 않았습니다. team에는 009의 DML만
한 transaction으로 적용하고 별도 읽기 연결에서 6개 값·hash와 나머지 필드 보존을
확인했습니다. Front 회귀와 유료 모델 게임은 변경 범위·비용을 고려해 생략했습니다.
확인 시 로컬 Backend·MCP·Front는 실행 중이지 않았으며 다음 기동에 새 코드가 적용됩니다.

## 첫날 발언 우선 지침

첫날 낮(`DAY_DISCUSSION`, `round=0`)에는 정보가 적다는 이유만으로 발언을 넘기지
않고 짧은 발언을 우선합니다. 첫 발언에는 새로운 확인 질문이나 판단 기준을,
이후에는 공개 발언에 대한 의견·후속 질문을 내도록 안내합니다. 이미 참여했고
새로 보탤 내용도 없을 때는 PASS를 허용하며, 반복 발언과 없는 근거 생성은 금지합니다.
자발적 PASS를 줄이기 위한 프롬프트 지침으로 실제 감소율은 아직 측정하지 않았습니다.
반영하려면 MCP를 먼저 재시작한 뒤 Backend를 갱신해야 합니다.

첫날 지침 수정 검증은 아래 합성 테스트 86개 통과입니다. 프롬프트 문구에 한정된
변경이므로 전체 회귀와 유료 모델 게임 실행은 생략했습니다.

```bash
PYTHONPATH=.:mcp_server .venv/bin/python -m pytest -q \
  mcp_server/tests/test_fastmcp_registration.py backend/tests/test_b6_agent_manager.py \
  -k 'prompt or resource or persona or dialogue_focus or request'
```

## system 메시지 축소와 MCP 패키지 구조 분리

Backend의 메인 system 메시지는 짧은 공통 마피아 규칙으로 축소했습니다. MCP가
운영 `me`·`persona` Resource에 추가한 `agent_instruction`과 Backend의 출력 JSON
계약은 developer 메시지에 한 번 전달합니다. 페르소나 원문·플레이어 발언은 user
데이터에 남기며 지시문으로 삽입하지 않습니다. Local·Gemini는 developer 지침을
해당 공급자의 system 영역에 합칩니다. 추가 MCP 왕복이나 DB 조회는 없습니다.

MCP API의 `prompts`·`resources`·`tools` 패키지는 `__init__.py`에 설명 docstring만
둡니다. 프롬프트 내용과 생성은 `prompts/instructions.py`, FastMCP 등록은 각 패키지의
`registry.py`가 담당하며 composition root와 소비자는 구현 모듈을 직접 import합니다.
이 구조 분리 후 독립 MCP의 등록·지침·ASGI 왕복·Backend adapter 테스트 85개가
통과했습니다. 동작을 유지한 모듈 이동이므로 전체 Backend 회귀·실제 DB·유료 API
재검증은 생략했습니다.

사용 모델 `gpt-5.6-luna`, 추론 강도와 출력 토큰 예산은 유지했습니다.
[공식 프롬프트 가이드](https://developers.openai.com/api/docs/guides/prompt-guidance-gpt-5p6)에
따라 중복 설명·예시와 현재 단계에 불필요한 전략을 줄였습니다. 과거 공개 발언과
본인 비공개 조사 기록은 길이 축소를 위해 자르지 않습니다.
프롬프트 축소 당시 공통 system은 262자였습니다. 9개 표현 성향을 모두 0.5로 둔 합성 입력에서 출력 계약을
포함한 system·developer 문자 수는 토론 4,463~4,687자에서 2,162~2,215자,
밤·투표 4,341~4,573자에서 1,563~1,646자로 감소했습니다. 토큰 수·승률·응답 품질의
실측 결과는 아닙니다.

MCP를 먼저 갱신한 뒤 Backend를 갱신해야 합니다. 기존 MCP에는 자동 reload가
없으므로 `run_openai.sh`를 사용 중이면 스크립트를 재시작합니다. 구버전 MCP가
역할 지침을 보내지 않으면 Backend는 기존 MCP 오류 경로로 처리합니다.
자세한 운영 응답 계약은 [API 명세 WU-M6 절](../01_core/AI_MAFIA_API_SPEC.md)을
참고하세요. 인증 세션 Resource의 8.2 스키마와 DB 스키마는 변경하지 않았습니다.

관련 검증 명령(루트 가상환경, 격리 QA DB, `LLM_PROVIDER=dummy`):

```bash
PYTHONPATH=.:mcp_server .venv/bin/python -m pytest -q \
  backend/tests/test_b6_agent_manager.py backend/tests/test_fastmcp_agent_client.py \
  backend/tests/test_llm_provider.py mcp_server/tests/test_fastmcp_registration.py \
  mcp_server/tests/test_fastmcp_roundtrip.py mcp_server/tests/test_process_backend_roundtrip.py
```

2026-09-08 검증: 역할·페르소나·공급자 전달 테스트와 실제 Backend↔MCP 프로세스
통합 테스트가 통과했습니다. Backend·MCP 전체 회귀는 917개 통과·기존 실패 14개·
명시적 `B6_LOCAL_QA=1`이 필요한 SQL 테스트 8개 건너뜀입니다. 기존 실패는 Agent
activity 테스트 대역의 설정·상태 누락, Agent/Redis/SQL 계층 경계와 MCP 공개 context
대역 문제이며 이번 범위에서 수정하지 않았습니다. 통합 테스트용 격리 QA DB에는
기존 007 마이그레이션을 적용했습니다. 변경하지 않은 Front 회귀와 유료 Luna 게임
재실행은 생략했으며, 프롬프트 축소의 실제 승률·대화 품질은 아직 측정하지 않았습니다.

## 최근 대화 반영 보완과 실시간 처리 제약 (2026-09-08, WU-B6)

AI의 토론 입력에 `dialogue_focus`를 추가했습니다. 현재 토론의 최근 공개 발언 6개와
본인을 이름·좌석으로 언급한 타인 발언 후보 6개, 본인의 마지막 발언, 그 뒤 타인의
발언 수를 따로 보여줍니다. 인간과 AI 발언을 같은 기준으로 다루며, 발췌 밖의 전체
공개 이력과 본인 조사 기록도 기존대로 전달합니다. 후보는 질문·미답·회피의 확정
판정이 아니며 모델이 자신의 이전 답변과 원문을 비교합니다. 동명이인은 이름 단독
언급을 제외하고 좌석 호칭으로 구분합니다.

첫날 GAME_BEGAN 또는 현재 round와 일치하는 NIGHT_RESOLVED 이후를 발췌합니다.
경계가 없거나 다르면 발췌만 생략하고 전체 context를 사용합니다. PASS나 발언 window
교체는 토론 경계로 보지 않으며, PASS는 새 타인 발언 수에 포함하지 않습니다.
새 답·근거 없이 같은 질문을 재촉하지 않도록 안내하되 자동으로 PASS를 강제하지는
않습니다. 의미상 반복 감소와 실제 응답 품질은 모델 출력에 달려 있습니다.

추가 조회·모델 호출 없이 기존
[`orchestrator.py`](../../../backend/app/agent/orchestrator.py)의 입력 구성에서 처리하며,
토론 SPEECH에만 적용합니다. 자유 문자열은 user 데이터에만 남기고 기존 MCP의
역할별 전략·말투 지침은 유지합니다. 공개·MCP API와 DB schema는 바꾸지 않았습니다.
실행 중인 Backend를 갱신해야 새 입력 구성이 적용되며 MCP 재시작은 필요하지 않습니다.

자유 토론의 인간은 AI 차례와 무관하게 발언할 수 있습니다. AI의 다음 차례는
[`discussion_transaction.py`](../../../backend/app/services/game/discussion_transaction.py)에서
최근 60초 행동 횟수와 좌석 순서로 고릅니다. 질문받은 AI에 대한 우선권은 없습니다.
SPEAK·PASS마다 상태 버전과 예약 window가 바뀌므로, AI가 생성하는 동안 인간이
발언하면 이전 결과는 재검증에서 거부됩니다. 현재 worker는 진행 중 모델 호출이
끝난 뒤 다음 차례를 처리하며, 발언·밤 작업은 게임 사이에도 순차 실행합니다.
화면 수신에는 이미 SSE와 전경 2초 polling fallback이 연결되어 있습니다.

질문받은 AI의 제한된 답변 우선권과 공정성, 새 발언 commit 뒤 worker 즉시 깨우기,
오래된 생성 작업의 재판단은 **후속 WU로 남아 있습니다**. window·공개 계약·MCP
지침을 바꾸는 작업은 해당 정본과 소유 섹터 경계를 먼저 맞춰야 합니다. 이전 결과를
최신 버전에 그대로 적용하거나 게임의 마감·생존·멱등성 검증을 완화하지 않습니다.

검증 시에는 공개 발언 저장부터 지목된 AI의 응답 저장까지의 시간, 같은 질문 반복,
새 발언으로 폐기된 작업을 구분해 측정해야 합니다. 진행 로그의 `sequence`는 실행별
순번이므로 DB 이벤트 순번과 직접 비교하지 않고 game·버전·시각을 함께 확인합니다.
사전 조사는 기존 공개 발언·진행 로그와 읽기 전용 DB 조회로 수행했습니다.
이번 구현은 Orca의 독립 설계 검토와 합성 테스트 작성 작업으로 나누어 진행했으며,
새 유료 모델 호출이나 실제 게임 데이터 변경 없이 검증했습니다.

검증 결과: 새 합성 사례 31개를 포함한 B6 테스트는 **57 통과·SQL opt-in 8 건너뜀**입니다.
Backend·MCP 회귀는 **940 통과·기존 실패 14·SQL opt-in 11 건너뜀**입니다. 기존 실패는
Agent activity 대역의 필수 설정·worker 누락, Agent/Redis/SQL 계층 경계 검사,
MCP 공개 context 대역 문제로 이전 기록과 같으며 이번 범위에서 수정하지 않았습니다.
실제 DB가 필수인 `test_b5_game_api.py`, `test_postgres_game_flow.py`,
`test_process_backend_roundtrip.py`는 DB 동작 변경이 없어 회귀 수집에서 제외했습니다.
변경하지 않은 Front 회귀·실게임 품질 측정·유료 모델 호출은 생략했습니다.

관련 검증 재실행 명령은 외부 환경 대신 합성 설정을 사용합니다. 전체 회귀를 실행하려면
마지막 줄의 B6 파일을 `backend/tests mcp_server/tests`로 바꾸고 위 DB 필수 3개 파일을
각각 `--ignore=<전체 상대 경로>`로 제외합니다.

```bash
TEAM_DATABASE_URL='postgresql://test:synthetic@127.0.0.1:1/mafia_tests' \
DATABASE_URL='postgresql://test:synthetic@127.0.0.1:1/mafia_tests' DATABASE_NAME=mafia_tests \
REDIS_URL='redis://127.0.0.1:1/15' GAME_STATE_KEYRING_FILE='' GAME_STATE_ACTIVE_KEY_ID='' \
LLM_PROVIDER=dummy OPENAI_API_KEY='' GEMINI_API_KEY='' SPEECH_ANALYSIS_ENABLED=false \
B6_LOCAL_QA=0 VOTE_INSIGHT_TEST_DATABASE_URL='' PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
PYTHONPATH=.:mcp_server .venv/bin/python -m pytest \
  -p pytest_asyncio.plugin -p anyio.pytest_plugin backend/tests/test_b6_agent_manager.py -q
```

## 역할 활용·판단 근거 프롬프트 보강

AI 프롬프트는 매 행동 전에 본인 역할을 확인하고, 역할 공개·은폐와 밤 능력을
상황에 맞게 활용하도록 안내합니다. 탐정은 실제 조사 결과가 있으면 탐정임을 밝히고
대상·조사 라운드·마피아 여부를 공개할 수 있습니다. 조사 결과가 `false`인 경우에는
‘마피아가 아님’만 알 수 있으므로 시민·의사 등 특정 직업으로 단정하지 않습니다.
의사는 보호 선택과 공개 위험을 고려하고, 시민은 진술 비교로 협력하며, 마피아는
정체 은폐와 역할 위장을 활용합니다. 이는 모델의 발언 지침이며 역할 판정 규칙을 바꾸지 않습니다.
페르소나의 말투·배경과 성향 수치는 원문 그대로 전달하고 모델이 해당 성격을
반영하도록 안내합니다. 공통 코드에서 정형 문구로 변환하지 않으며 200자 제한은 유지합니다.

2026-09-07 12:08~~12:19 산장 9인 게임 복기 후, `agent_personas.parameters`의
기억 활용을 0.90~~0.98, 주장 강도를 0.65~0.90으로 높이고 캐릭터별 위험 감수·협력·
참여도를 조정했습니다. 정확한 preset별 값은 마스터플랜 5.3절과 기존
`004_seed_scenarios_and_personas.sql`에 있습니다. 의심·기만·감정·발언 길이와
당시 `reasoning_skill=0.5`는 유지했습니다. 이후 009의 0.60~0.80 조정이 우선하며,
이 수치는 모델 추론 effort 설정이 아닙니다.
프롬프트에는 발언자·원문 대조, 이미 답한 질문 반복 방지, 처형으로 뒷받침된 탐정
보고의 신뢰도 갱신, 비공개 투표 이력 추측 금지, 마지막 판정에서의 결론 제시를
반영했습니다. 의사는 다섯 번째 밤에도 신뢰할 탐정의 조사 전달 가치를 고려합니다.
해당 게임이 저장된 로컬 Backend `18000`의 preset 5건과 content_hash를 한 transaction으로
갱신하고 읽어 확인했습니다. 공유 DB에는 적용하지 않았습니다. persona는 매 context 조회에서
읽으므로 다음 AI 판단부터 적용되며, 이전 완료 게임의 대사·투표·역할은 변경하지 않습니다.

## 기타 프롬프트 지침 보완

AI 발언 지침은 구어체 자기 보호 계획을 이미 제공된 답으로 인정하고, 아직 발언 기회가
없는 무응답과 모호한 목격을 마피아 증거로 삼지 않도록 보완했습니다. 시민 오처형
뒤에는 기존 의심 근거를 재검토하며, 밤 사망만으로 역할 자칭을 확정하지 않습니다.
프롬프트 지침이므로 모든 모델 응답의 준수를 보장하지는 않습니다.

운영 FastMCP는 AI 입력에서 시나리오 제목만 유지하고 배경·피해자·장소·개인 알리바이·목격담을 제외합니다. 대신 public.data.rules로 밤 행동·투표·승패·정보 공개 규칙을
제공합니다. 공개 발언과 본인 조사 결과는 보존하며 Front의 시나리오 화면은 그대로입니다.
Backend MCP 클라이언트는 기존·축약 응답을 모두 허용합니다. 실행 중인 MCP 프로세스는
코드 변경 후 재기동해야 적용됩니다. 검증: MCP 테스트 45개, Backend MCP 클라이언트
테스트 47개 통과. 실제 유료 모델 호출은 실행하지 않았습니다.

OpenAI 실행의 루트 `.env` 모델은 `OPENAI_MODEL=gpt-5.6-luna`로 설정하며, OpenAI
추론 모델 요청의 `reasoning.effort`는 `high`을 사용합니다.

AI는 규칙 안에서 자기 진영 승리를 최우선으로 판단하고 인간·AI 주장에 동일한 증거
기준을 적용합니다. 마피아의 기만 표현은 DB의 deception 값을 그대로 참고하며, 공통
코드의 2배 보정은 제거했습니다. 실제 거짓말 발언 비율을 보장하는 설정은 아닙니다.

AI 발언은 반말을 허용한 짧은 게임 채팅 구어체를 사용하도록 지시합니다. 보고서식
검증·신뢰도 표현과 매번 반복하는 상황 요약은 줄이고, 캐릭터별 어조와 승리 우선
판단은 유지합니다.

## 2026-09-07 WU-B6 실게임 검증 (OpenAI gpt-5.6-luna)

2026-09-07 WU-B6 발언·투표 수정은 사용자의 후속 요청에 따라 전체 회귀를 생략하고
**Chrome에서 실제 OpenAI `gpt-5.6-luna`로 6인 게임 한 판을 완료**했습니다.
기존 로컬 DB 환경의 `18000` Backend, `18100` MCP, `18501` 사용자 Front를 사용했고
다른 원격 실행과 분리했습니다. `CORS_ALLOWED_ORIGINS`에는 실제 Front origin을
명시해야 합니다. 이번 실행에는 `http://127.0.0.1:18501,http://localhost:18501`을 사용했습니다.

- 첫날 AI 5명, 둘째 날 4명, 셋째 날 2명: **모델 발언 11회·적용 11회, PASS 0회**.
- 첫 투표의 AI 선택은 좌석 순서로 **1번·6번·6번·4번**이었고 마지막 두 AI는
공개된 탐정 조사 결과에 따라 1번을 선택했습니다. 실행 로그에서 AI 투표 6건 모두
정상 선택·적용을 확인했으며 fallback은 없었습니다.
- 셋째 날 마피아가 처형되어 **시민 진영 승리**로 종료됐습니다. 밤은 입력 마감에
따른 자동 선택으로 해소됐으며 수동 밤 제출 성공은 이번 플레이에서 확인하지 않았습니다.
- UI의 공개 판단 근거·모델/대체 구분과 종료 후 전체 투표 기록을 실제 브라우저에서
확인했습니다. 저장·재개도 같은 게임에서 확인했습니다.
- 최초 공유 DB 실행에서는 이 Backend가 완료하기 전에 다른 실행 경로가 AI PASS를
기록하는 간섭이 관찰돼 해당 게임을 저장했습니다. 같은 DB를 쓰는 다른 Backend도
동일 버전으로 갱신하거나 실행 대상을 분리해야 합니다. 이 작업은 원격 작업자를 중지하지 않습니다.

후속 요청 전 focused 검증은 Backend 68개·Front 148개가 통과했습니다. 이후 추가한
검증 코드와 전체 회귀는 사용자 요청에 따라 실행하지 않았습니다. 위 한 판의 결과는
여러 게임의 추론 품질·승률을 보장하는 자료가 아닙니다.

이어진 역할·페르소나 프롬프트와 결과 화면 대비 수정에서는 사용자 요청에 따라
자동 테스트·lint·전체 회귀를 실행하지 않았습니다. 기존 완료 게임을 로컬 Front에서
다시 열고 별도 Chromium의 다크 테마에서 밤·조사·투표 기록, 요약 숫자와 보조 설명의
실제 색상·화면을 확인했습니다. 로컬 Backend를 재시작해 프롬프트도 반영했습니다.
앞의 게임 한 판은 이번 프롬프트 보강 이전 기록이며, 새 지침의 역할 공개·페르소나
발언 품질은 추가 실게임으로 평가하지 않았습니다.
