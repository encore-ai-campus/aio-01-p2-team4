# 발표 자료 근거와 캡처 기록

## 판정 기준

2026-09-09의 작업 디렉터리를 읽었다. 진행 중인 기존 파일 정리·README 변경은 보존했으며, 계획 문서에 적혔다는 이유만으로 구현 완료로 판단하지 않았다. 현재 동작은 코드·루트 README·실행 화면으로, 과거 개선의 검증 수치는 해당 날짜의 보고서로 구분했다.

## 주요 내부 근거

| 발표 내용 | 근거 파일 | 확인 내용 |
| --- | --- | --- |
| 제품·규칙·현재 제약 | [README](../../README.md) | 인간 1명+AI 5~8명, 시나리오 5개, 독립 입력, 사설망 MVP, CUSTOM_ROLE |
| 제품 정본·작업 범위 | [Master Plan](../개발상세플랜/01_core/AI_MAFIA_MASTER_PLAN.md) | 현재 구현과 목표 계약 구분, custom AI는 후속 범위 |
| API 경계 | [API Spec](../개발상세플랜/01_core/AI_MAFIA_API_SPEC.md) | 공개 API, actor별 내부 context, CORS, 행동 창·멱등성 |
| DB 책임 | [DB Design](../개발상세플랜/02_backend_data/AI_MAFIA_DB_DESIGN.md) | PostgreSQL 원본, Redis 파생 상태, 외부 호출 중 transaction 미보유 |
| MCP 책임 | [MCP Design](../개발상세플랜/03_mcp_agent/AI_MAFIA_MCP_SERVER_DESIGN.md) | Backend 내부 API 위임, DB·Redis·LLM 직접 접근 금지 |
| 화면과 공개 판단 요약 | [Screen Flow](../개발상세플랜/04_frontend/AI_MAFIA_SCREEN_FLOW.md) | 판단 요약은 내부 사고 원문이 아니며 비공개 정보와 구분 |
| 현재 Agent 실행 | [orchestrator.py](../../backend/app/agent/orchestrator.py) | 예약→scope 조회→단일 모델→검증/한 번 교정→완료 또는 대체 처리 |
| 모델 요청 구성 | [orchestrator.py](../../backend/app/agent/orchestrator.py) | actor별 새 요청, 역할 지침과 user 원문의 분리, 내부 추론 반환 금지 |
| AI 행동 실행 경로 | [postgres_runtime.py](../../backend/app/services/game/postgres_runtime.py) | 정상 발언의 MCP 제출, 투표 병렬 판단과 Backend 개별 적용 |
| MCP Tool 매핑 | [client.py](../../backend/app/mcp/client.py) | `propose_*`는 논리 행동명이며 wire `submit_action`으로 매핑 |
| wire Tool 3개 | [Tool registry](../../mcp_server/mafia_game/api/tools/registry.py) | `submit_action`, HUMAN 전용 `manipulate_vote`·`inspect_special_roles` |
| 분리 실행 설정 | [사용자 API client](../../frontend_user/core/api_client.py), [관리자 API client](../../frontend_admin/core/api_client.py), [Backend config](../../backend/app/core/config.py), [MCP main](../../mcp_server/mafia_game/main.py) | `BACKEND_API_URL`, `MCP_SERVER_URL`, DB·Redis 주소, MCP listen 주소와 CORS |
| 병렬 투표 개선 | [투표 문제 보고서](../개발상세플랜/05_reports/AI_MAFIA_PARALLEL_VOTE_BUG_REPORT.md) | 2026-09-07 관찰·원인·해결·실게임 두 투표 창의 수치 |
| 입력 안정화 | [Frontend 이력](../개발상세플랜/90_history/2026-09-07-08-frontend-ui.md) | fragment·FIFO·같은 멱등 키, 과거 연속 발언 10건의 순서·중복 확인 |
| 반복 질문 개선 | [Persona·Prompt 이력](../개발상세플랜/90_history/2026-09-08-persona-and-prompts.md) | dialogue_focus·역할 지침 재설계, 실게임 품질과 공유 worker 문제의 남은 범위 |
| 후속 Agent 설계 | [StateGraph 설계](../AI_MAFIA_AGENT_ARCHITECTURE_DESIGN.md) | 현재 실행 근거가 아닌 후속 설계로 취급 |
| 관리자 화면 | [관리자 README](../../frontend_admin/README.md), [dashboard_page.py](../../frontend_admin/app_pages/dashboard_page.py) | 운영 지표·AI 발언 분석·피드백·감사 로그의 네 탭, 실제 API 연결 |
| 발언 벡터 분석 | [admin_repository.py](../../backend/app/repositories/admin_repository.py), [006 migration](../../backend/migrations/006_create_speech_analysis.sql) | `double precision[]` 저장, 앞 96차원과 최대 500건 표본의 cosine 기반 주제 묶기, 원문 키워드 빈도 |
| 운영 자료 벡터 검색 | [admin_repository.py](../../backend/app/repositories/admin_repository.py), [005 migration](../../backend/migrations/005_create_admin_knowledge_schema.sql) | 승인 자료의 키워드 점수 0.55 + pgvector cosine 점수 0.45, `vector(64)`·HNSW 인덱스 선언 |
| 검색 답변의 현재 범위 | [admin_knowledge.py](../../backend/app/services/admin_knowledge.py), [admin_service.py](../../backend/app/services/admin_service.py) | 개발용 64차원 토큰 해싱, 근거 문장 추출·연결, 외부 LLM 호출 없음 |

