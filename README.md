<div align="center">

# AI MAFIA

### 같은 사건을 보지만, 같은 머릿속을 공유하지 않습니다.

한 명의 인간과 개성 있는 AI들이 펼치는 대화·추리·블러핑 게임

<img src="frontend_user/assets/main.png" alt="밤의 도시에서 마피아 게임을 준비하는 개성 있는 AI 캐릭터들" width="960">

**1 HUMAN + 5–8 AI** · **5 SCENARIOS** · **CUSTOM ROLES**

[핵심 설계](#design) · [ERD](docs/arrangement/01_DB_REDIS_DESIGN.md#3-논리-데이터-구조) · [독립적인 판단](#agents) · [시스템 관계도](#system) · [MCP 도구](#mcp) · [빠른 실행](#quick-start) · [Docker 배포](#docker-deployment) · [개발 안내](#development)

</div>

---

**AI 마피아**는 함께할 사람을 기다리지 않고 AI 플레이어들과 한 판을 시작할 수 있는
소셜 디덕션 게임입니다. `mystery-v1`의 6~9인 게임에 다섯 개의 사건 배경을 결합하고,
각 AI에 서로 다른 역할과 페르소나를 부여합니다.

| 각자의 판단 | 제한된 도구 | 하나의 게임 규칙 |
| :--- | :--- | :--- |
| AI별로 입력을 새로 구성하고 개별 요청 | MCP로 허용된 문맥 조회와 행동 위임 | Backend가 유효성·마감·승패 확정 |
| 다른 AI의 비공개 컨텍스트 공유 없음 | 모델 출력은 아직 확정되지 않은 제안 | PostgreSQL은 원본, Redis는 공개 이력 캐시 |

현재 구현을 빈 디렉터리에서 구축하기 위한 통합 설계 문서는
[arrangement 전체 시스템 설계서](docs/arrangement/AI_MAFIA_SYSTEM_ARCHITECTURE_DESIGN.md)와
그 하위 DB·Redis·API·MCP·게임 엔진·화면·에이전트 아키텍처 설계서에서 확인할 수 있습니다.
영역별 구현 순서와 검증 기준은 [세부 구현 계획서 목록](docs/arrangement/AI_MAFIA_IMPLEMENTATION_PLAN.md)을
참조하며, 문제 정의·사용자 가치·MVP 범위는 [프로젝트 기획서](docs/arrangement/00_AI_MAFIA_PROJECT_PROPOSAL.md)에,
Agent의 실행·검증 결과와 한계는 [에이전트 시험 결과 보고서](docs/arrangement/07_AGENT_TEST_RESULT_REPORT.md)에,
계획에서 실제 구현·오류 개선·통합 검증까지의 흐름은 [프로젝트 수행과정 보고서](docs/arrangement/08_PROJECT_EXECUTION_REPORT.md)에 정리합니다.

<a id="design"></a>

## 00 · 핵심 설계 한눈에 보기

> **한 줄 원칙:** Front와 AI는 행동을 요청하거나 제안하고, Backend가 규칙과 권한을
> 검증하며, PostgreSQL transaction이 게임의 최종 상태를 확정합니다.

### 핵심 논리 ERD

```mermaid
erDiagram
    USERS ||--o{ GAMES : owns
    GAMES ||--|{ GAME_PLAYERS : contains
    GAMES ||--o{ ACTION_WINDOWS : opens
    GAME_PLAYERS ||--o{ ACTION_SUBMISSIONS : submits
    GAMES ||--o{ GAME_EVENTS : records
    GAMES ||--o{ GAME_SNAPSHOTS : restores
    GAMES ||--o{ COMMAND_RECEIPTS : deduplicates
    GAME_PLAYERS ||--o{ AGENT_JOBS : runs
    AGENT_JOBS ||--o{ AGENT_CAPABILITIES : grants
    GAMES ||--o{ FEEDBACK : receives
```

[ERD 설명 크게 보기](docs/arrangement/01_DB_REDIS_DESIGN.md#3-논리-데이터-구조) ·
[전체 관계·schema 정본](docs/개발상세플랜/02_backend_data/AI_MAFIA_DB_DESIGN.md#3-관계-개요)

| 🎮 **제품·게임** | 🗃️ **데이터·ERD** | 🔌 **API·동기화** |
| :--- | :--- | :--- |
| [공통 마스터플랜](docs/개발상세플랜/01_core/AI_MAFIA_MASTER_PLAN.md) · [게임 엔진·시나리오 설계](docs/arrangement/04_GAME_ENGINE_SCENARIO_DESIGN.md) | [핵심 논리 ERD](docs/arrangement/01_DB_REDIS_DESIGN.md#3-논리-데이터-구조) · [DB·Redis 정본](docs/개발상세플랜/02_backend_data/AI_MAFIA_DB_DESIGN.md) | [API 설계 요약](docs/arrangement/02_API_DESIGN.md) · [API 명세 정본](docs/개발상세플랜/01_core/AI_MAFIA_API_SPEC.md) |
| 6~9인 역할 구성, 5개 사건, STANDARD·CUSTOM_ROLE, phase·승패 규칙 | PostgreSQL 원장, Redis 파생 cache·lock·stream, transaction·migration | 사용자·관리자·내부 API, command 멱등성, snapshot·SSE·polling |
| 🤖 **MCP·Agent** | 🖥️ **화면·UX** | 🧭 **전체 설계 문서** |
| [MCP 설계 요약](docs/arrangement/03_MCP_DESIGN.md) · [MCP Server 정본](docs/개발상세플랜/03_mcp_agent/AI_MAFIA_MCP_SERVER_DESIGN.md) · [Agent 아키텍처](docs/arrangement/06_AGENT_ARCHITECTURE_DESIGN.md) | [화면 설계 요약](docs/arrangement/05_SCREEN_DESIGN.md) · [화면 흐름 정본](docs/개발상세플랜/04_frontend/AI_MAFIA_SCREEN_FLOW.md) | [통합 시스템 설계](docs/arrangement/AI_MAFIA_SYSTEM_ARCHITECTURE_DESIGN.md) · [구현 계획](docs/arrangement/AI_MAFIA_IMPLEMENTATION_PLAN.md) |
| actor별 문맥, 역할·페르소나 지침, 행동 위임과 Backend 재검증 | 사용자·관전·결과·피드백, 관리자 read-only 분석, 반응형·접근성 | 현재 구현을 기준으로 시스템·데이터·오류·보안 설계를 한 문서에 연결 |

### 설계 축별 핵심 결정

| 설계 축 | 핵심 결정 | 권위와 경계 |
| --- | --- | --- |
| 게임 규칙 | 인간 1명과 AI 5~8명이 `mystery-v1` 규칙으로 토론 → 밤 행동 → 투표를 반복합니다. 기본 역할 또는 인간 전용 커스텀 직업을 선택하며, 최대 다섯 번째 밤에도 표준 승패가 없으면 최종 지목으로 끝냅니다. | 역할 배정·행동 유효성·결정적 RNG·승패는 Backend Game Engine만 판정합니다. |
| 데이터 | 게임·플레이어·행동 창·제출·확정 event·snapshot·멱등 receipt를 PostgreSQL에 보존합니다. Redis는 공개 대화 cache, lock, event fan-out만 담당하며 언제든 원장에서 재구성할 수 있어야 합니다. | [핵심 논리 ERD](docs/arrangement/01_DB_REDIS_DESIGN.md#3-논리-데이터-구조)는 관계를 빠르게 보여 주고, [전체 관계·schema 정본](docs/개발상세플랜/02_backend_data/AI_MAFIA_DB_DESIGN.md#3-관계-개요)은 상세 제약을 정의합니다. |
| 상태 변경 | 모든 command는 소유권·phase·actor·target·window·deadline·`state_version`을 검사합니다. `Idempotency-Key`와 영구 receipt가 재전송의 중복 반영을 막습니다. | 상태·event·snapshot·receipt는 한 PostgreSQL transaction에서 함께 commit하며, 외부 LLM·MCP 호출 중에는 DB transaction이나 Redis lock을 잡지 않습니다. |
| API·동기화 | 변경은 단일 command endpoint, 읽기는 authoritative snapshot을 사용합니다. 실시간 갱신은 같은 operation batch를 SSE와 polling에 공통 적용하고 sequence gap이면 전체 snapshot으로 복구합니다. | Front는 Backend 공개 HTTP API만 호출하며 DB·Redis·LLM·raw MCP Tool에 직접 접근하지 않습니다. |
| AI·MCP | Backend가 actor별 `public`·`me`·`turn`·`persona` 문맥을 만들고, LLM은 현재 허용된 구조화 행동만 제안합니다. 현재 FastMCP는 이 문맥과 역할 지침을 전달하고 행동을 Backend에 위임하는 얇은 adapter입니다. | 모델 응답은 미확정 제안입니다. Backend가 형식·대상·상태를 다시 검증한 뒤에만 적용하며 MCP runtime은 DB·Redis·LLM에 직접 접근하지 않습니다. |
| 화면 | 사용자 앱은 생성·역할 공개·게임·관전·결과·피드백을, 관리자 앱은 KPI·피드백·감사·공개 발언 분석을 제공합니다. UI는 snapshot과 `legal_actions`를 표현하고 규칙을 추론하지 않습니다. | countdown은 표시용이며 서버 deadline이 기준입니다. 비공개 정보는 해당 actor 화면에만 두고, 관리자 API도 allowlist 기반 read-only로 제한합니다. |
| 보안·운영 | 브라우저 UUID는 편의용 식별자일 뿐 강한 인증이 아닙니다. prompt·raw 모델 응답·chain-of-thought·secret과 다른 actor의 private context는 공개 응답·cache·로그에서 제외합니다. | 현재 배포 경계는 개인 개발 환경 또는 접근이 통제된 사설망입니다. 공개 인터넷 배포 전에는 별도 인증·TLS·네트워크 접근 통제가 필요합니다. |

### 요청부터 화면 반영까지

| 흐름 | 처리 순서 |
| --- | --- |
| 사용자 행동 | Front 입력 → 공개 API 검증 → 게임 행 잠금·Game Engine 적용 → PostgreSQL commit → snapshot/SSE·polling 반영 |
| AI 행동 | Backend job 선택 → MCP actor 문맥 조회 → LLM 구조화 제안 → Backend 재검증 → 게임 원장 반영 또는 결정적 fallback |
| 장애 복구 | 중복 요청은 receipt replay → 낡은 화면·늦은 AI 결과는 version/window 검증으로 거부 → Redis·SSE 장애는 PostgreSQL snapshot으로 복구 |
| 저장·재개 | 확정 상태와 timed window의 남은 시간을 저장 → 재개 시 같은 phase·결과·RNG를 유지하고 새 서버 deadline만 계산 |

정본 문서에는 후속 확장 목표도 포함될 수 있습니다. **현재 동작 여부는 이 README와
[현재 코드 상태 보고서](docs/개발상세플랜/05_reports/AI_MAFIA_CURRENT_CODE_STATUS.md)를 함께 확인**하고,
계약이 충돌하면 `AGENTS.MD`와 영역별 정본을 우선합니다.

<a id="agents"></a>

## 01 · 공개 대화는 함께, 의사결정은 각자

> **각 에이전트는 다른 에이전트의 비공개 컨텍스트·내부 추론·미공개 선택을 공유하지 않습니다.**
> 같은 공개 사건과 대화를 관찰하더라도, 자기 역할·개인 기록·페르소나를 바탕으로 개별 판단합니다.

독립성은 **판단 입력과 행동 주체의 분리**를 뜻합니다. AI마다 별도 프로세스나 별도 모델을
띄우는 구조는 아닙니다. 같은 Provider·모델 설정을 사용하되, 매 판단마다 actor별 새
컨텍스트와 메시지 묶음을 구성합니다. 타인의 공개 발언은 함께 읽는 **주장**이지,
그 AI의 비공개 조사 기록을 전달받은 것이 아닙니다.

### 한 번의 판단은 어떻게 게임에 반영될까?

```mermaid
flowchart TD
    W["① Backend worker<br/>차례 · actor · window 선택"]
    C["② MCP 문맥 조회<br/>public · me<br/>turn · persona"]
    I["③ 본인 입력 구성<br/>역할 · 말투 · 공개 이력"]
    L["④ LLM 개별 요청<br/>발언 · 투표 · 밤 선택"]
    V["⑤ Backend 제안 검증<br/>형식 · 행동 · 대상 확인"]
    E["⑥ Backend 게임 적용<br/>규칙 검증 · 저장·확정"]
    W --> C --> I --> L --> V --> E
    classDef input fill:#e0f2fe,stroke:#0284c7,color:#0c4a6e
    classDef decision fill:#ede9fe,stroke:#7c3aed,color:#4c1d95
    classDef authority fill:#dcfce7,stroke:#16a34a,color:#14532d
    class W,C,I input
    class L decision
    class V,E authority
```

모델은 구조화된 행동 제안을 반환합니다. 검증 실패 시 한 번의 교정 또는 fallback을
시도하며, **제안 생성 성공과 게임 반영 성공은 다릅니다.** 최종 적용은 Backend의
상태 버전·행동 창·대상·마감 검증을 통과해야 합니다. 위 도식은 내부 추론 원문이 아닌
관찰 가능한 실행 단계이며, 화면에는 제한된 공개 판단 근거 요약만 표시합니다.

| AI에게 전달되는 scope | 내용 | 다른 AI와의 관계 |
| --- | --- | --- |
| `public` | 공개 상태·명부·대화·확정 사건 | 같은 상태에서는 공통 관찰 가능 |
| `me` | 본인 역할·본인 조사 결과·확정된 개인 기록 | 다른 AI의 `me`를 공유하지 않음 |
| `turn` | 현재 허용 행동·대상·행동 창·마감 | 해당 actor의 행동 범위만 적용 |
| `persona` | 본인 말투·배경·성격 수치와 지침 | 본인에게 배정된 페르소나로 입력 구성 |

현재 MCP의 모델용 projection은 사건 배경 서사와 개인 `alibi`·`observation`을
제외하고 시나리오 ID·제목만 남깁니다. 공개 대화와 본인 조사 기록은 유지합니다.
마피아끼리도 동료의 정체를 자동으로 공유하지 않습니다.

<details>
<summary>실제 실행 방식과 코드 근거</summary>

| 행동 | 현재 실행 방식 |
| --- | --- |
| 발언 | 현재 AI 차례를 순차 처리. 정상 SPEAK/PASS는 MCP `submit_action`으로 제출 |
| 투표·재투표·최종 지목 | 미제출 AI의 판단을 병렬로 시작하고 완료된 표부터 Backend에 제출 |
| 밤 행동 | AI별 판단을 순차 생성해 모은 뒤 Backend에 제출. 판단 순서와 게임 규칙상 동시 확정은 별개 |

복구한 proposal이나 MCP 제출 장애의 발언은 최초 행동 창·버전을 유지해 Backend에 직접
제출할 수 있습니다. 따라서 **모든 AI 행동이 MCP Tool을 거치는 구조는 아닙니다.**

- [actor별 실행·행동 제출](backend/app/services/game/postgres_runtime.py)
- [컨텍스트·메시지 구성과 응답 검증](backend/app/agent/orchestrator.py)
- [Backend의 actor별 정보 투영](backend/app/services/game/actor_context.py)
- [MCP의 모델 입력 축약](mcp_server/mafia_game/api/resources/registry.py)
- [OpenAI 요청 구성](backend/app/llm_provider/openai_provider.py): 매 요청의 메시지, `store=False`, 공유 conversation 참조 없음

[StateGraph 아키텍처 문서](docs/AI_MAFIA_AGENT_ARCHITECTURE_DESIGN.md)는 **후속 도입 설계안**입니다.
현재 실행은 `AgentOrchestrator.run` 기반이며 StateGraph·지속 요약 메모리가 구현됐다는 뜻이 아닙니다.

</details>

<a id="system"></a>

## 02 · 메인 시스템은 어떻게 연결될까?

[![사용자·관리자 Front, Backend, MCP, LLM, PostgreSQL, Redis의 시스템 관계도](docs/diagrams/system-map.svg)](docs/diagrams/system-map.html)

[확대 가능한 HTML](docs/diagrams/system-map.html) · [SVG 이미지](docs/diagrams/system-map.svg) · [도식 원본](docs/diagrams/system-map.architecture.json)

HTML은 내려받아 브라우저에서 열 수 있습니다. GitHub 본문에서는 위 정적 이미지를 사용합니다.

| 시스템 | 책임 | 넘지 않는 경계 |
| --- | --- | --- |
| 사용자·관리자 Front · Streamlit | 게임 조작·화면·읽기 전용 운영 분석 | Backend HTTP API만 호출 |
| Backend · FastAPI | 게임 엔진, AI orchestration, 원장·이벤트, 발언 분석 | LLM 제안을 검증한 뒤 상태 변경 |
| MCP Server · FastMCP | actor별 Resource, 역할 지침, 행동 위임 Tool | DB·Redis·LLM에 직접 접근하지 않음 |
| LLM Provider | 입력에 따른 행동 제안·선택적 발언 분석 | 게임 상태나 승패를 직접 확정하지 않음 |
| PostgreSQL / Redis | 영구 원본 / 재구성 가능한 공개 대화 캐시 | 비공개 컨텍스트는 공유 공개 캐시에 넣지 않음 |

화살표는 요청 방향이며 응답은 반대 방향으로 돌아옵니다. Backend가 Provider를 직접
호출하고, MCP는 필요한 조회·행동을 Backend 내부 HTTP API에 위임합니다.

<a id="mcp"></a>

## 03 · MCP: 문맥을 읽고, 허용된 행동을 제안하기

현재 실행되는 최소 FastMCP 등록은 **Tool 3개 · Resource 템플릿 2개 · Prompt 1개**입니다.
등록부는 [tools](mcp_server/mafia_game/api/tools/registry.py),
[resources](mcp_server/mafia_game/api/resources/registry.py),
[prompts](mcp_server/mafia_game/api/prompts/registry.py)에서 확인할 수 있습니다.

### 실제 등록된 Tool

| Tool 이름 | 역할 | 검증·실행 주체 |
| --- | --- | --- |
| `submit_action` | `SPEAK`·`PASS`·`NIGHT_ACTION`·`VOTE` 제출 위임 | Backend `/internal/mcp/actions` |
| `manipulate_vote` | HUMAN의 `vote.triple.v1` 능력으로 본인 표를 3표로 제출 | Backend에서 소유권·능력·투표 창 확인 |
| `inspect_special_roles` | HUMAN의 `intel.special_roles.v1` 능력으로 다른 탐정·의사 조회 | Backend에서 소유권·능력·첫 밤 완료 확인 |

AI의 `propose_speech`, `propose_pass`, `propose_night_action`, `propose_vote`는
**내부 논리 행동명**입니다. 별도 wire Tool 4개가 아니며, MCP client가 허용 목록을
확인해 `submit_action`으로 매핑합니다. HUMAN 전용 커스텀 Tool은 AI의 권한을 늘리지 않습니다.

### Resource와 Prompt

| 등록 항목 | 접근 범위 |
| --- | --- |
| `mafia://context/current/{game_id}/{user_id}` | actor 없는 공개 컨텍스트 |
| `mafia://context/scoped/{game_id}/{user_id}/{player_id}/{scope}` | 해당 AI의 `public`·`me`·`turn`·`persona` |
| `agent_instruction` | 역할·단계별 지침 생성 Prompt. 운영 AI는 Resource에 포함된 역할·페르소나 지침도 사용 |

정본 API의 다섯 `mafia://session/*` Resource는 확장 계약이며 위의 현재 운영 템플릿과
구분합니다. 사용자 Front의 커스텀 능력 조작은 공개 Backend API로 들어가며 raw MCP를
직접 호출하지 않습니다.

<a id="quick-start"></a>

## 04 · 빠른 실행

Python 3.12+, 의존성 설치, 팀 DB·Redis·Provider 설정이 먼저 필요합니다.
처음이라면 [개발 환경 준비](#development)와 [환경 설정](#configuration)을 확인하세요.

```bash
./run_openai.sh --check  # 설정·import·팀 DB·Redis 준비 상태를 읽기 전용으로 확인
./run_openai.sh          # Backend·MCP·사용자 Front 실행
```

| 구성 | 기본 주소 | 실행 방식 |
| --- | --- | --- |
| 사용자 Front | `http://127.0.0.1:18501` | 통합 스크립트 |
| Backend | `http://127.0.0.1:18000` | 통합 스크립트 |
| MCP | `http://127.0.0.1:18100/mcp` | 통합 스크립트 |
| 관리자 Front | `http://127.0.0.1:18502` | 아래 실행 안내의 별도 명령 |

Windows는 `run_openai.bat --check` / `run_openai.bat`를 사용합니다.
Windows의 `--check`는 환경값 읽기·import만 확인합니다.
포트 변경·개별 실행·관리자 전용 실행은 [실행 안내](#running)를 참고하세요.

<a id="docker-deployment"></a>

### Docker Compose 배포

`docker-compose.yml`은 Docker Hub의 사전 빌드 이미지를 받아 PostgreSQL·Redis·Backend·
MCP·사용자 Front를 한 번에 실행합니다. 관리자 Front는 이 스택에 포함되지 않으며,
MCP 포트도 호스트에 공개하지 않습니다. 모든 이미지는 `linux/amd64`로 고정되어 있으므로
ARM 기반 PC에서는 Docker의 아키텍처 에뮬레이션을 사용하며 실행이 느릴 수 있습니다.

#### AI 에이전트에게 Docker 배포 맡기기

Claude Code, AmpCode, Cursor 같은 LLM 에이전트에서 이 저장소를 연 뒤 아래 프롬프트를
그대로 붙여넣으세요. 로컬 PC의 Docker Compose 배포를 기준으로 하며, 실제 비밀값은
채팅에 붙여넣지 말고 `.env.deploy`에만 직접 입력합니다.

```text
이 저장소(https://github.com/encore-ai-campus/aio-01-p2-team4#docker-deployment)
의 AI 마피아 서비스를 Docker Compose로 안전하게 설치하고 배포해 주세요.

작업 전에 저장소 루트의 AGENTS.MD와 README.md의 "Docker Compose 배포" 절을 끝까지
읽고 그 지침을 우선 적용하세요. 현재 branch와 변경 파일을 먼저 확인하되, 기존 사용자
변경을 덮어쓰거나 되돌리지 마세요. 사용자 승인 없이 commit이나 push를 하지 마세요.

다음 순서로 진행하세요.

1. Docker Engine 또는 Docker Desktop이 실행 중인지, `docker compose`를 사용할 수
   있는지 확인하세요. 기본 포트 18501, 18000, 55432, 56379의 충돌 여부도 읽기 전용으로
   확인하세요.
2. 저장소 루트의 `.env.deploy.example`, `docker-compose.yml`과 이미지 구성을 확인하세요.
   `.env.deploy`이 없을 때만 예제 파일을 복사하고, 이미 있으면 절대 덮어쓰지 마세요.
3. `.env.deploy`의 `OPENAI_API_KEY`, `POSTGRES_MIGRATION_PASSWORD`,
   `POSTGRES_APP_PASSWORD`가 비어 있거나 예제값이면 진행을 멈추고 사용자가 파일에 직접
   입력하도록 안내하세요. 비밀값을 채팅, 명령 출력, 로그 또는 보고서에 표시하거나
   대신 생성하지 마세요. 두 PostgreSQL 비밀번호는 서로 달라야 합니다.
4. `docker compose --env-file .env.deploy config --quiet`로 구성을 검증한 뒤 아래 명령으로
   이미지를 받고 스택을 시작하세요.

   docker compose --env-file .env.deploy pull
   docker compose --env-file .env.deploy up -d
   docker compose --env-file .env.deploy ps

5. PostgreSQL·Redis·Backend·Frontend가 healthy이고 MCP가 Up인지 확인하세요. 이어서
   아래 endpoint를 확인하세요.

   curl http://127.0.0.1:18000/health
   curl http://127.0.0.1:18000/ready
   curl http://127.0.0.1:18501/_stcore/health

6. 실패한 경우 관련 서비스의 최근 로그만 최소 범위로 확인하고 비밀값·DSN·header·
   token은 출력에서 가리세요. 원인을 좁힌 뒤 안전한 설정 수정만 수행하고 다시 검증하세요.
7. 완료 시 실행한 명령, 서비스별 최종 상태, health 결과, 사용자 화면
   `http://127.0.0.1:18501`과 Backend 문서 `http://127.0.0.1:18000/docs`, 남은 문제를
   짧게 보고하세요. 실제 비밀값은 보고하지 마세요.

데이터 보호 규칙:
- `docker compose down -v`, `docker volume rm`, `docker system prune`, 데이터 디렉터리
  삭제처럼 PostgreSQL·Redis 데이터를 지우는 명령은 실행하지 마세요.
- 기존 named volume이 있으면 보존하세요. `.env.deploy`의 DB 비밀번호 변경만으로 기존
  volume의 계정 비밀번호가 바뀐다고 가정하지 마세요.
- 명시적 요청 없이는 포트를 외부 인터페이스에 공개하거나 reverse proxy·TLS·공개 인터넷
  배포로 범위를 넓히지 마세요. 기본 loopback 바인딩을 유지하세요.
- 새 migration이 필요한 기존 volume 업그레이드는 임의 실행하지 말고 README의 migration
  전략과 현재 적용 상태를 확인한 뒤 사용자에게 별도 작업으로 보고하세요.
```

직접 배포하려면 아래 1~4단계를 순서대로 진행합니다.

#### 1. 사전 준비

- Docker Engine 또는 Docker Desktop과 `docker compose` 명령
- Docker Hub 이미지 다운로드가 가능한 네트워크
- 유효한 OpenAI API key
- 기본 호스트 포트 `18501`, `18000`, `55432`, `56379`의 미사용 상태

저장소 루트에서 예제 파일을 실제 배포 설정으로 복사합니다. `.env.deploy`은 Git에서
제외되므로 실제 key와 비밀번호를 이 파일에만 저장하고, 예제 파일이나 README에는
기록하지 않습니다.

```bash
# macOS / Linux
cp .env.deploy.example .env.deploy
```

```powershell
# Windows PowerShell
Copy-Item .env.deploy.example .env.deploy
```

`.env.deploy`에서 다음 값을 확인합니다.

| 변수 | 설정 방법 |
| --- | --- |
| `OPENAI_API_KEY` | 반드시 실제 key 입력 |
| `POSTGRES_MIGRATION_PASSWORD` | 예제값 대신 충분히 긴 임의 값 입력 |
| `POSTGRES_APP_PASSWORD` | migration 계정과 다른 임의 값 입력 |
| `OPENAI_MODEL` | 선택 사항. 파일에 새 줄로 추가하지 않으면 `gpt-4.1-mini` 사용 |
| `FRONTEND_HOST_PORT`, `BACKEND_HOST_PORT` | 기본값은 `18501`, `18000`; 충돌할 때 변경 |
| `POSTGRES_HOST_PORT`, `REDIS_HOST_PORT` | 기본값은 `55432`, `56379`; 충돌할 때 변경 |

OpenAI key는 Backend 컨테이너에만 전달되며 Front·MCP·PostgreSQL·Redis 컨테이너나
이미지에는 포함되지 않습니다.

PostgreSQL 계정과 비밀번호는 데이터 볼륨을 처음 만들 때만 초기화됩니다. 기존 볼륨을
유지한 채 `.env.deploy`만 수정해도 DB 비밀번호가 자동으로 변경되지는 않습니다.

#### 2. 이미지 다운로드와 기동

```bash
docker compose --env-file .env.deploy pull
docker compose --env-file .env.deploy up -d
docker compose --env-file .env.deploy ps
```

Compose가 사용하는 이미지는 다음과 같습니다.

| 서비스 | 이미지 | 호스트 공개·저장 |
| --- | --- | --- |
| `frontend` | `shs5029/ai-mafia-frontend:latest` | `127.0.0.1:18501` |
| `backend` | `shs5029/ai-mafia-backend:latest` | `127.0.0.1:18000` |
| `mcp` | `shs5029/ai-mafia-mcp:latest` | Compose 내부 `mcp:8100`만 사용 |
| `postgres` | `shs5029/ai-mafia-postgres:latest` | `127.0.0.1:55432`, named volume에 원본 저장 |
| `redis` | `shs5029/ai-mafia-redis:latest` | `127.0.0.1:56379`, named volume에 AOF 저장 |

PostgreSQL 이미지는 **빈 볼륨의 최초 초기화 때만** `backend/migrations/*.sql`을 이름순으로
실행하고 DDL migration 계정과 DML 애플리케이션 계정을 분리합니다. 이미지 업데이트만으로
기존 볼륨에 새 migration이 적용되지는 않으므로, 기존 데이터를 유지하는 업그레이드는
[DB migration 전략](docs/개발상세플랜/02_backend_data/AI_MAFIA_DB_DESIGN.md#9-migration-전략)에
따라 별도 실행·검증해야 합니다.

#### 3. 배포 확인과 장애 확인

`docker compose ps`에서 PostgreSQL·Redis·Backend·Frontend가 `healthy`, MCP가 `Up`인지
확인한 뒤 다음 주소를 점검합니다.

```bash
curl http://127.0.0.1:18000/health
curl http://127.0.0.1:18000/ready
curl http://127.0.0.1:18501/_stcore/health
```

- 사용자 화면: `http://127.0.0.1:18501`
- Backend API 문서: `http://127.0.0.1:18000/docs`
- `/ready`는 PostgreSQL과 Redis 연결이 모두 정상일 때만 HTTP 200을 반환합니다.
- LLM Provider와 MCP는 게임 중 fallback 대상이므로 `/ready` 판정에는 포함되지 않습니다.

서비스가 준비되지 않으면 비밀값을 출력하지 않는 범위에서 상태와 최근 로그를 확인합니다.

```bash
docker compose --env-file .env.deploy ps
docker compose --env-file .env.deploy logs --tail=100 postgres redis backend mcp frontend
```

#### 4. 업데이트·재시작·중지

새 이미지를 반영할 때는 pull 후 스택을 다시 적용합니다. named volume은 유지됩니다.

```bash
docker compose --env-file .env.deploy pull
docker compose --env-file .env.deploy up -d
```

설정 변경 뒤 특정 서비스만 다시 만들려면 다음과 같이 실행합니다.

```bash
docker compose --env-file .env.deploy up -d --force-recreate backend
```

서비스만 중지하고 데이터를 보존하려면 `down`을 사용합니다.

```bash
docker compose --env-file .env.deploy down
```

아래 명령은 PostgreSQL·Redis named volume과 저장 데이터를 함께 삭제합니다. 테스트 데이터를
의도적으로 초기화할 때만 실행하며 복구할 데이터가 있으면 먼저 백업합니다.

```bash
docker compose --env-file .env.deploy down -v
```

#### 네트워크와 보안 범위

기본 포트는 모두 `127.0.0.1`에 바인딩되며 Front의 브라우저 통신 주소도
`http://127.0.0.1:18000`입니다. 따라서 기본 Compose 파일은 **Docker를 실행한 같은 PC에서
접속하는 로컬 배포용**입니다. 원격 사설망이나 reverse proxy 배포에는 공개 bind 주소,
브라우저에서 접근 가능한 Backend URL, TLS와 접근 제어를 함께 설계해야 합니다.

이 MVP는 UUID를 사용자 구분값으로만 사용하고 현재 최소 MCP도 별도 인증을 제공하지
않으므로 공개 인터넷에 그대로 노출하지 않습니다. 관리자 allowlist 역시 공개 배포용
인증을 대신하지 않습니다. 자세한 내용은 [보안과 제약](#security)을 참고하세요.

#### Docker 빌드 컨텍스트

루트에서 이미지를 직접 빌드할 때는 반드시 저장소 루트를 build context(`.`)로 사용합니다.
`.dockerignore`는 실제 환경 파일·secret, 가상환경·캐시·로그를 제외하고 Dockerfile이
필요한 소스와 migration을 유지합니다. 서비스별 Dockerfile은 `docker/backend/`,
`docker/frontend/`, `docker/mcp/`, `docker/postgres/`, `docker/redis/`에 있습니다.

<a id="features"></a>

## 05 · 플레이와 관찰

| 플레이 | 커스텀 직업 | 운영 분석 |
| --- | --- | --- |
| 토론 → 밤 행동 → 투표 → 승패 | 인간 플레이어의 진영·직업명·능력 조합 | 게임 KPI·승률·피드백·감사 로그 |
| 저장·재개, 관전, 게임 기록 | 5개 능력 중 1~3개 선택 | 공개 AI 발언의 유사 주제·키워드·근거 |

아래 항목을 펼치면 현재 동작과 제약을 확인할 수 있습니다.

<details>
<summary>게임 규칙 · mystery-v1 / scenario-v1</summary>

### 게임 규칙 (mystery-v1 · scenario-v1)

- 전체 6~9명, 탐정·의사·시민과 서로 정체를 모르는 마피아
- 첫날 낮은 1분 45초 자유 채팅 후 무투표로 밤에 진입
- 첫날(Day 1)은 인간·AI 모두 발언 PASS 금지. AI 생성·MCP 조회 실패 시에는 사실을
  단정하지 않는 짧은 질문을 사용합니다. 확인한 공개 이력의 질문은 중복을 피하고,
  준비된 질문을 모두 사용하면 가장 오래된 질문부터 재사용하며, 이력이 없으면
  게임·AI·발언 창별로 결정적으로 선택합니다. 이력 조회 자체가 실패하면
  중복 방지를 보장할 수 없습니다. 둘째 날 이후 PASS 규칙은 유지합니다
- 정상 생성한 대사는 MCP 제출 실패만으로 기본 대사로 바꾸지 않습니다. 최초 상태
  버전·발언 창으로 같은 대사를 재제출하며, 이미 처리됐거나 차례가 바뀌면 기존 검증이 거부합니다
- 게임·관리자 API의 동기 DB 작업은 별도 스레드에서 실행합니다. 브라우저 조회나
  관리자 집계가 오래 걸려도 공용 이벤트 루프와 MCP 응답 처리를 막지 않습니다
- 발언은 200자 이하, 플레이어별 최근 1분에 최대 7회. 밤 행동은 30초·투표는 30초의
Backend 권위 deadline
- 다섯 개 시나리오와 플레이어별 알리바이·관찰 정보를 검증된 seed 기반
카탈로그로 배정하고 사용자별 직전 시나리오 제외
- 최대 다섯째 밤 뒤 표준 승패가 없으면 최종 지목으로 종료
- 투표·재투표·최종 지목은 모든 미제출 AI가 병렬로 판단하고 완료된 표부터 저장
- 투표는 후보별 집계만 공개하고 밤 사망 역할은 숨기며 처형 역할만 공개
- AI GM은 공개 확정 이벤트만 받고 전체 비공개 상태는 Backend만 보유
- 저장한 게임은 이어서 재개할 수 있고, 사용자는 진행·저장 게임을 수동으로 삭제할 수 있습니다
- 저장·재개로 상태 버전이 바뀐 AI 발언은 기존 lease가 만료되고 같은 발언 창이 열려
  있으며 미제출인 경우 새 예약으로 다시 생성합니다. 이전 결과는 재사용하지 않고,
  유효 lease의 중복 예약과 이전 worker의 늦은 완료는 계속 거부합니다
- `IN_PROGRESS` 게임은 마지막 사용자 command 뒤 15분간 새 사용자 command가 없으면
중앙 worker가 자동 삭제합니다(SAVED·COMPLETED·FAILED는 자동 삭제하지 않음)

</details>

<details>
<summary>사용자 전용 커스텀 직업 · 능력 카탈로그와 공개 범위</summary>

### 사용자 전용 커스텀 직업 (CUSTOM_ROLE)

새 게임 화면에서 기본 `STANDARD` 또는 인간 한 명만 자유 직업을 갖는 `CUSTOM_ROLE`을
선택합니다. 커스텀 생성은 `mode=CUSTOM_ROLE`과 `custom_role`의 `name`, `faction`
(`CITIZEN`/`MAFIA`), `catalog_version=custom-role-v1`, 중복 없는 `ability_ids` 1~3개를
보냅니다. 직업명은 NFC·공백 정규화 후 1~40자의 일반 표시 문자열이며 prompt로 사용하지
않습니다. 기존 마피아 총수와 AI 탐정·의사 구성을 유지하고 승패는 저장 진영으로 판정합니다.

`GET /api/v1/game-config/custom-role-abilities`를 `X-User-Id`로 조회하며 catalog는
다음 다섯 항목으로 고정됩니다. Front는 ID·label·진영 배열의 누락·중복·미지 항목을
거부하고 안전한 재시도를 제공합니다.

| 능력 ID | label | factions | 동작 |
| --- | --- | --- | --- |
| `night.attack.v1` | 공격 | `[MAFIA]` | 자신 외 생존자 공격 |
| `night.investigate.v1` | 조사 | `[CITIZEN, MAFIA]` | 자신 외 생존자의 진영 조사 |
| `night.protect.v1` | 보호 | `[CITIZEN, MAFIA]` | 자신을 포함한 생존자 보호 |
| `vote.triple.v1` | 투표 조작 | `[CITIZEN, MAFIA]` | DAY_VOTE·REVOTE에서 본인의 한 표를 3표로 제출 |
| `intel.special_roles.v1` | 특수 직업 열람 | `[CITIZEN, MAFIA]` | 첫 밤 종료 후 다른 탐정·의사 조회 |

시민은 공격을 선택할 수 없고, 마피아는 공격을 반드시 포함합니다. 밤 능력이 여러 개여도
매일 밤 `me.ability_options`에서 **하나만** 선택해 대상과 `SUBMIT_NIGHT_ACTION`의
`ability_id`를 제출합니다. 낮/조회 능력만 가진 시민은 밤 제출 대상에서 제외됩니다.
STANDARD는 기존 역할 배정·밤 제출을 유지하며 능력 ID를 보내지 않습니다.

생존한 능력 보유자는 DAY_VOTE·REVOTE 화면에서 일반 1표 또는 능력 3표를 선택합니다.
능력 선택은 공개 `SUBMIT_VOTE`에 `ability_id=vote.triple.v1`을 함께 보내며 창당 첫
유효 제출만 받습니다. 누적 강화는 없고 일반·자동 투표·FINAL_ACCUSATION은 1표입니다.
최종 지목에는 능력 선택을 표시하지 않습니다. 원장의 능력 ID로 재개 후 같은 가중치를
복원하며 공개 집계에는 후보별 가중 합계만 제공합니다.

특수 직업 열람은 생존한 CUSTOM_ROLE HUMAN 능력 보유자의 `IN_PROGRESS` 게임에서
`day_number >= 2`일 때 본인 private panel로 제공합니다. Front는
`GET /api/v1/games/{game_id}/special-roles`에 `X-User-Id`를 보내고, Backend는 기존
읽기 service에서 소유권·능력·상태를 검증합니다. 응답은 공통 success envelope와
`Cache-Control: no-store`를 사용하며 소유권 불일치 404, 능력 불일치 403,
상태·해금 조건 불충족 409도 저장하지 않습니다. 사망자를 포함한 다른 탐정·의사만
반환하고 밤 행동 횟수를 소모하지 않습니다. 실패·identity/game/state 변경·사망·종료 시
Front 결과를 폐기하고 늦은 응답도 차단합니다. AI context·공개 명부·timeline·analytics·
공유 cache에 복제하지 않습니다.

역할 공개에는 본인 직업명·진영·능력을 표시하고, 공개 자유 직업명은 처형 또는 종료
후에만 표시합니다. 종료 화면은 custom `role_name`·`faction`을 우선하며 표시 문자열을
escape합니다. private 조회 결과를 종료 결과에 합치지 않습니다.

Front는 raw MCP Tool을 직접 호출하지 않습니다. 세 밤 능력은 logical
`propose_night_action` 계약을 참조하며 기존 wire Tool은 `submit_action`입니다.
내부 `manipulate_vote`는 `/internal/mcp/actions`에 투표 능력 ID를 고정 전달하고,
`inspect_special_roles`는 `/internal/mcp/special-roles`로 위임합니다. 공개 조회는 MCP를
경유하지 않습니다. MCP는 DB·Redis에 직접 접근하지 않고 AI Tool 권한을 확대하지
않으며 기존 UUID 소유권·loopback 신뢰 경계를 유지합니다.

코드 연결은 WU-B16·F11·M10·B17·F12에 반영됐고, 팀 DB의 010·011은
2026-09-08에 적용했습니다. 현재 통합 검증 결과는 아래 테스트 절을 따릅니다.

</details>

<details>
<summary>AI 플레이어 · 페르소나, 전략, timeout과 fallback</summary>

### AI 플레이어

- 역할(시민·탐정·의사·마피아)별 전략과 승리 계획은 MCP의 역할 지침이 제공하고,
  기본 모델 설정과 정보 접근 정책은 동일합니다. 실제 비공개 정보는 각 AI 본인에게 한정됩니다
- 성격(preset)별 `speech_style`·`backstory`·`parameters`는 team DB의
  `agent_personas`에 배정된 값을 모델에 그대로 전달합니다
- AI는 상대 답변에 대한 인정·반박·정정과 조건부 협력을 섞고, 의심 대상과 설득할
  상대를 구분하도록 안내합니다. 모든 성격에 도발을 강제하지 않으며 말투·감정 표현은
  배정된 페르소나와 상황에 맞춥니다
- 마피아는 사실과 필요한 왜곡을 섞어 신뢰·표를 확보하고, 시민 진영은 오처형 위험을
  고려해 미끼 주장을 사용합니다. 탐정은 조사 공개 시점, 의사는 보호 계획의 노출,
  마피아는 공격과 낮 처형의 이득을 비교합니다. 실제 기록·타인의 주장·자신의 블러핑을
  구분하며 역할·허용 행동·정보 권한과 첫날 SPEAK 의무는 유지합니다. 프롬프트 지침이므로
  실제 대화 품질이나 승률 개선을 보장하지는 않습니다
- 문구는 `mcp_server/mafia_game/api/prompts/instructions.py`에서 관리합니다.
  실행 중인 MCP는 재시작해야 바뀐 지침을 다음 AI 판단부터 전달합니다
- Backend 중앙 AI worker가 열린 AI 차례(발언·밤·투표)를 비동기로 회복하며,
  LLM·MCP 호출 실패 시에만 같은 규칙의 결정적 fallback을 사용합니다
- AI 판단 단계(정보 확인 → 판단 → 선택 → 적용)와 제한된 공개 판단 근거 요약을
  게임 화면에서 확인할 수 있습니다
- Agent 예약은 최대 40초이며 실제 게임 창 마감을 넘지 않습니다. MCP 조회·최초
  모델 요청·교정 요청이 같은 잔여 시간을 사용하고 완료·제출용으로 3초를 남깁니다.
  요청 취소를 삼킨 늦은 응답도 거부하며, 시작할 시간이 없으면 추가 요청 없이 폐기합니다
- `FALLBACK`은 예약 완료가 승인된 대체 선택이며 실제 반영은 `APPLIED`와 DB event로
  확인합니다. 만료·fencing 거부로 버린 시도는 `FALLBACK PASS` 선택으로 기록하지 않습니다.
  `AGENT_GENERATION_FAILED` 내부 진단은 비공개 actor·원문 없이 고정 실패 코드만 남깁니다

</details>

<details>
<summary>사용자·관리자 화면 · 발언 임베딩 분석</summary>

### 화면

- **사용자 앱**: UUID 자동 생성, 홈(게임 목록·이어하기), 새 게임 생성·역할 공개,
  게임 진행·관전, 결과·게임 기록, 일반·게임별 피드백
- 토론 입력은 Enter로 순서대로 예약하며 실시간 대화·상태 갱신 중에도 유지합니다.
  밤·투표는 선택 입력과 시계 갱신을 분리하고, 홈 이동 시 저장·이탈 확인을 제공합니다.
  탐정의 조사 결과는 본인 화면에서만 별도로 표시합니다
- **관리자 앱**(read-only): 게임 KPI·진영별 승률·페르소나별 AI 승률, 사용자 피드백,
  관리자 감사 로그와 공개 AI 발언 분석을 네 탭으로 표시하고 30초마다 갱신합니다.
  **관리자 로그 → AI Agent 행동**에서는 팀 DB `public.agent_jobs`의 작업을
  `GET /api/v1/admin/agent-jobs`로 조회합니다. 작업 종류·처리 상태·게임 UUID로
  필터링하고 최근 생성순으로 20건씩 이전/다음 페이지를 이동할 수 있습니다.
  에이전트 이름·생성/완료 시각·실패 코드·작업 식별자를 표시하며, 잘못된 UUID는
  안내와 빈 목록을 표시합니다. 기존 관리자 조회 이력은 같은 페이지에서 선택합니다.
  작업당 현재 상태 한 건이며 결과 생성 성공·대체 결과 생성은 게임 반영 완료와
  다릅니다. 제안 원문·선택 대상·역할·예약 토큰은 조회하지 않습니다.
  기존 테이블을 사용하므로 추가 migration은 필요하지 않습니다.
  발언 분석은 `speech_analysis` 임베딩으로 유사 주제를 묶고 원문 키워드·stance·
  대표 근거를 함께 보여 줍니다. 운영 에이전트 계획 탭은 제거됐으며 질문 API는
  Backend 독립 계약으로 유지합니다
- 공개 발언의 실시간 임베딩·주장 분석과 투표 보조 정보 표시(선택 기능,
  기본 비활성)

</details>

<a id="development"></a>

## 06 · 개발·운영 가이드

제품 범위는 [공통 마스터플랜](docs/개발상세플랜/01_core/AI_MAFIA_MASTER_PLAN.md)이 기준입니다.
작업 전에 [AGENTS.MD](AGENTS.MD)의 WU 범위·브랜치·승인·검증 규칙을 읽으세요.
아래 접이식 안내는 설치·운영 명령과 기존 검증 기록을 보존합니다.

<details>
<summary>정본과 설계 문서 찾아보기</summary>

### 개발 문서

전체 분류와 권장 읽기 순서는 [개발 문서 안내](docs/개발상세플랜/README.md)를 참고하세요.

| 문서 | 기록된 내용 |
| --- | --- |
| [핵심 논리 ERD](docs/arrangement/01_DB_REDIS_DESIGN.md#3-논리-데이터-구조) | 사용자·게임·플레이어·행동 창·제출·이벤트·snapshot·receipt·Agent 작업의 핵심 관계도 |
| [AI_MAFIA_MASTER_PLAN.md](docs/개발상세플랜/01_core/AI_MAFIA_MASTER_PLAN.md) | 제품 규칙, 시나리오, 아키텍처, 보안 경계, 섹터 소유권, WU/CP 정본 |
| [AI_MAFIA_DB_DESIGN.md](docs/개발상세플랜/02_backend_data/AI_MAFIA_DB_DESIGN.md) | PostgreSQL·Redis schema, transaction, lock, migration과 보존 계약 |
| [AI_MAFIA_API_SPEC.md](docs/개발상세플랜/01_core/AI_MAFIA_API_SPEC.md) | 일반·관리자·내부 Engine HTTP API와 MCP Resource·Tool 계약 |
| [AI_MAFIA_MCP_SERVER_DESIGN.md](docs/개발상세플랜/03_mcp_agent/AI_MAFIA_MCP_SERVER_DESIGN.md) | MCP runtime 구조, 보안 경계와 WU-M1A~WU-M8 실행·검증 계획 |
| [AI_MAFIA_SCREEN_FLOW.md](docs/개발상세플랜/04_frontend/AI_MAFIA_SCREEN_FLOW.md) | UUID 초기화, 사용자 게임·관전·피드백과 관리자 화면 흐름 |
| [AI_MAFIA_FRONTEND_TECHNICAL_DESIGN.md](docs/개발상세플랜/04_frontend/AI_MAFIA_FRONTEND_TECHNICAL_DESIGN.md) | Streamlit Front 전용 WU-F1~F10 기술 설계 |
| [AI_MAFIA_FRONTEND_BACKEND_HANDOFF.md](docs/개발상세플랜/04_frontend/AI_MAFIA_FRONTEND_BACKEND_HANDOFF.md) | Frontend–Backend 공개 API, SSE·CORS, 오류·private 경계 요약 |
| [AI_MAFIA_INDEPENDENT_CONTRACT.md](docs/개발상세플랜/01_core/AI_MAFIA_INDEPENDENT_CONTRACT.md) | 세 섹터 독립 구현 시 공통 최소 연결 형식·경계 |
| [AI_MAFIA_GAME_ENGINE_STRATEGY_DRAFT.md](docs/개발상세플랜/02_backend_data/AI_MAFIA_GAME_ENGINE_STRATEGY_DRAFT.md) | 게임 엔진·Agent Manager 모듈화 전략 임시 초안 |
| [AI_MAFIA_CURRENT_CODE_STATUS.md](docs/개발상세플랜/05_reports/AI_MAFIA_CURRENT_CODE_STATUS.md) | 현재 실제 코드 구조, 게임 흐름, 공개 API, 설정, 검증 결과와 제약 |
| [AI_MAFIA_CUSTOM_ROLE_MCP_TOOLS_SUMMARY.md](docs/개발상세플랜/05_reports/AI_MAFIA_CUSTOM_ROLE_MCP_TOOLS_SUMMARY.md) | 사용자 전용 투표 조작·특수 직업 열람 툴의 구현·검증·남은 적용 작업 요약 |
| [AI_MAFIA_AGENT_ARCHITECTURE_DESIGN.md](docs/AI_MAFIA_AGENT_ARCHITECTURE_DESIGN.md) | StateGraph 도입안: 분기·기억·도구·공유 상태·종료 조건 |

확장 계약의 다섯 MCP Resource 상세 `data` schema는 API 명세 8.2절만 정본입니다.
현재 운영 등록 목록은 위 MCP 절과 API 명세 상단의 최소 운영 프로파일을 함께 참고하세요.
날짜별 변경·검증 내역은 [90_history](docs/개발상세플랜/90_history/)를 참조하세요.

15분 프로젝트 발표 자료를 **16장·16:9·한국어 발표자 노트**로 완성했습니다.
[PPTX](docs/ai_mafia_15min/ai_mafia_15min.pptx),
[PDF 미리보기](docs/ai_mafia_15min/ai_mafia_15min.pdf),
[발표 대본](docs/ai_mafia_15min/speech.md),
[장별 시간표·구성안](docs/ai_mafia_15min/outline.md)을 함께 제공합니다.
사용자가 승인한 흰색·연보라·남색의 ‘밝은 테크 스타일’과 내장 ImageGen을 사용했습니다.
다섯 서버가 각각 별도 환경에서 실행 중인 상황은 ‘분산 실행 가정’으로 표현했습니다.
실제 게임·커스텀 직업·관리자 화면 8개는 사용자 승인에 따라 원본 JPEG를 PowerPoint
이미지로 직접 삽입했습니다. 화면·도식의 배경은 이미지형이며 발표자 노트는 편집할 수 있습니다.
현재 인간 전용 커스텀 능력과 후속 AI Tool 구성, PostgreSQL 배열 기반 발언 분석과
pgvector·RAG 확장도 구분했습니다. 팀 DB의 색인 적용 여부는 2026-09-09 캡처·조사
시점 기준이며, 현재 검색 답변 코드의 LLM 생성 연결은 후속 범위로 설명합니다.
[근거·캡처 기록](docs/ai_mafia_15min/sources.md)과
[제작·검증 기록](docs/ai_mafia_15min/qa_report.md)에 상세 경로·생성 출처·검증 범위를 남겼습니다.
16장 렌더, 노트 일치, 원본 화면 바이트 일치, 도형 경계를 확인했습니다.
이 발표 자료 작업에서는 애플리케이션 코드를 변경하지 않아 자동 회귀 테스트를 생략했습니다.

</details>

<details>
<summary>프로젝트 구조와 README 도식 관리</summary>

### 프로젝트 구조

```text
.
├── AGENTS.MD                         # 개발·기여 작업 규칙
├── README.md                         # 전체 설정·실행·검증 안내
├── .env.example                      # Backend 환경 변수 예시
├── .env.deploy.example               # 전체 Docker 스택 배포 변수 예시
├── .env.docker.example               # Docker DB·Redis 변수 점검용 예시
├── .dockerignore                     # Docker build context의 비밀·산출물 제외 규칙
├── docker-compose.yml                # PostgreSQL·Redis·Backend·MCP·사용자 Front 통합 실행
├── run_openai.sh                     # macOS/Linux용 OpenAI Backend·MCP·Front 동시 실행
├── run_openai.bat                    # Windows용 PowerShell 실행 진입점
├── run_openai.ps1                    # Windows용 OpenAI Backend·MCP·Front 실행 로직
├── pyproject.toml                    # ai-mafia 통합 런타임·개발 의존성 및 도구 설정
├── docker/                            # 서비스 이미지 정의와 데이터 서비스 초기화 설정
│   ├── backend/Dockerfile             # FastAPI Backend 이미지
│   ├── frontend/Dockerfile            # Streamlit 사용자 Front 이미지
│   ├── mcp/Dockerfile                 # FastMCP 서버 이미지
│   ├── postgres/                      # pgvector 기반 DB 이미지와 최초 초기화 스크립트
│   └── redis/                         # AOF를 사용하는 Redis 이미지와 설정
├── backend/
│   ├── app/main.py                   # FastAPI 생성과 router·오류 처리 등록
│   ├── app/routers/                  # health·공개 게임·내부 Engine endpoint
│   ├── app/schemas/                  # 요청·응답 validation 계약
│   ├── app/services/                 # UUID 사용자·게임 유스케이스
│   │   └── game/                     # 게임 업무 Service·공용 계약
│   ├── app/models/identity.py        # UUID 내부 사용자 모델
│   ├── app/repositories/             # PostgreSQL CRUD·row 변환 저장소
│   ├── app/infrastructure/           # migration·PostgreSQL·내부 HMAC 구현
│   ├── app/agent/                    # Agent activity·projection·orchestration
│   ├── app/game_engine/              # 순수 게임 규칙·phase·결정적 RNG 정본 package
│   ├── app/llm_provider/             # 현재 LLM Provider adapter
│   ├── app/mcp/                      # Backend Agent용 MCP context client
│   ├── migrations/                   # Backend 작성 SQL migration(MCP 실행, 001~012)
│   ├── tests/                        # Agent 시험 보고서 전용 행동·오류 회복 반복 검증 2개 파일
│   ├── logs/                         # 실행 시 생성되는 순환 진행 로그 (Git 제외)
│   └── README.md
├── frontend_user/
│   ├── app.py                        # UUID bootstrap·화면 dispatcher
│   ├── app_pages/                    # 홈·생성·역할 공개·게임·결과·피드백·설정 화면
│   ├── components/                   # identity bridge·테마·투표 보조 등 공통 UI
│   ├── core/                         # identity·session·api_client·sync
│   ├── assets/                       # 사용자 화면 이미지·맵·결과 배경
│   ├── tests/, pytest.ini            # 현재 남아 있는 사용자 Front 회귀 테스트
│   ├── .streamlit/secrets.toml.example
│   └── README.md
├── frontend_admin/
│   ├── app.py                        # read-only 관리자 앱 진입점
│   ├── app_pages/                    # 대시보드·게임 목록·상세 화면
│   ├── components/                   # 관리자 UI·브라우저 연동 컴포넌트
│   ├── core/                         # 관리자 API client·식별·응답 모델
│   └── README.md
├── mcp_server/
│   ├── pyproject.toml, uv.lock       # Python 3.12·MCP SDK 1.29.1 독립 실행 환경
│   └── mafia_game/
│       ├── main.py, __main__.py      # FastMCP 조립·실행 진입점
│       ├── api/                      # Prompt·Resource·Tool 등록부
│       ├── integrations/             # Backend 내부 HTTP adapter
│       ├── schemas/                  # MCP wire 입력·응답 검증
│       └── README.md
├── docs/
│   ├── arrangement/                  # 프로젝트 기획·Agent 평가·현재 구현 기준 시스템·영역별 설계·세부 구현 계획
│   ├── diagrams/                     # README 시스템 관계도 원본·HTML·SVG·검증 근거
│   ├── ai_mafia_15min/               # 16장·15분 PPTX/PDF·대본·구성안·검증 기록
│   │   ├── assets/screenshots/      # 실제 게임·관리자 화면 원본 8개
│   │   ├── origin_image/            # 내장 ImageGen 슬라이드 배경 16개
│   │   ├── prompts/                 # 슬라이드별 생성 작업과 참조 이미지 정보
│   │   └── insert_original_screens.py # 승인된 원본 화면의 PPT 이미지 삽입
│   ├── AI_MAFIA_AGENT_ARCHITECTURE_DESIGN.md # Agent StateGraph 도입 설계
│   └── 개발상세플랜/                  # 카테고리별 개발 문서 통합 위치
│       ├── README.md                  # 문서 목록·우선순위·권장 읽기 순서
│       ├── 01_core/                   # 제품·공통 계약·API 정본
│       ├── 02_backend_data/           # Backend·DB·게임 엔진 설계
│       ├── 03_mcp_agent/              # MCP runtime·Agent 설계
│       ├── 04_frontend/               # 화면·Frontend·Backend 인계 설계
│       ├── 05_reports/                # 구현 현황·실행·검증 보고서
│       ├── 90_history/                # 날짜별 변경·검증 기록
│       └── 99_archive/                # 현재 정본이 아닌 과거 임시 자료
└── scripts/                          # 운영·개발 보조 스크립트
```

관계도는 `docs/diagrams/system-map.architecture.json`을 Archify로 검증·생성한
`system-map.html`과 그 뷰어에서 내보낸 `system-map.svg`를 사용합니다.
도식 본문은 한국어이며 Archify의 고정 뷰어 UI와 HTML 언어 표시는 영어로 남습니다.
생성물의 검증·바이트 식별 정보는 [도식 검증 기록](docs/diagrams/validation.md)에 보존합니다.

2026-09-09 정리에서 테스트 소스와 캐시, 비어 있는 디렉터리·`__init__.py`,
참조되지 않던 Backend Agent/MCP 예약 모듈, 실행 코드가 없던 `mcp_2`, 현재 실행 경로와
분리된 과거 MCP 계층을 제거했습니다. Python `Protocol`의 `...`와 예외 정리용 `pass`는
완성된 코드의 일부이므로 유지했습니다. 삭제한 Git 추적 파일은 저장소 이력에서 복구할
수 있습니다. 현재 checkout에는 사용자 Front 테스트 11개와 `pytest.ini`가 있으며,
Agent 시험 보고서 검증용으로 `backend/tests/test_agent_report_behavior.py`와
`test_agent_report_recovery.py` 두 파일을 추가했습니다. Backend의 나머지 과거 회귀와
MCP·관리자 Front의 기존 회귀를 재개하려면 해당 테스트와 경로 설정을 복원해야 합니다.

같은 날 개발 문서는 `01_core`부터 `99_archive`까지 역할별로 재분류했습니다. 저장소
루트에 중복돼 있던 Frontend 기술 설계와 Backend 인계 문서는 변경 내용이 더 많은 최신본을
`04_frontend`에 유지하고 루트 사본을 제거했습니다. 문서 추가·이동 시에는
[개발 문서 안내](docs/개발상세플랜/README.md)의 분류 규칙을 따릅니다.

</details>

<details>
<summary>개발 환경 준비 · Python, 가상환경, 사용자 식별</summary>

### 시작하기

### 사전 준비

- Python 3.12 이상
- PostgreSQL 서버와 데이터베이스 생성 권한(MCP 섹터 운영 책임)
- Redis 실행 환경(MCP 섹터 운영 책임)
- 권장 패키지 관리자: [uv](https://docs.astral.sh/uv/)

모든 명령은 저장소 루트에서 실행합니다.

### 로컬 가상환경과 의존성 준비

| 위치 | 용도·설치 기준 |
| --- | --- |
| `.venv` | 통합 환경, 루트 `pyproject.toml`·`uv.lock`의 dev 포함 |
| `backend/.venv` | `backend/requirements.txt`, pytest·pytest-asyncio·httpx2 포함 |
| `frontend_user/.venv` | `frontend_user/requirements-dev.txt` |
| `frontend_admin/.venv` | `frontend_admin/requirements.txt`와 테스트용 `pytest>=8,<9` |
| `mcp_server/.venv` | 독립 `pyproject.toml`·`uv.lock`의 dev 포함, MCP SDK 1.29.1 |

기존 환경을 삭제하거나 덮어쓰지 않고, 없는 컴포넌트 환경만
`uv venv --python 3.12 <컴포넌트>/.venv`로 만듭니다. 설치·갱신:

```bash
uv sync --locked --dev
uv pip install --python backend/.venv/bin/python -r backend/requirements.txt
uv pip install --python frontend_user/.venv/bin/python -r frontend_user/requirements-dev.txt
uv pip install --python frontend_admin/.venv/bin/python -r frontend_admin/requirements.txt 'pytest>=8,<9'
uv sync --project mcp_server --locked --dev
```

Windows에서는 컴포넌트별 환경을 분리하고 반드시 환경 내부 Python으로 설치합니다:

```powershell
& ".\backend\.venv\Scripts\python.exe" -m pip install -r ".\backend\requirements.txt"
& ".\frontend_user\.venv\Scripts\python.exe" -m pip install -r ".\frontend_user\requirements-dev.txt"
& ".\frontend_admin\.venv\Scripts\python.exe" -m pip install -r ".\frontend_admin\requirements.txt"
```

### 사용자 식별

로그인 없이 브라우저가 생성·보관한 UUID v4 `user_id`와 `X-User-Id` header로
사용자를 구분합니다(저장 key: `ai_mafia_user_id_v1`). UUID는 인증 수단이 아니므로
신뢰된 로컬·사설망 환경에서만 사용합니다.

```bash
cp frontend_user/.streamlit/secrets.toml.example \
  frontend_user/.streamlit/secrets.toml
chmod 600 frontend_user/.streamlit/secrets.toml
```

실제 `.env`와 `secrets.toml`은 Git 무시 대상이며 이동·커밋하지 않습니다.

</details>

<a id="configuration"></a>

<details>
<summary>환경 설정 · 팀 DB, Provider, 프로세스별 비밀값 경계</summary>

### 환경 설정

### Backend·Data Infrastructure

기존 `.env`에는 다른 로컬 설정이나 비밀값이 있을 수 있으므로 덮어쓰지 마세요.
아래 복사는 로컬 개발용 placeholder 시작점입니다. 운영에서는 프로세스별
allowlist만 주입합니다(아래 표).

```bash
cp .env.example .env
chmod 600 .env
```

필수·기본 설정 예시:

```dotenv
TEAM_DATABASE_URL=postgresql://runtime_user:change-me@remote-host:4000/Team4_Proj
DATABASE_MIGRATION_URL=postgresql://migration_user:change-me@remote-host:4000/Team4_Proj
DATABASE_NAME=Team4_Proj
AI_MAFIA_STORAGE_MODE=team
```

- `TEAM_DATABASE_URL`의 팀 DB가 기본 테스트 DB입니다. DB 조사·실제 게임·DB 연동
검증을 여기서 진행하며, 실제 `.env`에는 로컬 DB URL을 두지 않습니다. DML 최소 권한
계정을 설정하고 다른 테스트의 게임·자료는 임의로 변경하지 않습니다.
- 기존 `DATABASE_URL` fallback은 별도 로컬 작업을 명시적으로 선택할 때만 사용합니다.
- `DATABASE_MIGRATION_URL`은 migration runner 전용 DDL 연결입니다. runtime DSN으로
대체하지 않으며 Backend runtime 프로세스에는 전달하지 않습니다.
- `run_openai.sh`의 `AI_MAFIA_STORAGE_MODE` 기본값은 `team`(공유
`TEAM_DATABASE_URL` 사용)입니다. `isolated`는 별도 로컬 작업을 명시적으로 요청한
경우에만 선택합니다.
- LLM Provider는 `LLM_PROVIDER`로 `dummy`(테스트 전용 고정 PASS)·`local`·`openai`·
`gemini` 중 하나를 선택하고, `config.py`가 모델·필수 키를 검증합니다.
- `LLM_TIMEOUT_SECONDS`(기본 30초)는 모든 중앙 Agent의 요청별 상한입니다. 실제
호출 제한은 `min(LLM_TIMEOUT_SECONDS, 창·예약 마감까지 남은 시간 - 완료·제출 여유 3초)`이며,
Provider에 전달하는 timeout과 `asyncio.timeout`으로 함께 적용합니다.
3초는 여유이며 DB·네트워크 지연에도 제출 완료를 보장하는 값은 아닙니다. 늦은 제출은
기존 마감·상태 검증으로 거부합니다. OpenAI의 `high` 추론 노력과 출력 한도는 유지합니다.
- Backend 중앙 AI worker는 `MCP_SERVER_URL`로 FastMCP 서버를 호출합니다.
- Backend는 Front host·port 사전 등록 없이 모든 origin의 SSE fetch preflight를
허용합니다. credentials는 허용하지 않으며 method·header와 API 권한 검사는 유지합니다.
- 공개 발언 분석은 `SPEECH_ANALYSIS_ENABLED=false`가 기본이며, 활성화하려면
migration 006·008 적용과 [.env.example](.env.example)의 `SPEECH_ANALYSIS_*` 설정이
필요합니다.

| 환경 소비자 | 허용하는 AI 마피아 관련 키 | 주입 금지 |
| --- | --- | --- |
| Front 서버 | Backend URL | DB·Redis·LLM·MCP/Engine secret |
| Backend runtime | `TEAM_DATABASE_URL`, `DATABASE_URL`, `DATABASE_NAME`, `REDIS_URL`, game state keyring, LLM Provider·model·key, `ADMIN_USER_IDS`, `MCP_SERVER_URL` | `DATABASE_MIGRATION_URL`, MCP runtime 전용 설정 |
| migration 실행 프로세스 | `DATABASE_MIGRATION_URL`, 비교용 `TEAM_DATABASE_URL`/`DATABASE_URL`·`DATABASE_NAME` | LLM·MCP secret |
| MCP runtime | `BACKEND_API_URL`, `MCP_LISTEN_HOST`, `MCP_LISTEN_PORT` | DB·Redis·LLM·인증 secret |

</details>

<details>
<summary>데이터베이스 마이그레이션 · 001~012와 팀 DB 적용 기록</summary>

### 데이터베이스 마이그레이션

Backend가 작성·소유하는 `backend/migrations/`의 SQL을 MCP 담당자가 이름순으로
실행합니다.

```bash
uv run python -m backend.app.infrastructure.migrations
```

- `001` legacy `users`·`oauth_identities`, `002`는 과거 scaffold `scaffold_*` 게임 테이블을 생성
- `003_create_mystery_v1_schema.sql`은 canonical `mystery-v1` 테이블을 순방향 추가
- `004_seed_scenarios_and_personas.sql`은 정본 시나리오 5개·알리바이·관찰 문장·persona를 멱등 등록
- `005_create_admin_knowledge_schema.sql` 관리자 운영 에이전트 색인(pgvector 필요)
- `006_create_speech_analysis.sql` 발언 분석 파생 저장소(pgvector 비의존)
- `007_add_stale_game_cleanup.sql` `games.last_user_action_at` 추가와 15분 무동작 정리 index
- `008_allow_public_human_speech_analysis.sql` 공개 사용자 발언 분석 허용
- `009_update_persona_reasoning_skill.sql` persona 추론 수치·내용 hash 갱신
- `010_add_custom_role.sql` 게임 mode, HUMAN custom snapshot, 제출 ability_id 추가
- `011_add_custom_role_tool_abilities.sql` HUMAN VOTE의 `vote.triple.v1` CHECK 확장
- `012_align_team_db_baseline.sql` 현재 team DB에 없는 빈 `scaffold_*`·`admin_knowledge_*` 객체를
  데이터가 있을 때는 삭제하지 않고 중단한 뒤 정리하고, `BALANCED_OBSERVER` persona를 seed
  데이터로 고정

**팀 DB 적용 기록 (2026-09-08):** 사용자 승인으로 설정된 `DATABASE_MIGRATION_URL`의
대상 DB 경로와 DDL 권한을 확인한 뒤, 서비스를 중지하고 **010 → 011**만 적용했습니다.
임시 디렉터리에 두 SQL만 연결해 기존 001~009를 다시 실행하지 않았습니다. 동일 순서
재실행도 통과했으며 새 열 5개·검증된 CHECK 3개, 기존 테이블 행 수, 기존 게임의
`STANDARD` 기본값과 custom/ability 열의 `NULL` 보존을 확인했습니다.

**team DB baseline 정렬 (2026-09-09):** 읽기 전용 catalog 확인에서 현재 DB에는
`scaffold_*` 3개와 `admin_knowledge_*` 2개가 없고, 활성 persona 6개 중
`BALANCED_OBSERVER`가 004 seed에 없음을 확인했습니다. 새 DB가 같은 최종 구조와
seed를 얻도록 012를 추가했습니다. 012는 현재 team DB에서 없는 객체에는 no-op이고,
대상 객체에 데이터가 있으면 삭제하지 않고 실패합니다. 실제 team DB에 012를 적용하는
작업은 이 검증과 분리하며, 적용 전 row count·백업·서비스 중지 여부를 확인해야 합니다.

위 기본 runner는 디렉터리의 전체 SQL을 이름순 실행하므로 이미 운영 중인 DB에서는
적용할 파일 범위를 먼저 확정해야 합니다. runtime DSN으로 DDL 설정을 자동 대체하지
않으며 URL과 자격 증명은 로그에 출력하지 않습니다. 다른 환경도 Backend·MCP를
최신 코드로 실행하기 전에 010·011·012를 적용해야 합니다. 새 DB에서는 runner가
001부터 012까지 이름순으로 실행하며, 이미 team baseline인 DB에서는 012가 정렬 검사를
수행하고 누락된 `BALANCED_OBSERVER`만 멱등 보완합니다.

자세한 기본값·권한 분리는 [.env.example](.env.example)과
[DB 설계 정본](docs/개발상세플랜/02_backend_data/AI_MAFIA_DB_DESIGN.md)을 참고하세요.

</details>

<a id="running"></a>

<details>
<summary>실행 안내 · 통합 실행, 개별 실행, 관리자 전용 실행</summary>

### 실행

### 한 번에 실행 (OpenAI)

```bash
./run_openai.sh --check  # 유료 API 호출 없이 세 런타임 설정·import 검증
./run_openai.sh          # Backend·MCP·Front 동시 실행
```

`.env`의 `OPENAI_MODEL`을 변경한 뒤에는 실행 중인 Backend를 재기동해야 합니다.
이 항목이 없으면 현재 코드의 기본 모델인 `gpt-4.1-mini`가 선택됩니다.
`--check`가 출력하는 실제 선택 모델을 확인하세요. 이 점검은 설정·import 확인이며
해당 모델의 API 접근 권한이나 실제 응답 성공까지 검증하지는 않습니다.

Windows PowerShell 또는 명령 프롬프트에서는 다음처럼 실행합니다.

```bat
run_openai.bat --check
run_openai.bat
```

동시 실행 주소: Backend `http://127.0.0.1:18000`, MCP
`http://127.0.0.1:18100/mcp`, Front `http://127.0.0.1:18501`.
다른 프로젝트와 포트가 겹치면 `AI_MAFIA_BACKEND_PORT`·`AI_MAFIA_MCP_PORT`·
`AI_MAFIA_FRONTEND_PORT`로 바꿀 수 있습니다.

Backend는 `backend/app` 안의 코드 변경만 `--reload`로 반영합니다. Front·테스트 편집은
Backend를 재시작하지 않습니다. MCP 프롬프트·adapter는 자동 재적재하지 않습니다.
MCP 변경 후에는 실행 터미널에서 `Ctrl+C`로 종료하고 `./run_openai.sh`로 전체 재시작합니다.

두 실행 스크립트의 기본 저장소 모드는 `team`입니다. 명시적 `isolated`는
`AI_MAFIA_DATABASE_URL`·`AI_MAFIA_REDIS_URL`을 사용하며 같은 팀 DB를 격리 DB로
지정하면 거부합니다. Windows `--check`는 필수 환경값 읽기와 import만 검사하고,
설정 객체·DB·Redis·migration·seed·API 연결은 검사하지 않습니다. macOS/Linux
`--check`는 선택한 DB·Redis와 seed 준비 상태까지 읽기 전용으로 검사합니다.

### 개별 실행 (통합 스크립트와 다른 포트 예시)

아래 Backend·MCP·사용자 Front 예시는 8000·8100·8501 조합입니다.
통합 스크립트의 18000·18100·18501과 혼용하지 않도록 각 프로세스의 연결 URL을 맞추세요.

```bash
# Backend (dummy Provider로 첫 검증)
LLM_PROVIDER=dummy .venv/bin/python -m uvicorn backend.app.main:app --reload --port 8000

# MCP server
(cd mcp_server && .venv/bin/python -m mafia_game)

# 사용자 Front
uv run streamlit run frontend_user/app.py --server.port 8501

# 관리자 Front (실제 API 모드 예시)
BACKEND_API_URL=http://127.0.0.1:8000 ADMIN_DEMO_MODE=false \
  frontend_admin/.venv/bin/python -m streamlit run frontend_admin/app.py \
  --server.address 127.0.0.1 --server.port 8502 --server.headless true
```

health 주소: 수동 Backend `http://127.0.0.1:8000/health`, 동시 실행
`http://127.0.0.1:18000/health` → `{"status":"ok"}`.

### Backend 공유 · Frontend는 localhost 유지

같은 네트워크의 다른 PC가 이 Backend를 사용하려면 기존 통합 실행을 종료하고
아래 세 명령을 각각 실행합니다. Backend만 `0.0.0.0:18000`에서 수신하고,
MCP와 사용자 Front는 localhost에 유지합니다. `run_openai.sh`의 기본 bind 주소는
여전히 `127.0.0.1`이므로 통합 스크립트로 다시 시작하면 LAN 공개가 해제됩니다.

```bash
# MCP를 먼저 기동해 Backend worker가 시작할 때 연결할 수 있게 합니다.
(cd mcp_server && BACKEND_API_URL=http://127.0.0.1:18000 \
  MCP_LISTEN_HOST=127.0.0.1 MCP_LISTEN_PORT=18100 .venv/bin/python -m mafia_game)

# 팀 DB·모델 설정은 루트 .env를 사용합니다.
LLM_PROVIDER=openai MCP_SERVER_URL=http://127.0.0.1:18100 \
  .venv/bin/python -m uvicorn backend.app.main:app \
  --reload --reload-dir backend/app --host 0.0.0.0 --port 18000

# 이 PC의 사용자 Front는 http://localhost:18501에서 접속합니다.
BACKEND_API_URL=http://127.0.0.1:18000 .venv/bin/python -m streamlit run \
  frontend_user/app.py --server.address 127.0.0.1 --server.port 18501 --server.headless true

# 동일 Backend를 쓰는 두 번째 Frontend는 별도 터미널에서 실행할 수 있습니다.
BACKEND_API_URL=http://127.0.0.1:18000 .venv/bin/python -m streamlit run \
  frontend_user/app.py --server.address 127.0.0.1 --server.port 18502 --server.headless true
```

다른 PC의 Front는 `BACKEND_API_URL`을 이 PC의 LAN IP와 `18000` 포트로 지정하고
localhost의 `18501` 포트에서 실행합니다. 같은 팀 DB를 처리하는 Backend worker를
한 곳으로 모으려면 다른 PC의 Backend 실행도 종료해야 합니다. `/health` 외에
`/ready`가 PostgreSQL·Redis 모두 `ok`인지 확인하고, Redis는 기존 환경을 기동합니다.
Frontend 프로세스에는 AI background worker가 없으므로 여러 포트로 실행해도
AI 차례를 중복 선점하지 않습니다. Backend는 모든 origin을 허용하므로 Front 포트를
추가해도 CORS 환경 설정을 변경할 필요가 없습니다.

진행 로그 확인:

```bash
tail -f backend/logs/game-progress.log
```

MCP를 `python -m mafia_game`으로 기동하면 stderr에 구조화 진단 로그를 기록합니다.
각 HTTP 요청과 그 안의 Backend 콜백은 같은 `correlation_id`를 공유하며,
`request_id`는 각 작업의 시작·종료를 연결합니다. UTC `timestamp`·`process`와
`operation`, `status`, `duration_ms`, `error_class`만 기록하고 게임·사용자 ID,
대사·역할·토큰·header·예외 원문은 기록하지 않습니다. SDK의 원문 진단도 고정
분류로 바꿉니다. 로그 출력 실패는 요청 결과나 취소 전파를 변경하지 않습니다.

- `mcp.initialize`, `mcp.resources.read`, `mcp.tools.call`은 MCP 요청 결과입니다.
  HTTP 200 안의 JSON-RPC 실패는 `MCP_RPC_ERROR`, Tool 실패는 `MCP_TOOL_ERROR`입니다.
- `backend.context.public/me/turn/persona`, `backend.action`은 Backend 콜백 결과입니다.
  `MCP_BACKEND_HTTP_403`처럼 HTTP 상태를 보존하고 `CONNECT_TIMEOUT`, `READ_TIMEOUT`,
  `WRITE_TIMEOUT`, `POOL_TIMEOUT`을 구분합니다. 같은 `correlation_id`로 MCP 오류와
  콜백의 세부 오류를 대조합니다.
- 분류용 요청·응답 복사본은 각각 16 KiB·64 KiB로 제한합니다. 이를 넘으면 본문
  분류를 생략하고 HTTP 결과만 남기며 실제 전송 본문은 변경하지 않습니다.

진단 실행의 stderr를 루트 `mcp_runtime.error.log`로 모았다면 다음 명령으로 봅니다.
모듈 자체는 파일·DB·queue를 만들지 않으며 기본 통합 실행에서는 터미널에 표시합니다.
MCP 코드 변경은 자동 reload되지 않으므로 MCP 프로세스를 다시 기동해야 합니다.

```bash
tail -f mcp_runtime.error.log
```

관리자 앱의 실제 조회는 Backend `ADMIN_USER_IDS`에 등록된 UUID가 필요합니다.
Backend·UUID 없이 화면만 확인하려면 `ADMIN_DEMO_MODE=true`로 실행하면 합성
데이터가 표시됩니다(실제 권한 검증을 대신하지 않습니다).

### Backend와 관리자 Front만 실행

기존 `run_openai.sh` 실행은 해당 터미널의 `Ctrl+C`로 Backend·MCP·사용자 Front를
함께 종료하고, 별도로 실행한 관리자 Front도 종료합니다. 아래 명령은 저장소 루트의
서로 다른 터미널에서 실행합니다. Backend는 `.env`의 팀 DB와 관리자 allowlist를
사용하며, 관리자 조회에 필요 없는 게임·발언 분석 백그라운드 worker는 시작하지 않습니다.

```bash
# Backend: 관리자 조회용으로 백그라운드 게임 진행을 중지한 상태로 실행합니다.
.venv/bin/python -c 'import uvicorn; from backend.app.main import create_app; uvicorn.run(create_app(enable_background_worker=False), host="127.0.0.1", port=18000)'

# 관리자 Front: 기존 Backend의 실제 관리자 API에 연결합니다.
BACKEND_API_URL=http://127.0.0.1:18000 ADMIN_DEMO_MODE=false \
  .venv/bin/python -m streamlit run frontend_admin/app.py \
  --server.address 127.0.0.1 --server.port 18502 --server.headless true
```

접속 주소는 Backend `http://127.0.0.1:18000`, 관리자 Front
`http://127.0.0.1:18502`입니다. 기동 확인은 각각 `/health`, `/_stcore/health`로
수행합니다. 이 구성에서는 MCP·사용자 Front를 실행하지 않으며 실제 게임 진행에는
전체 실행 구성이 필요합니다.
Backend만 리로드할 때는 Backend 터미널에서 `Ctrl+C` 후 위 Backend 명령을 다시
실행합니다. 관리자 Front는 그대로 유지하고 `/health`의 정상 응답을 확인합니다.

</details>

<a id="verification"></a>

<details>
<summary>검증 기록 · 테스트 소스 정리 상태 포함</summary>

### 검증 기록과 현재 상태

2026-09-09 WU-B6 Agent 시험 보고서 검증은 AGT-001~012 및 보강 시험의
**127개 변형을 각각 50회, 총 6,350회** 실행했습니다. 결과는 **6,296회 통과·54회
실패·오류/건너뜀 0회**이며 pytest 실행 시간은 9.27초입니다. 각 변형의 샘플
0~49가 정확히 한 번씩 실행됐음을 JUnit으로 검산했습니다. 재현 코드 두 파일은
`backend/tests/`에 보존하며 관련 명령은 아래에 있습니다.

- 실패는 모두 **9인 전원 생존 의사의 후보 상한 충돌**입니다. Backend의 의사
  대상은 자기 자신을 포함해 9명이지만 API 명세와 MCP client는 최대 8개로 제한해
  정상 Context를 `MCP_CONTEXT_CONTRACT`로 거부합니다. 고정 재현 시험 50회가 모두
  실패했고, 다른 변형의 같은 조건에서도 4회 실패했습니다. 실제 판정 코드와 API
  상한은 수정하지 않았으며 실패 테스트를 보존했습니다.
- stale·중복 제출·MCP 장애·응답 유실과 rollback·activity 보강 시험은 통과했습니다.
  응답 유실 시 원장은 1회 적용됐어도 activity가 `FAILED`일 수 있으므로, 실제 적용
  건수는 원장과 함께 확인해야 합니다.
- 합성 Provider·HTTP 전송·메모리 저장소를 사용해 실제 판정 코드를 실행했습니다.
  실제 LLM 오류율·DB turn 통계·SQL 잠금/내구성 시험은 아닙니다. 새 테스트의 Ruff
  `E9,F`와 문서·diff 검사를 통과했고, 런타임 변경이 없어 무관한 Front 회귀·외부 서비스
  통합은 생략했습니다. 삭제된 과거 Backend·MCP 전체 스위트도 복원하지 않았습니다.

시나리오별 횟수, 실제 오류 코드, 원인, 재현 명령과 증거 hash는
[에이전트 시험 결과 보고서](docs/arrangement/07_AGENT_TEST_RESULT_REPORT.md)에 기록했습니다.

2026-09-09 WU-B6에서는 `.env`의 `OPENAI_MODEL=gpt-5.6-luna`를 확인하고
Backend·MCP·사용자 Front를 재기동한 뒤, 6인 박물관 게임 한 판을 브라우저에서
진행했습니다. 저장·재개 두 번을 포함해 14:56:38 KST에 마피아 승리로 종료됐으며,
브라우저 결과와 Backend의 버전 51 완료 기록을 대조했습니다. 종료 후 Backend
`/ready`의 PostgreSQL·Redis와 사용자 Front health는 모두 정상입니다.

- **수정한 원인:** 저장 전 버전으로 남은 SPEECH 예약이 만료돼도 재개 후 버전에서는
  재예약되지 않아 AI가 계속 `SKIPPED`되는 오류였습니다. 기존 예약 저장소에서
  SPEECH도 현재 binding 검증 뒤 새 token·현재 버전으로 예약하도록 수정했습니다.
  같은 실게임에서 예약 버전 37→39, 새 token, 정상 생성·원장 제출·`APPLIED`까지
  확인했고 재개부터 적용까지 약 11.2초였습니다.
- **로컬 MCP·모델:** 해당 게임의 로컬 컨텍스트 완료는 25건, `MCP_CONTEXT_FAILED`는
  0건입니다. `PROVIDER_TIMEOUT` 1건은 MCP 조회 성공 후 게임 마감의 제출 여유
  3초를 제외한 모델 예산이 약 4.185초 남았을 때 발생했고 fallback이 적용됐습니다.
  별도 `AGENT_TIME_BUDGET_EXHAUSTED` 1건은 호출 전에 남은 예산이 소진된 경우입니다.
  이 기록만으로 API 인증·모델 접근 오류나 OpenAI 서비스 장애를 판정하지 않습니다.
- **남은 실행 환경 문제:** 최종 DB 작업 51건은 성공 23건, `MCP_UNAVAILABLE`
  fallback 25건, timeout fallback 1건, STALE 1건, 수정 전 잔여 RESERVED 1건입니다.
  DB 작업 행은 재예약으로 갱신되므로 호출 횟수와 다릅니다. 로컬 Backend에
  `PGAPPNAME`을 붙인 상태에서 MCP 실패 행의 `xmin`과 별도 무표식 연결의
  `backend_xid`가 일치했고, 성공 행은 로컬 표시 연결과 일치했습니다. 직접 연결을
  대조한 실패 표본은 1건이며 25건 모두를 그 세션에 귀속시키지는 않습니다. 단일 Backend
  실행으로 제한됐다고 확정할 수 없으며, 별도 연결의 실제 PC·실패 MCP 주소는 아직
  특정되지 않았습니다. 후반에는 다른 게임도 실행돼 MCP 런타임 전체 건수를 이 한
  게임의 성공률로 사용하지 않았습니다.
- **검증:** 팀 DB의 세션 전용 TEMP 합성 자료로 수정 전 실패 9건을 재현하고,
  수정 후 예약·만료·중복·이전 token 거부·기존 VOTE 동작 27개 테스트를 통과했습니다.
  public 게임 자료는 읽거나 쓰지 않고 transaction을 rollback했습니다. 이 검증은
  단일 연결의 SQL 경계를 다루며 실제 다중 연결 경합 전체를 검증하지는 않습니다.
  사용자 Front 전체 회귀는 606개 통과·54개 실패했습니다. 실패는 수정하지 않은
  화면의 `vote_insights` 속성·widget key·표시 기대값에 있고 이번 범위에서 수정하지
  않았습니다. 실행 분담 확인이 늦어 작업자와 코디네이터가 각 한 번 실행했으며
  결과는 같고 추가 반복은 하지 않았습니다. Backend·MCP 기존 전체 suite는 소스가
  없어 생략했고, 네 런타임의 compile·Ruff `E9`와 문서 포함 diff 검사는 통과했습니다. `scripts/`는
  현재 checkout에 없어 compile 대상에서 제외합니다. 추가 유료 자동 회귀와
  migration은 실행하지 않았습니다.

2026-09-09 WU-M5 MCP 진단 로그는 합성 HTTP 성공·상태 오류·잘못된 JSON,
네 종류의 timeout·transport 오류, 취소 전파와 로그 출력 장애를 확인했습니다.
실제 FastMCP를 연결한 두 동시 세션에서 요청별 correlation 분리, Backend 403과
HTTP 200 내부 RPC 오류의 연결, 본문 크기 제한과 민감 marker 제거도 통과했습니다.
변경한 두 Python 파일의 Ruff `F,I` 검사와 `git diff --check`가 통과했습니다.
삭제된 MCP 테스트 소스를 복원하지 않았으므로 기존 전체 회귀 스위트는 실행하지
않았고, 별도 테스트 파일 없이 합성 검증을 수행했습니다.

MCP를 재기동한 뒤 Backend `/ready`와 MCP initialize의 200 응답을 확인했습니다.
localhost:18502의 실제 6인 게임을 Day 2까지 진행하고 저장했으며, MCP 로그·Backend
진행 로그·팀 DB를 대조했습니다. MCP의 세션 초기화 26건과 컨텍스트 콜백 104건은
모두 성공했고 콜백 최댓값은 약 450 ms였습니다. 같은 게임의 AI 발언 45건은 정상
모델 발언 21건, `MCP_UNAVAILABLE` 기본 발언 12건·PASS 11건, `PROVIDER_TIMEOUT`
기본 발언 1건이었습니다. 후자의 로컬 timeout은 설정 상한 30초보다 행동 창의 남은
시간이 짧아 실제 LLM 예산이 약 0.99초로 줄어든 경우였습니다. `MCP_UNAVAILABLE`
발언 23건에는 로컬 Backend의 FALLBACK·APPLIED 기록이 없었고, 같은 관측 구간에
별도 무표식 DB 연결의 `agent_jobs` INSERT·UPDATE 실행을 확인했습니다. 이 첫
관측에서는 개별 실패 행과 해당 연결을 직접 연결하지 못했습니다.

후속 추가 분석에서는 별도 완료 게임의 컨텍스트 콜백 156건도 모두 성공했지만,
`MCP_UNAVAILABLE` 기본 발언 10건·PASS 20건·밤 행동 5건이 실제 적용됐음을
확인했습니다. 로컬의 행동 제출 HTTP 409 두 건은 상태 변경에 따른 거부이며 이
실패 코드와 구분합니다. 두 게임의 원래 관측 구간에서 MCP 실패 발언 53건 중
51건은 로컬 STARTED·SKIPPED만 있고 2건은 해당 actor·예약 버전의 기록이 없습니다.
전체 실행 sequence의 연속성과 현재 복구 경로를 대조해 일반적인 로그 회전 누락이나
저장 proposal 재사용으로 이 불일치를 설명하기 어렵다는 점도 확인했습니다.

2026-09-09 05:22:55.677~05:23:15.767 UTC에는 다른 진행 게임이 없는 상태에서
기존 진단 게임만 재개하고 로컬 Backend 부모·자식 세 프로세스를 20초간 일시
정지했습니다. 21회 관측 모두 정지 상태였으며, 초기 3초를 제외한 뒤 생성된 새
발언 작업 3건이 `MCP_UNAVAILABLE`로 완료되고 PASS로 실제 제출됐습니다.
게임 버전은 56에서 60으로 진행됐고 이 구간의 로컬 MCP 로그는 0건이었습니다.
정지 이후 시각만으로 판정하지 않고 새 예약→실패 완료→PASS 제출→다음 버전의
연속 진행을 확인해 이미 전송된 단일 SQL과 구분했습니다.
그중 실패 행의 `xmin=158079`가 정지 후 새로 연결된 무표식 DB 세션의
`backend_xid=158079`와 일치했습니다. 이는 별도 실행이 해당 FALLBACK 행 버전을
작성했다는 증거이며, 물리 PC나 원래 실패를 판정한 코드·MCP 주소까지 식별하지는
않습니다. `xmin`은 현재 행 버전의 작성 트랜잭션이므로 중간 실패 버전 이후의
lease 수정과 최초 실패 확정을 구분하는 추가 증거가 필요합니다.
DB에 표시되는 client 주소는 중계 주소이고 연결·SQL 이력 기록도 꺼져
있어 그 이후 추적에는 DB 서버의 중계 전 연결 정보나 해당 실행의 로그가 필요합니다.

프로세스는 watchdog과 `finally` 복원 경로를 두고 정상 재개했으며 Backend `/ready`
200과 브라우저 연결 복구를 확인했습니다. 진단 게임은 Day 3에서 다시 저장했습니다.
추가 분석에서 실행 코드는 변경하지 않았고 DB 진단 연결은 읽기 전용이었습니다.
로컬 프로세스·컨테이너와 기존 연결된 Linux 개발 서버에서도 추가 프로젝트 Backend를
찾지 못했지만, 이 관측 범위 밖의 실행 위치는 확정하지 않습니다. 읽기 전용 감사와
기존 실행의 대조 실험이므로 자동 테스트는 반복하지 않고 문서 diff를 확인했습니다.

2026-09-09 WU-B8 관리자 AI 행동 로그 확장은 임시 focused 테스트 33개
(권한 거부·입력 오류·조회/감사 장애·민감 열 제외·Front 필터와 페이지 이동)를
통과했습니다. 팀 DB에서는 검증 시점의 작업 5,497건을 100건씩 55페이지로 읽어
중복·누락 없이 확인했고, 작업 종류/상태 20개 조합·게임 필터·없는 커서·실제 DB를
연결한 API 200 응답을 검증했습니다. DB transaction은 읽기 전용이고 감사 저장만
메모리 대역을 사용해 실제 데이터는 변경하지 않았습니다. 합성 데이터 브라우저 화면도
확인했고 전체 런타임 `compileall`, `ruff E9`와 `git diff --check`도 통과했습니다.
삭제된 테스트 소스는 복원하지 않았으므로 기존 전체 회귀 스위트는
실행하지 않았고, 유료 API 호출·신규 게임 생성·migration도 수행하지 않았습니다.

후속 서버 리로드에서는 멈춘 Backend 작업 프로세스를 종료하고 자동 재기동을
확인했습니다. 실제 `:18000/health`와 관리자 `agent-jobs` API가 200을 반환했고,
`:18502`의 **관리자 로그 → AI Agent 행동**에서 팀 DB 로그 20건 표시를 확인했습니다.
실행 코드 변경이 없어 자동 테스트는 재실행하지 않았습니다.
이후 사용자 종료 요청으로 Backend·MCP·사용자 Front·관리자 Front를 종료했고,
18000·18100·18501·18502 포트가 모두 닫힌 것을 확인했습니다.

아래 수치는 기능 구현 당시의 기록입니다. 현재 checkout에는 `frontend_user/tests`의
테스트 소스 11개와 `frontend_user/pytest.ini`가 있어 다음 사용자 Front 회귀를 실행할
수 있습니다. `backend/tests`에는 이번 Agent 보고서 전용 두 파일만 있으며,
`frontend_admin/tests`, `mcp_server/tests`는 없으므로 이 세 컴포넌트의 과거 전체 결과를
현재 재현 결과로 해석하지 마세요. 과거 검증 근거는
[날짜별 기록](docs/개발상세플랜/90_history/)과 관련 설계 문서에 보존합니다.

```bash
.venv/bin/python -m pytest frontend_user/tests -c frontend_user/pytest.ini
```

Agent 보고서의 AGT-001~012 반복 검증은 저장소 루트에서 다음과 같이 실행합니다.
각 테스트 변형마다 새 합성 상태로 50회 실행하며 외부 LLM·MCP·DB는 호출하지 않습니다.
실제 Backend 판정 코드를 사용하는 이 시험의 통과율은 실제 LLM의 판단 정확도나
실제 DB의 Agent turn 오류율과 구분합니다. 항목별 결과·예외 코드·시험 경계는
[에이전트 시험 결과 보고서](docs/arrangement/07_AGENT_TEST_RESULT_REPORT.md)를 따릅니다.

```bash
AGENT_REPORT_SAMPLES=50 PYTHONPATH=. .venv/bin/python -m pytest \
  backend/tests/test_agent_report_behavior.py \
  backend/tests/test_agent_report_recovery.py \
  -q --tb=short --junitxml=/tmp/agent-report-results.xml
```

나머지 과거 스위트를 복원할 때는 컴포넌트별 `tests/` 경로와 pytest 설정을 함께 복원하고,
팀 DB를 사용하는 검증은 테스트 소유 자료만 조작해야 합니다. 현재 실행할 수 있는
최소 정적 확인은 다음과 같습니다.

```bash
.venv/bin/python -m compileall -q backend/app frontend_user frontend_admin mcp_server/mafia_game
.venv/bin/python -m ruff check --no-cache --select E9 backend/app frontend_user frontend_admin mcp_server/mafia_game
git diff --check
```

구조 정리 직후 위 compileall, Backend·MCP 생성 함수 import, `E9` 구문 검사와
`git diff --check`는 통과했습니다. 추가로 실행한 `E9,F` 검사에서는 이번 삭제와 무관한
기존 미사용 import·지역 변수 42건이 확인되어 요청 범위 밖 코드에는 손대지 않았습니다.

CP-7 전체 회귀 결과 (2026-09-08, JSONB 수정 후·마이그레이션 적용 전):

| suite | 통과 | 실패 | 오류 | 생략 | 실패 분류 |
| --- | ---: | ---: | ---: | ---: | --- |
| Backend | 1,231 | 26 | 0 | 17 | 스키마 미적용 22건, 기존 계층 경계 3건·로컬 DB 전용 assertion 1건 |
| 사용자 Front | 655 | 5 | 0 | 0 | 기존 UUID 교체 컨트롤 3건·결과 새 게임 버튼 2건 |
| MCP server | 177 | 1 | 0 | 0 | 실제 Backend process 게임 생성 시 스키마 미적용 |

Backend 계층 경계 실패는 `test_lb06_agent_boundaries.py`,
`test_lb08_final_boundaries.py`, `test_repository_boundary.py`입니다. Front 실패는
`test_identity_f1.py`의 `identity.replace_button`/`identity.replacement_input`과
`test_result_f6.py`의 `result.new_game` 기대입니다. 모두 기존 기록과 일치하며 코드나
fixture를 수정하지 않았습니다. 이전 MCP public context fixture 실패 3건은 이번 실행에서
나타나지 않았습니다. compileall과 `git diff --check`는 통과했습니다.

`custom_ability_ids`는 psycopg `Jsonb`로 감싸 JSON 배열로 저장하도록 보완했습니다.
STANDARD·AI의 NULL 호환과 1~3개 배열 직렬화를 포함한 B16 165개 및
B16·migration·config 집중 검증 240개가 통과했습니다. 브라우저에서 발견한 생성 화면
능력 선택 상자, 역할 공개 직업명, 내 정보 능력 설명과 발언 입력 안내의 대비도
보완했으며, 수정 후 F2 52개·F3 219개와
최소 Ruff·compile·diff 검증이 통과했습니다.

010·011 적용 후 팀 DB 회귀 재검증에서는 `test_b5_game_api.py` 19개가 통과했고,
`test_postgres_game_flow.py`는 2개 통과·4개 실패, MCP process roundtrip은 1개가
실패했습니다. 합계 21개 통과·5개 실패이며 스키마 누락 오류는 사라졌습니다.
남은 실패는 첫날 PASS 허용을 기대하는 4건과 로컬 DB 호스트를 전제한 1건입니다.
현재 제품의 첫날 PASS 금지·팀 DB 기본 정책과 충돌하는 기존 기대값은 수정하지
않았습니다. DB 검증 중 실제 게임 worker는 중지하고 테스트 소유 자료만 정리했습니다.

관리자 timeout 보정 후 focused 3개와 관리자 전체 22개가 통과했습니다. 실제 Chrome
최종 검증은 코드 추가 수정 없이 다음 두 흐름이 연속 통과했습니다(2026-09-08).

1. 시민 `감식 수호자 최종` + 조사·보호: 생성, 역할 공개, 시작, 발언 전송,
   저장·불러오기·재개 후 직업/능력/발언 복원, 관리자 운영·발언 분석 표시.
2. 마피아 `밤의 조율자 최종` + 필수 공격·투표 조작·특수 직업 열람: 같은 저장·복원
   흐름, 첫날 열람 잠금, 관리자 실시간 재조회와 히트맵·키워드·공개 근거 표시.

테스트 게임은 마지막에 다시 저장해 일시 정지했습니다. 브라우저 검증은 위 사용자
흐름의 smoke test이며 두 게임의 승패까지 완주하거나 모든 능력 조합을 실제 유료
모델로 반복한 검증은 아닙니다. 밤 선택·가중 투표·승패·거부 경로는 위 focused
자동 테스트로 확인했습니다. 전체 회귀 이후 변경되지 않은 Backend·MCP suite는
중복 실행하지 않았고, 마지막 관리자 보정은 해당 전체 suite로 검증했습니다.
최종 변경 범위 검토, 비밀값 대조, 변경 Python 메모리 compile과 diff 검사가 통과했습니다.

과거 회귀 집계의 상세 명령·환경·실패 분류는 [날짜별 기록](docs/개발상세플랜/90_history/)을 참고하세요.

관리자 발언 분석 API는 `GET /api/v1/admin/speech-analytics`이며 기존 관리자 UUID
allowlist와 감사 기록을 그대로 사용합니다. 화면의 분석 조건에서 기간·에이전트·라운드·
게임 UUID를 좁혀 조회할 수 있고, 최대 500건의 결정적 표본을 Backend에서
저장 벡터의 앞 96차원 투영으로 cosine 유사도(0.78)를 계산해 묶고, 미완료 분석과
표본 제한을 coverage에 표시합니다. API는
공개 AI 발언만 반환하며 벡터·역할·진영·개별 행동·투표·private context는 노출하지
않습니다. 운영 화면에서 임베딩 행이 없으면 주제 대신 분석 대기 상태를 표시합니다.
팀 DB의 전체 기간 발언 분석 GET에는 30초 제한을 사용하고 다른 관리자 요청은
기존 5초를 유지합니다. 약 12초 걸리는 정상 집계를 연결 오류로 처리하던 문제를
보정한 것이며, timeout·403 오류의 fail-closed 처리와 자동 재시도 없음은 유지합니다.

</details>

<a id="security"></a>

## 07 · 보안과 현재 한계

AI의 비공개 정보 분리는 Backend의 actor projection과 검증 정책으로 보장하는
애플리케이션 경계입니다. UUID 기반 MVP를 강한 인증·프로세스 격리로 해석하지 마세요.

<details>
<summary>보안 원칙과 알려진 제약 전체 보기</summary>

- `.env`, 실제 `secrets.toml`, token과 모든 실제 자격증명을 커밋하지 않습니다.
- 공개 API의 `X-User-Id`는 인증이 아니라 UUID scope 선택값입니다. UUID를 아는
사용자의 가장을 막지 못하므로 MVP는 개인 개발 환경 또는 사설망으로 제한합니다.
- 현재 최소 FastMCP는 custom bootstrap·HMAC·capability 인증을 제공하지 않습니다.
요청 schema·게임 소유권·행동 유효성은 Backend가 검증합니다.
- Backend는 각 AI actor의 허용된 자기 정보만 scope별로 투영합니다. 밤 행동과
개별 투표는 종료 전에 공개하지 않으며 확정 공개 결과와 본인의 조사 결과를 구분합니다.
- MCP runtime은 DB·Redis에 직접 접근하거나 영속 outbox를 소유하지 않습니다.
- seed와 engine snapshot keyring은 저장소 밖에 두고 과거 record가 참조하는 key를
보존합니다.
- LLM prompt, raw response, private context, token과 비용을 로그에 넣지 않습니다.
- 루트 `*_runtime*.log`는 사용자·게임 식별자가 포함될 수 있어 Git 추적에서 제외합니다.
  2026-09-08 병합으로 들어온 6개 로그도 로컬 파일을 보존하면서 추적 해제했습니다.
  기존 병합 이력에는 남으므로 외부 공유 범위를 점검해야 합니다. 비밀키가 추가로
  확인되면 해당 키를 폐기·재발급해야 하며, 이번 작업은 Git 이력을 재작성하지 않습니다.
- `ADMIN_USER_IDS`는 강한 인증이 아니므로 관리자 앱도 loopback·사설망에서만 사용합니다.
- 현재 홈에는 UUID 복구 설정 진입점이 없으며, 완료 화면의 새 게임 시작은 홈을
  거쳐야 합니다. 관련 기존 회귀 실패는 이번 병합 수정 범위에서 유지합니다.
- 팀 DB를 공유하는 Backend worker는 같은 버전으로 실행해야 합니다. 발언 worker는
  같은 DB의 모든 진행 중 게임을 조회하므로 Backend 포트를 나눠도 게임 처리 대상이
  분리되지는 않습니다. Frontend에는 AI worker가 없으며, 2026-09-09의 18501·18502
  병렬 브라우저 검증에서는 두 게임 모두 정상 모델 발언과 `MCP_UNAVAILABLE`에 따른
  기본 발언·PASS가 섞여 재현됐습니다.
  반복 발언·PASS는 `action_submissions`에 실제 반영된 행동을 같은 window·player의
  `agent_jobs`와 대조해 집계합니다. 현재 fallback은 첫날에 준비된 일반 질문을 고르고,
  이후 발언 차례에는 PASS를 고릅니다. MCP 공개 이력 조회가 실패하면 이전 발언을
  이용한 중복 회피도 제한됩니다. 모델이 선택한 PASS와 오류 fallback을 구분해야 합니다.
  `MCP_UNAVAILABLE`의 상세 원인은 처리한 실행의 `MCP_CONTEXT_FAILED` 진단을
  확인해야 합니다. 로컬 기록이 없는 job의 실패 endpoint·HTTP 상태·실행 호스트를
  추측으로 확정하지 않습니다. DB job에는 worker instance가 없고 `created_at`은 DB,
  `completed_at`은 application 시계를 사용하므로 시각 역전만으로 호스트를 특정할 수 없습니다.
  Backend의 DB 연결을 구분하려면 실행 환경에 PC별로 다른 `PGAPPNAME`을 지정하고,
  진단 조회에도 별도 `application_name`을 지정해 `pg_stat_activity`를 대조합니다.
  2026-09-09 재검증에서는 로컬 Backend 연결에 식별 이름을 붙인 뒤에도 별도 무표식
  연결이 `list_expired_night_windows`와 동일한 자동 진행 조회를 실행하는 것을 확인했습니다.
  MCP 재기동 후 실게임에서는 별도 무표식 연결이 `agent_jobs` INSERT·UPDATE도
  실행했습니다. 후속 20초 정지 실험에서는 새 FALLBACK 행의 `xmin`과 별도 연결의
  `backend_xid`까지 대조해 해당 행 버전의 작성 연결을 확인했습니다. 구체적 관측
  조건은 위 검증 기록을 따르며 물리 PC·MCP 실패 endpoint는 여전히 미확정입니다.
  조사용 연결은 읽기 전용으로 운영했고 이 PC에서 추가 Backend 프로세스도
  관측되지 않았지만, DB의 client 주소가 중계 주소로 보여 별도 실행의 PC는 특정하지 못했습니다.
  앞선 8초 동결 관측은 모든 자식의 정지 상태와 이미 보낸 DB 작업의 완료를 확인하지
  않았으므로 다른 PC 실행의 단독 확정 근거로 사용하지 않습니다.
  `Event loop is closed`는 별도 연결 정리 문제도 점검해야 합니다. 합성 HTTP 응답으로
  검증했을 때 OpenAI 요청 성공 후 다음 event loop의 지연된 client 정리에서 오류가
  재현됐고, 같은 loop에서 명시적으로 닫은 대조군은 정상 종료했습니다. 이 정리 오류를
  MCP context 조회 실패나 LLM 요청 실패와 같은 원인으로 집계하지 않습니다.

비밀값 노출이 의심되면 값을 다시 출력하지 말고 즉시 폐기·재발급한 뒤 Git 이력과
외부 로그를 별도로 점검하세요.

</details>

<details>
<summary>변경 이력 · 날짜별 기능·통합 검증 기록</summary>

### 변경 이력

날짜별 변경·검증 기록은 [90_history](docs/개발상세플랜/90_history/)에 모아 두었습니다.

2026-09-08 `chd_test`·`jyu` 병합 검증에서는 실시간 갱신·발언 예약·저장/이탈·
조사 결과 표시와 관리자 접근 거부 후 복귀를 복구했습니다. 외부 Chrome의 6인 박물관
게임은 시민 승리(2라운드), 8인 산장 게임은 저장·재개 후 마피아 승리(3라운드)로
모두 `COMPLETED`/`ENDED`를 확인했습니다. 마지막 Front·관리자 회귀는 605 통과·
기존 실패 5건, Backend는 전체 실행과 실패 재검증 합산 978 통과·기존 실패 14건·
선택 검증 17건 생략, 독립 MCP 대상 검증은 101 통과였습니다. Windows 실기동은
환경이 없어 생략했으며 PowerShell 스크립트는 합성 dotenv·대상 비교와 정적 검증만
수행했습니다. 당시 후속 프롬프트 작업의 전체 회귀는 보류했으며, 현재 CP-7 검증은 위 테스트 절을 따릅니다.

역할별 공격적 토론·블러핑 프롬프트 보완 후에는 최소 MCP 검증 48건이 통과했고,
재시작한 MCP의 실제 Prompt 응답이 최종 소스와 일치함을 확인했습니다. 외부 Chrome의
추가 6인 야간열차 게임은 직접 발언·투표, 관전 빠른 진행을 거쳐 3일차 2라운드에
시민 승리로 종료됐습니다(16:19:34 KST). 실제 대화에서 직접 추궁·표 몰이·앞선 말과
다른 해명을 관찰했습니다. 공유 worker 개입 가능성이 남아 있어 한 판만으로 역할별
기만 빈도나 의도적 날조의 효과를 확정하지 않습니다.

| 문서 | 기록 범위 |
| --- | --- |
| [persona-and-prompts](docs/개발상세플랜/90_history/2026-09-08-persona-and-prompts.md) | 역할별 프롬프트, persona 추론 수치(009), dialogue_focus, 실게임 검증 |
| [speech-analysis](docs/개발상세플랜/90_history/2026-09-08-speech-analysis.md) | 공개 발언 분석 구현·006/008 적용·Team DB 적용·실게임 점검 |
| [game-lifecycle](docs/개발상세플랜/90_history/2026-09-08-game-lifecycle.md) | 저장·재개·삭제·뒤로가기, 병렬 투표, stale 게임 자동 정리(007) |
| [frontend-ui](docs/개발상세플랜/90_history/2026-09-07-08-frontend-ui.md) | WU-F5 발언 대기열, 홈·UUID 복구, 타임라인·채팅 UI |
| [infra-merge-admin](docs/개발상세플랜/90_history/2026-09-07-infra-merge-admin.md) | 섹터 병합, 관리자 앱 연결, Redis 캐시, 로깅, 회귀 기록 |

</details>

<details>
<summary>확장 지점 · 어디서 기능을 이어 개발할까?</summary>

### 확장 지점

- UUID 사용자 식별: `frontend_user/core/identity.py`, `frontend_user/core/session.py`,
`frontend_user/components/identity_bridge.py`, `backend/app/services/identity_service.py`
- Backend API client: `frontend_user/core/api_client.py`
- 사용자 저장소: `backend/app/repositories/user_repository.py`
- schema 변경: Backend가 `backend/migrations/`에 다음 번호의 순방향 SQL을
추가하고 MCP 담당자가 실제 환경에서 실행·재실행 검증
- Agent·LLM·MCP client: `backend/app/agent/`, `backend/app/llm_provider/`,
`backend/app/mcp/`
- 관리자 발언 분석: `backend/app/repositories/admin_repository.py`,
  `backend/app/services/admin_service.py`, `frontend_admin/app_pages/dashboard_page.py`
- 독립 MCP 기능: `mcp_server/mafia_game/`의 기존 `api`, `integrations`, `schemas` 계층에 추가

</details>

---

### 함께 개발하기

작업을 시작하기 전에 [AGENTS.MD](AGENTS.MD)를 읽고 브랜치 정책, 사용자 승인,
검증 수준, README 갱신 규칙을 따르세요. 구현 요청은 파일 변경을 승인하지만
커밋이나 push를 자동 승인하지 않습니다.

[맨 위로](#ai-mafia) · [테스트·검증 기록](#verification) · [날짜별 변경 기록](docs/개발상세플랜/90_history/)
