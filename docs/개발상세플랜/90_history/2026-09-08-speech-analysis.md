# 공개 발언 분석 구현·검증 이력 (2026-09-07 ~ 2026-09-08)

루트 README의 변경 기록에서 옮긴 문서입니다. 공개 발언 분석(임베딩·주장 추출·
투표 보조)의 구현 범위, migration 006·008 적용, Team DB 적용과 브라우저 실게임
점검 기록을 다룹니다. 현재 활성화 방법과 설정 기본값은 루트 README를 참고하세요.

## 공개 발언 분석 구현 범위

확정된 사용자·AI 공개 발언의 실시간 임베딩·주장 저장, 누적 핵심 요약 조회와
투표 보조 화면을 구현했습니다. [마스터플랜의 구현 착수 결정](../01_core/AI_MAFIA_MASTER_PLAN.md#8-구현-착수-결정-2026-09-07)과
아래 활성화 절차를 따릅니다. 배포 기본값은 비활성이며, 현재 실행 환경은 후속
요청에 따라 활성화했습니다. 관리자용 64차원 해싱과 분리된 실제 의미 임베딩을 사용합니다.

## 실시간 공개 대화 요약과 발언 분석

사용자·AI의 확정된 `PUBLIC / PLAYER_SPOKE` 발언을 별도 worker가 분석합니다.
첫날·열린 토론에서도 발언 확정 후 다음 탐색 주기부터 임베딩·주장 추출을 시작합니다.
PASS, 미확정 입력·모델 응답, private context·내부 사고는 분석하지 않습니다.
**대화 요약과 발언 분석**에서 현재 토론/게임 누적 범위의 발언별 핵심 요약과 원문을
확인할 수 있습니다. 새 발언으로 창이 바뀌어도 같은 토론의 범위 선택은 유지합니다.
요약에는 화자를 표시하고 검증된 `proposition` 최대 3개를 연결하며 최신 20발언과
생략 수를 표시합니다. 별도 모델이 전체 대화를 다시 해석하는 종합 문단은 아닙니다.
분석된 주장부터 부분 결과로 표시하며 빈 주장 배열은 요약 항목을 만들지 않습니다.

투표·재투표·최종 지목에서는 지목 순위, 유사 주장과 후보별 의심·옹호·질문 근거도
제공합니다. 고유 발언자 수로 집계하므로 같은 사람의 반복 지목은 한 명입니다.
기간 중 지목 이력이며 실제 투표 의향이나 마피아 확률을 뜻하지 않습니다. 유사 주장은
같은 대상·입장·논점의 다른 발언자끼리 전문 임베딩 cosine 0.88 이상에서 묶습니다.
현재 논점은 알리바이·역할 주장·진술 변화이며, 숫자나 직업 근거가 다르거나 부정·인용이
불명확하면 묶음을 생략합니다. 모든 유사 표현을 표시하거나 사실을 판정하지 않습니다.

**투표 직전 분석 대기는 유지합니다.** 실시간으로 완료한 결과는 재사용하고 남은 분석이
끝나거나 단계별 재시도를 소진하면 투표 창을 열어 그때부터 30초를 계산합니다.
첫날 밤 전환은 대기하지 않으며 분석 비활성·초기화·DB 장애 시 게임 진행을 유지합니다.
게임 저장은 분석 완료를 기다리지 않고 직전 확정 게임 상태를 저장합니다. 저장·종료·실패
게임은 새 분석을 선점하지 않으며, 저장 직전 이미 시작한 유효 lease 결과는 보존할 수
있습니다. 재개하면 미완료 단계를 이어가고 삭제 후 늦은 결과는 버립니다.

Front는 기존 텍스트·expander로 요약과 원문을 표시합니다. 원문에는 event ID·시점이
함께 표시되며 타임라인 직접 이동은 구현하지 않았습니다. 보조 요청은 최대 0.75초이고
매초 타이머에서는 호출하지 않습니다. 토론에서는 READY·실패도 다음 공개 기록 갱신에
재조회하고 투표에서는 고정 cutoff의 완료 결과를 캐시합니다. 조회 오류가 입력·투표·저장을
막지 않으며, 저장 중에는 조회를 중단합니다.

Backend는 `speech_analysis`에 단계별 결과·재시도·선점 토큰을 저장합니다.
`speech_analysis_versions`의 최초 활성 시점과 기존 분석 버전을 유지합니다. 모델 호출 중에도
다음 polling 주기의 원문 탐색은 계속하며, 빈 실행 슬롯만 선점합니다. 임베딩이 성공한 뒤
주장 분석이 실패해도 성공한 벡터를 재호출하지 않습니다. 마지막 허용 시도 중 프로세스가
종료된 작업은 lease 만료 후 `FAILED / LEASE_EXPIRED`로 정리합니다.

토론 조회 cutoff는 같은 읽기 snapshot의 최대 공개 sequence+1이고 투표는 window의
최초 공개 개설 sequence로 고정합니다. GET은 DB 쓰기·모델 호출 없이 저장된 결과를
조합합니다. 분석은 게임 원장·state_version을 변경하지 않으며 모델 입력은 공개 player
ID·좌석·이름과 확정 원문으로 제한합니다.
조회 서비스와 DB 연결 설정은 기존 `runtime_factory.py`에서 조립하고 앱에 주입합니다.
HTTP router는 입력 검증과 서비스 호출만 담당합니다.

## migration 006·008 적용 절차

기존 001~004 스키마가 있는 DB에 Backend 소유의
`backend/migrations/006_create_speech_analysis.sql` 다음
`backend/migrations/008_allow_public_human_speech_analysis.sql`을 적용해야 합니다. 008은
공개 사용자 발언을 허용하도록 기존 검증 함수만 교체하고 테이블·열·권한을 추가하지 않습니다. 006은
PostgreSQL `double precision[]`를 사용해 pgvector와 관리자용 005에 의존하지 않습니다.
전체 migration runner는 기존처럼 005도 실행하므로, pgvector가 없는 기존 DB에는
MCP/Data 담당자가 검증된 DDL DSN으로 006 다음 008을 적용합니다. 실행 위치는 저장소 루트입니다.

```bash
backend/.venv/bin/python - <<'PY'
from pathlib import Path
import psycopg
from backend.app.core.config import Settings

try:
    settings = Settings.from_migration_env()
    with psycopg.connect(settings.effective_migration_database_url, autocommit=True) as connection:
        for name in ("006_create_speech_analysis.sql", "008_allow_public_human_speech_analysis.sql"):
            connection.execute((Path("backend/migrations") / name).read_text(encoding="utf-8"))
except Exception:
    raise SystemExit("speech analysis migration failed; verify the DDL target and permissions") from None
print("speech analysis migrations applied")
PY
```

DDL 대상과 runtime 대상은 같은 DB여야 합니다. runtime은 `speech_analysis`에
SELECT/INSERT/UPDATE, `speech_analysis_versions`에 SELECT/INSERT만 필요하며
DDL·원본 삭제 권한은 필요하지 않습니다. 실행 환경의
계정 분리가 적용돼 있다면 MCP/Data 담당자가 새 테이블 권한도 함께 부여해야 합니다.
설정은 `.env.example`의 `SPEECH_ANALYSIS_*`를 따릅니다.

## 운영값 조정 (2026-09-08)

2026-09-08 현재 `.env`는 분석을 활성화한 상태에서 아래 세 운영값을 조정했습니다.
위 표와 `.env.example`의 배포 기본값은 유지합니다.

| 설정 | 변경 | 이유 |
|---|---|---|
| `SPEECH_ANALYSIS_POLL_SECONDS` | `1` → `0.5` | 다음 발언 탐색·빈 실행 슬롯 확인까지의 대기 단축 |
| `SPEECH_ANALYSIS_BATCH_SIZE` | `16` → `32` | 매 탐색의 발언 등록·분석 단계 처리 한도 확대 |
| `SPEECH_ANALYSIS_CONCURRENCY` | `2` → `4` | 앱 하나의 동시 모델 요청 상한 확대 |

한 발언은 임베딩·주장 추출 두 단계이므로 batch 32가 발언 32개 완료를 뜻하지는
않습니다. polling 간격은 짧은 DB 탐색·선점 작업 뒤 대기이며 진행 중 모델의 완료를
기다리지 않습니다. 슬롯이 모두 사용 중이면 다음 주기에 다시 확인하므로 0.5초 안에
분석 완료를 보장하지 않습니다. 여러 Backend를 띄우면 동시성은 프로세스별로 합산됩니다.

`text-embedding-3-small`·1536차원·`gpt-4.1-mini`·`v1`, timeout 30초·최대 시도 3회는
유지했습니다. 1536차원은 현재 코드의 고정 지원 조합이며
[OpenAI 임베딩 문서](https://developers.openai.com/api/docs/guides/embeddings)의 기본 차원과
일치합니다. [GPT-4.1 Mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini)는
Responses 구조화 출력과 낮은 지연의 주장 추출에 적합한 기본 선택입니다. 실제 한국어
정확도·계정 rate limit·처리 지연을 측정하지 않은 상태에서 모델이나 분석 버전을 바꾸면
불필요한 재분석과 결과 혼합 위험이 있어 유지합니다.

2026-09-08 후속 코드 변경으로 실시간 공개 사용자·AI 발언 분석과 누적 핵심 요약 조회를
추가했습니다. 현재 `.env`의 모델·차원·버전·poll 0.5초·batch 32·동시성 4·timeout 30초·
최대 시도 3회는 그대로 사용합니다. 후속 사용자 요청으로 **Team DB의 008 migration을
적용했습니다**. Backend·Front 재시작은 이번 마이그레이션 요청에서 수행하지 않았습니다.
별도 전체 대화 종합문 생성 단계는 추가하지 않았습니다.

앞선 설정 조정에서는 loader 검증과 Provider·worker 92개 테스트, 실제 설정으로
합성 32단계 완료·동시성 4 준수를 확인했습니다. 후속 코드 검증 결과는 아래 기록합니다.

## 실시간 확장 검증 (2026-09-08, WU-B14)

Orca에서 B11 저장소, B12 worker, F9 화면, M9 격리 DB 작업을 추적하고 결과를
통합했습니다. 기존 변경을 보존했으며 커밋·푸시는 만들지 않았습니다.

| 검증 | 결과 |
|---|---|
| 저장소 / Provider·worker / 조회 API | 93 / 100 / 81 통과 |
| 실제 PostgreSQL 연결 / migration runner / Front 요약 화면 | 25 / 51 / 62 통과 |
| 관련 테스트 합계 | **412 통과** |
| 격리 DB의 008 재실행·행/권한 보존·원문 거부·동시 선점·lease | **57개 검증 통과** |
| Backend 전체 회귀 | **925 통과, 기존 14 실패, 8 건너뜀** |
| Front 전체 회귀 | **452 통과, 기존 7 실패** |

Backend 기존 실패는 Agent activity fake의 `_ai_worker`·`llm_max_output_tokens` 누락,
Agent/Redis/직접 SQL 계층 검사와 MCP context fake 응답입니다. Front 기존 실패는
countdown·최종 지목 문구와 identity/result 버튼 selector 불일치입니다. 이번 기능 밖의
실패는 변경하지 않았습니다. Backend의 B6_LOCAL_QA 선택 검증 8개는 활성화하지 않았고,
발언 분석 DB 통합은 전용 loopback QA DB에서 실제로 실행했습니다. 유료 모델 품질·실서비스
부하·강제 종료 검증은 요청 범위와 외부 비용을 고려해 생략했습니다. 모델은 fake로 대체했습니다.

전체 회귀는 root `.venv`에서 각각 `backend/tests`와 `frontend_user/tests`를 실행했습니다.
Backend는 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`과 `-p pytest_asyncio.plugin -p anyio.pytest_plugin`을
사용하고 DB 환경은 전용 QA 주소로 덮어썼습니다. DB 연결 검증은
`VOTE_INSIGHT_TEST_DATABASE_URL`의 loopback `mafia_vote_insights_qa_` DB만 허용합니다.
위 코드 검증 시점에는 실제 서비스 DB·프로세스를 변경하지 않았습니다. 이후 승인된
Team DB 008 적용 결과는 다음 절을 따릅니다.

기존 `OPENAI_API_KEY`를 재사용하되 게임 Agent와 별도 요청이므로 활성화하면 추가
API 사용량이 발생합니다. 분석 DB 연결·명령·잠금 대기는 각각 5초·5초·1초로 제한합니다.
초기화나 종료 실패도 고정 오류 코드만 기록하고 게임 lifespan과 분리합니다.
`enable_background_worker=False`인 테스트 앱에서는 분석 worker도 기동하지 않습니다.
실제 한국어 모델 분류 품질·처리 지연 목표는 유료 호출 없이 입증할 수 없으므로
합성 회귀 결과와 구분하며, 사용자에게 표시하는 분석은 항상 원문 확인용 참고 정보입니다.

## Team DB 008 적용 완료 (2026-09-08, WU-M9)

사용자의 명시 요청으로 `.env`의 `TEAM_DATABASE_URL`이 가리키는 `4team_db`에
`008_allow_public_human_speech_analysis.sql`의 검토된 함수 교체를 적용·커밋했습니다.
전용 DDL URL이 없는 기존 환경이므로 같은 Team 계정의 실제 함수 소유권·DDL 권한을
검증한 별도 관리 연결을 사용했습니다. 셸 환경변수 덮어쓰기·dotenv 보간을 사용하지 않고
대상을 고정했으며 `.env`·접속 계정·권한은 변경하지 않았습니다.

적용 transaction의 같은 REPEATABLE READ snapshot에서 `games` 11행,
`game_events` 2,129행, `game_players` 76행, `action_windows` 695행,
`speech_analysis` 115행, `speech_analysis_versions` 1행의 행 수·내용 해시가 전후
일치했습니다. 이는 적용 시점의 보존 검증이며 실행 중 서비스의 이후 데이터 증가를
막거나 같은 수치로 고정한 것은 아닙니다. 함수 OID·소유권·ACL·실행 설정과 기존
트리거·relation 메타데이터도 보존됐습니다. commit 후 독립 읽기 연결에서 정확한
008 함수 본문·활성 트리거·DB health를 재확인했습니다.

006 재실행·다른 migration·게임/분석 데이터 보정·서버 재시작·유료 모델 호출은
수행하지 않았습니다. 적용 SQL에 변경이 없어 직전 412개 관련 테스트·57개 QA 검증과
전체 회귀 결과를 재사용했으며 서비스 DB에서 자동 테스트나 합성 데이터를 실행하지
않았습니다. root README·마스터플랜·DB 운영 기록만 갱신했고 커밋·푸시는 하지 않았습니다.

## 원격 연결 전환 (2026-09-07)

후속 요청으로 원격 `4team_db`에 006을 적용하고
`.env`의 `AI_MAFIA_STORAGE_MODE=team`으로 현재 Backend 연결을 전환했습니다.
`run_openai.sh`는 `TEAM_DATABASE_URL`과 `REDIS_URL`을 사용하며 분석 설정은 켜져 있습니다.
원격 `public.speech_analysis.embedding`에 1536차원 벡터를 저장하고, 기동 직후
공개 발언 2개의 임베딩·주장 `READY` 저장을 확인했습니다. 로컬의 기존 게임·분석 데이터는
보존했으며 원격으로 복제하지 않았습니다. 다음 실행도 `./run_openai.sh`를 사용합니다.

원격 DDL은 기존 계정의 소유권·DDL 권한과 대상을 확인한 별도 관리 연결에서 006만
적용했습니다. 적용 전후 게임 118개를 포함한 기존 23개 테이블의 행수·내용 집계·권한·
소유자가 일치했고 새 제약·인덱스 6개·트리거·함수가 정상입니다. 현재 원격 접속 계정도
기존 superuser를 재사용하므로 운영용 runtime/DDL 최소 권한 분리는 미적용입니다.
서버 전환 후 Backend health/readiness와 Front health는 200이며 DB·Redis 연결이 정상입니다.
스크립트의 설정 선택·누락값·격리 보호 8건과 `bash -n`, 실제 `--check`를 확인했습니다.
MCP 초기화·도구 목록 조회도 통과했습니다. 별도 격리 QA에서 실행한 Backend 전체 회귀는
751 통과·기존 14 실패·8 건너뜀이며, 변경 없는 Front·MCP 전체 회귀는 직전 결과를
재사용했습니다. 원격에서는 합성 테스트 데이터 작성과 전체 회귀를 수행하지 않았습니다.

## 브라우저 실게임 점검 (2026-09-08, WU-B14)

기존 원격 연결과 모델로 09:06~09:11 KST에 6인 게임 한 판을 진행하여 2일차 낮 투표 후
시민 승리·COMPLETED를 확인했습니다. 브라우저에서 다른 AI 발언 수신 후 채팅 초안이
유지되고 Enter keydown으로 인간 발언이 공개 원장에 등록됨을 확인했습니다. OS 키 입력
자체의 검증과는 구분합니다. 투표 제출은 반영되지 않아 인간 표가 시간 만료 자동 선택으로
처리됐으며 직접 투표 성공으로 집계하지 않습니다.

투표 개설 직후 게임 누적 AI 발언 8개 중 임베딩 2개(1536차원), 주장 분석 0개만 준비됐고
게임 종료 때도 같은 상태였습니다. 현재 토론 범위는 4개 모두 미처리였으며 지목 순위·유사
주장은 비어 있었습니다. 투표 보조 API는 두 범위에서 HTTP 200, 관측한 최초 응답 시간은
각각 369ms·455ms였습니다. 이 단일 표본으로 지연 목표나 한국어 검색 품질을 판정하지 않습니다.
현재 임베딩은 인간의 투표 참고 조회용이며 AI 판단에 검색 결과를 재주입하는 RAG는 미구현입니다.

종료 후 원격 DB에서 준비 판정 SQL만 읽기 전용으로 실행하면 미완료에 대해 `False`를
반환했습니다. 원장의 투표 전환 transaction은 토론 마감 3.197초 뒤 실행됐지만 로컬
진행 로그에는 해당 state version의 전환이 없고, 로컬 프로세스는 2.4초 뒤 열린 투표를
처음 관측했습니다. 로컬 Backend 재시작 뒤 진행된 다른 게임에서도 투표 전환은 로컬 로그에
없고 후속 투표 처리만 기록됐습니다. 각 Backend의 scheduler가 소유자나 배포 instance 구분
없이 공유 DB의 모든 마감 게임을 조회하며, 이를 직렬화하거나 호환 버전을 강제하는 분산
lease가 없습니다. 따라서 다른 Backend instance가 분석 비활성·초기화 실패 또는 B14 이전
코드로 먼저 전환하면 현재 instance의 대기 판정을 우회합니다. 실제 게임에서는 마감 뒤 두
임베딩이 선점됐지만 외부 전환으로 SPEECH 창이 닫혀, 완료된 두 벡터 외 나머지 임베딩과
모든 주장 분석이 더 이상 선점되지 않았습니다. 조기 활성화의 원인 범주는 **공유 DB에 연결된
호환되지 않는 별도 Backend scheduler**로 확정했으며, 과거 DB statement/connection log와
commit timestamp가 비활성이라 해당 원격 프로세스의 호스트·설정은 사후 특정할 수 없습니다.

분석 버전 활성화 뒤 열린 투표 창 37개를 읽기 전용으로 점검하면 29개에 분석 대상이 있고,
그중 21개는 개설 시점에 모든 분석이 READY가 아니었습니다. 재시도 소진 실패도 허용되므로
21개 전체를 오류로 단정하지 않지만, 이번 게임처럼 시도 0인 PENDING 행이 남은 최근 사례는
대기 계약 위반입니다. 후속 진단을 위해
기존 runtime 운영 로그의 `SPEECH_ANALYSIS_PRE_VOTE_FAILED`에 게임·행동 창·PID와 고정
실패 사유를 추가하고, 이 프로세스가 실제 확정한 전환만 `DISCUSSION_TRANSITION_APPLIED`에
분석 준비/비활성/불필요/실패 상태로 기록합니다. 예외 원문·발언·접속 정보는 기록하지 않습니다.
분석 실행 시점·장애 우회 정책·DB 원장은 변경하지 않았습니다.

격리 PostgreSQL과 fake Provider로 원문→양 분석 단계→투표 개설→근거 조회, 전환 경쟁과
비밀정보 비노출을 포함한 focused 검증 **22개가 통과**했습니다. Backend 전체 회귀는
**811 통과·기존 14 실패·8 건너뜀**으로 기존 실패 목록과 같습니다. 실패는 activity fixture
8개, Agent/Redis import 경계 각 1개, MCP fake 3개, action SQL 경계 1개입니다.
8개는 별도 B6 opt-in 검증이며 변경 없는 Front·MCP 전체 회귀와 추가 유료 게임은 생략했습니다.
원격 합성 데이터 작성·migration·commit·push는 하지 않았습니다.

## 후속 로그 점검 (2026-09-07)

점검 시 원격 공개 발언 31개가 임베딩·주장 모두 `READY`였고 분석 실패는 없었습니다.
기존 게임 한 개는 4일차 `DAY_DISCUSSION`, `state_version=35`에서 `FAILED`·
`WORKER_FAILED`를 반복했습니다. 읽기 전용 DB 조회와 메모리 엔진 재현으로, 3일차와
4일차에 같은 `round=3`, `cycle=1`을 사용한 기존 게임의 과거 발언이 현재 토론 상태에
섞여 현재 AI의 `PASS`가 `DUPLICATE_ACTION`으로 거부되는 경로를 확인했습니다. 당시 저장된
판단 재적용이 반복됐고 worker 실패 로그는 원인 코드를 보존하지 않았습니다. 후속 수정은
현재 날짜·연속 phase 진입 버전의 제출만 복원하고 운영 로그에 허용된 고정 원인 코드를
남깁니다. 진입 이벤트가 없는 불완전 이력은 과거 발언을 임의로 섞지 않고 빈 발언 이력으로
복원합니다. 원격 DB 읽기 전용 조회에서도 해당 AI가 이미 행동한 것으로 잘못 복원되지
않음을 확인했습니다.

투표 준비 sweep을 별도 작업으로 분리해 분석 DB 지연이 다른 게임의 기존 투표 처리를
막지 않도록 했습니다. 구형 순차 토론도 마지막 행동을 한 번 저장한 뒤 마감된 SPEECH
창에서 분석을 기다리며, 저장·재개와 재시작 후 같은 원장으로 복구합니다. 추가 migration과
직접 게임 데이터 보정은 필요하지 않습니다. 변경 관련 focused 검증은 격리 PostgreSQL의
원장→분석→투표 개설→조회 연결을 포함해 124건 통과했습니다.

후속 Backend 전체 회귀는 **806 통과·기존 14 실패·8 건너뜀**이며 직전 결과와 비교한
새 실패는 없습니다. 기존 실패는 activity fixture 누락 8건, Agent/Redis import 경계
각 1건, MCP fake cache 3건, 기존 action SQL 경계 1건입니다. 변경 없는 Front·MCP
전체 회귀와 유료 모델 자동 테스트는 재실행하지 않았습니다. 006 파일 hash와 diff를
확인했고 commit·push는 하지 않았습니다. 같은 원격 연결로 서버를 재기동한 뒤
Backend health/readiness·Front health가 200이고 실제 MCP 요청도 성공했습니다.
기존 중단 게임은 상태 버전 35에서 37 이후로 진행했으며 점검 구간의 실패 로그는 0건입니다.
새 토론 발언의 양 분석 단계는 PENDING·시도 횟수 0으로 유지됨을 원격 읽기 전용으로 확인했습니다.

## 이전 로컬 활성화 기록 (2026-09-07)

기존 `run_openai.sh`가 사용하는 `127.0.0.1:55432/mafia_qa`에 006을 적용하고
Git 제외 `.env`의 분석 설정을 켰습니다. 기존 OpenAI 키와 다른 설정은 보존했습니다.
Orca의 **AI 마피아 실행** 터미널이 Backend `http://127.0.0.1:18000`,
MCP `http://127.0.0.1:18100/mcp`, 사용자 화면 `http://127.0.0.1:18501`을 관리합니다.
주소는 원격 전환 뒤에도 같습니다.

마이그레이션 전후 기존 게임 19개와 이벤트·플레이어·행동창, 기존 객체 권한의 보존을
확인했습니다. 이 로컬 QA는 기존 `qa` owner/superuser 계정을 그대로 사용하므로 위의
운영용 최소 권한 계정 분리는 적용되지 않았습니다. 당시에는 공유 원격 DB를 변경하지 않았습니다.
기동 후 Backend health/readiness와 Front health는 200, MCP 초기화·도구 목록 조회는
정상이었으며 당시 진행·저장 게임의 공개 AI 발언 **30개가 임베딩·주장 모두 READY**였습니다.
활성화 이전 종료 게임은 자동 역채움 대상에서 제외됩니다.

실제 OpenAI 임베딩 1536차원과 합성 발언의 주장 추출도 확인했습니다. 이 과정에서
모델이 한국어 인용문의 글자 위치를 잘못 계산하는 문제를 재현해 수신부에서 보완했습니다.
정확한 인용이 원문에 한 번만 있을 때 위치를 재계산하고 엄격 검증하며, 모호한 반복
인용이나 없는 문장은 거부합니다. 분석 revision은 `claims-ko-v2`입니다. 이 보완 후
Backend 전체 회귀는 **751 통과·기존 14 실패·8 건너뜀**입니다. 변경 없는 Front·MCP
회귀는 아래 결과를 재사용했으며 별도 실게임 플레이 E2E와 대규모 품질·부하 평가는 생략했습니다.

## 최초 구현 검증 (2026-09-07)

최초 구현 단계의 발언 분석 검증(2026-09-07)은 모델 호출을 fake로 대체했습니다. 격리 PostgreSQL에서
006 재적용·재실행, 기존 행 보존, 최소 권한, 동시 선점, 종료 게임 탐색, lease 만료와
위조 원본 거부 등 108개 assertion을 확인했습니다. API·worker·원장 연결을 포함한
통합 테스트 5개와 마지막 조립 수정의 관련 회귀 129개가 통과했습니다.
전체 회귀는 Backend **729 통과·기존 14 실패·8 건너뜀**, 사용자 Front
**388 통과·기존 8 실패**, 관리자 Front **18 통과**, MCP **44 통과**입니다.
Backend의 남은 실패는 병합 검증에 기록한 기존 14건과 동일하며, 건너뛴 8건은
별도 고정 QA DB를 사용하는 B6 opt-in 검사입니다. 사용자 Front의 타이머·투표 안내
3건과 UUID 설정·결과 CTA 5건도 새 연결을 제외한 기존 코드에서 동일하게 재현했습니다.
이 기존 실패들은 이번 기능 범위에서 수정하지 않았습니다. 유료 모델 품질·부하 측정과 실제
서비스 DB migration·프로세스 재시작·브라우저 실게임 E2E는 수행하지 않았습니다.

새 기능의 focused 검증 명령은 다음과 같습니다. DB 통합 3개는
`VOTE_INSIGHT_TEST_DATABASE_URL`에 loopback의 `mafia_vote_insights_qa_`로 시작하는
격리 DB를 지정할 때만 실행됩니다. 해당 DB에 001~004·006·008을 먼저 적용해야 합니다.

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -p pytest_asyncio.plugin -p anyio.pytest_plugin \
  backend/tests/test_speech_analysis_repository.py backend/tests/test_speech_analysis_provider.py \
  backend/tests/test_speech_analysis_worker.py backend/tests/test_vote_insights.py \
  backend/tests/test_vote_insight_integration.py -q
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 frontend_user/.venv/bin/python -m pytest -c pyproject.toml \
  frontend_user/tests/test_vote_insights_f9.py -q
```