## 외부 근거

확인일은 2026-09-09다. 다음 자료는 제품 기본 설명과 개념 정의만 사용한다. 경쟁 제품에 특정 기능이 없다는 부재 증명이나 시장 규모·매출 추정에 사용하지 않는다.

- [마피아42 / TEAM42의 Google Play 등록](https://play.google.com/store/apps/details?hl=ko&id=com.sopt.mafia42.client): 실시간 심리전과 직업·커뮤니티 기능을 설명한다. 싱글 플레이어 분류도 있으므로 ‘혼자 할 수 없는 게임’이라고 제품 전체를 단정하지 않는다. 사용자 리뷰를 현재 전체 사용자 경험의 통계로 인용하지 않는다.
- [Among Us / Innersloth 공식](https://www.innersloth.com/games/among-us/): 4~15인 온라인·로컬 플레이, 팀워크·배신·투표라는 기본 플레이 설명. 발표에서는 소셜 디덕션 장르의 참고 사례로만 사용한다.
- [Building effective agents / Anthropic](https://www.anthropic.com/engineering/building-effective-agents): 2024-12-19 발표된 Workflow·Agent 구분과 비용·지연·유연성의 균형. 수업 자료 자체는 제공되지 않았으며 이 정의를 프로젝트에 적용하는 부분은 발표의 설계 해석이다.
- [pgvector 공식 저장소](https://github.com/pgvector/pgvector): PostgreSQL의 벡터 유사도 검색 확장. 프로젝트의 실제 사용 여부는 migration·repository와 아래 팀 DB 확인으로 따로 판단한다.
- [Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks](https://arxiv.org/abs/2005.11401): 검색한 외부 지식을 조건으로 언어를 생성하는 RAG 개념의 원 논문. 벡터 군집 통계나 근거 문장 추출만으로 생성형 RAG가 완성됐다고 표현하지 않는다.

## 직접 확보한 실제 화면

`http://127.0.0.1:18501/`에서 현재 실행 중인 사용자 앱을 열어 직접 캡처했다. 이 주소는 로컬 개발 실행을 뜻하며 외부 배포 주소가 아니다.

- 새 브라우저의 발표용 게임에서 6인·시민 진영·직업명 ‘전략 탐정’을 선택했다.
- 능력은 조사·투표 조작·특수 직업 열람을 선택했다.
- 실제 생성된 시나리오는 ‘정전된 방송국’이었다.
- 역할 공개 뒤 낮 토론에서 발표용 문장 한 건을 제출하고, 인간 발언과 AI의 공개 반응을 확인했다.
- 화면 확보 후 ‘저장하고 나가기’를 실행했으며 홈의 ‘저장됨 · Day 1 · Round 0’을 직접 확인했다.
- 게임 전체 완주·밤 능력·3표 투표·특수 직업 조회의 실제 사용을 이번 캡처에서 검증한 것은 아니다. 해당 기능의 설명은 현재 코드와 기존 통합 기록을 근거로 한다.
- 홈 이미지의 UUID는 이번 캡처 세션에서 생성된 식별값이며 발표 화면 배치에서는 제외한다. 외부 로그·자격증명·기존 사용자의 대화는 발표 자료에 복사하지 않았다.

| 파일 | 내용 | 사용 슬라이드 |
| --- | --- | --- |
| `assets/screenshots/home.jpg` | 실제 홈 | 4 |
| `assets/screenshots/role_reveal.jpg` | 실제 전략 탐정 역할 공개 | 4 |
| `assets/screenshots/game_discussion.jpg` | 내 정보·공개 대화·마감 안내 | 8 |
| `assets/screenshots/game_chat.jpg` | 인간과 플레이어 3·4의 대화 | 8 |
| `assets/screenshots/custom_role_setup.jpg` | 직업명·진영 | 9 |
| `assets/screenshots/custom_role.jpg` | 세 가지 선택 능력 | 9 |
| `assets/screenshots/admin_overview.jpg` | 실제 관리자 운영 지표와 API 연결 표시 | 11 |
| `assets/screenshots/admin_speech_analytics.jpg` | 실제 AI 발언 주제 히트맵·키워드 빈도 | 11 |

원본 캡처의 일부를 발췌해 슬라이드에 배치할 수 있지만, 문구나 선택값을 바꿔 실제 구현 화면처럼 제시하지 않는다. `origin_image/`에는 내장 ImageGen으로 생성한 슬라이드 배경을 보관한다. ImageGen이 화면을 재구성하는 문제가 있어 사용자가 4·8·9·11장의 원본 직접 삽입을 승인했다. 해당 슬라이드는 생성된 화면 영역 전체를 가린 뒤, 원본 JPEG를 PowerPoint 이미지로 넣고 기본 자르기 속성으로 표시 범위만 지정한다. 따라서 이 네 장의 최종 화면은 PPTX와 PDF 미리보기를 기준으로 확인한다.

## 관리자 화면·벡터 DB·RAG 추가 확인

2026-09-09 기존에 실행 중인 `http://127.0.0.1:18502/`의 관리자 앱에 설정된 관리자 식별자로 접근했다. Backend allowlist를 바꾸거나 새 권한을 부여하지 않았다. 실제 API로 표시된 운영 지표와 AI 발언 분석의 주제 히트맵·키워드 차트를 캡처했으며, 식별자·피드백 원문·감사 로그는 캡처 대상에서 제외했다. 캡처 후 관리자 탭을 닫았다.

화면 숫자는 팀 테스트 DB의 캡처 시점 집계이며 테스트·합성 데이터가 포함될 수 있다. 슬라이드에서는 기능 설명에만 쓰고 유료 사용자 수·시장 검증·모델 품질 성과로 사용하지 않는다.

`TEAM_DATABASE_URL`의 팀 DB에 기본 transaction을 읽기 전용으로 설정하고, 접속·문장 제한 시간을 둔 상태로 extension·테이블 존재 여부만 조회했다. 접속값·행 원문은 출력하지 않았고 DB·migration을 변경하지 않았다.

| 확인 항목 | 결과 |
| --- | --- |
| `vector` 확장 | 설치됨 |
| `public.speech_analysis` | 존재함 |
| `public.admin_knowledge_documents` | 없음 |
| `public.admin_knowledge_chunks` | 없음 |

따라서 현재 발언 통계는 PostgreSQL 숫자 배열에 저장한 전문 임베딩을 Backend에서 비교하는 기능으로 설명한다. 별도 운영 자료 검색은 pgvector·키워드 혼합 검색 코드와 migration이 있으나 이 팀 DB에 색인 테이블이 없어 운영 완료로 표현하지 않는다. 관리자 질문 API의 답변 구성도 외부 LLM을 호출하지 않는 추출형이다. RAG는 검색→근거 연결→생성 개념과 후속 연결 방향으로 명시하며, 색인 적용·자료 적재·학습 임베딩 검토·LLM 생성·관리자 질문 UI 연결을 완료 사실과 구분한다.

## 대표 샘플 생성·검토

- 생성일: 2026-09-09. 구성·이미지 배치·밝은 테크 스타일·내장 ImageGen 사용을 사용자에게 승인받은 뒤 Slide 5 한 장을 생성했다.
- 백엔드: built-in image tool, 실제 호출 도구 `image_gen__imagegen`. 최초 의도는 `generate`이며, 사용자 요청을 반영한 현재 수정본은 `edit`이다. 별도 API/CLI는 사용하지 않았다.
- 사용 프롬프트: [sample_prompt.draft.md](sample_prompt.draft.md)의 ‘전달 프롬프트’로 생성하고 ‘수정 프롬프트 1’로 수정했다. 수정 입력은 기존 샘플을 `view_image`로 확인한 뒤 `referenced_image_paths`로 전달했다. 구체 모델·품질 옵션은 이 도구가 노출하지 않는다.
- 결과: [origin_image/slide_05.png](origin_image/slide_05.png), 1672×941 PNG, 1,377,810 bytes. 도구 원본과 저장 파일의 SHA-256 일치를 확인했다. 로컬 그리기·재배치·리사이즈·오버레이는 사용하지 않았다.
- 현재 수정본 SHA-256: `11ae5070344d24061085d1d8c15741e0c078915dc36078678a37944b20e80b56`. 최초 생성본 SHA-256은 `b71a6ef1d7f0a9c25c6743dd9e38ffcce95925b671c78e4630d81ca9f327f6d4`이며 도구 기본 저장 위치에 보존되어 있다.
- 비율 확인: 도구 반환 크기는 정수 픽셀 반올림으로 정확한 16:9와 약 0.053% 차이가 있다. 원본을 유지하며 최종 PPTX의 캔버스는 16:9로 조립한다.
- 시각 검토: 서버 A~E 다섯 개 각각의 ‘독립 환경 · 실행 중’ 상태, Backend 내부 Agent Orchestrator·Game Engine, 외부 LLM 구분, 일곱 개 연결과 방향, 한글 표기, 제목·본문 잘림, 겹침을 다시 확인했다. MCP에서 DB나 LLM으로 향하는 잘못된 직접 연결은 없다.
- 수정 사항: 사용자의 ‘각 서버가 별도 환경에서 실행 중이라고 가정’ 요청에 따라 다섯 개 독립 서버의 실행 상태와 네트워크 통신을 강조했다. 상단 ‘분산 실행 가정’은 이를 실제 원격 배포 검증 결과와 구분한다.
- 상태: 수정 샘플과 전체 제작을 승인받았다. 나머지 15장은 슬라이드별 작업자에게 위임하고, 결과를 부모 작업자가 확인한 뒤 `record_slide_result.py`로 저장했다. 16장 한국어 대본을 PPTX 발표자 노트에 넣었고 PDF 미리보기도 생성했다.

## 이번 단계의 확인 범위

- 16장 시간 합계 900초와 사용자 요청 항목 대응을 확인한다. 추가된 11장은 55초이며 개발 문제 해결 세 사례는 200초를 유지한다.
- 문서 링크·필수 원본 경로·캡처 화면을 확인한다.
- 시스템 연결 방향, Tool 개수, HUMAN 전용 커스텀 경계, StateGraph 미구현 여부를 코드와 비교한다.
- 관리자 실제 화면 두 장, 발언 분석 저장·유사도 계산, 운영 자료 검색의 pgvector 코드·DB 적용 범위와 추출형 답변을 확인했다.
- 애플리케이션 코드는 변경하지 않았으므로 자동 테스트·lint·전체 회귀는 실행하지 않는다. 과거 테스트 통과 수를 이번 실행 결과로 보고하지 않는다.
- 구성·원본 배치·스타일·백엔드·수정 샘플·전체 제작과 원본 화면 직접 삽입을 승인받았다. 최종 16장 렌더, 발표자 노트와 원본 이미지의 일치, 생성 출처·도형 경계를 확인했다. 최종 경로·재생성 내역·검증 범위는 [제작·검증 기록](qa_report.md)에 정리했다.
