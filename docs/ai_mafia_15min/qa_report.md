# AI MAFIA 발표 자료 — 제작·검증 기록

2026-09-09, 승인된 **16장·15분·16:9 한국어 발표 자료**를 완성했다. 수정 샘플 1장과 슬라이드별 생성 결과 15장을 조립했고, 발표자 노트 16개와 원본 화면 8개를 포함했다. 미완료 슬라이드나 남은 제작 차단 사유는 없다.

## 산출물

| 항목 | 경로 |
| --- | --- |
| 프로젝트 폴더 | `docs/ai_mafia_15min/` |
| 발표 파일 | [ai_mafia_15min.pptx](ai_mafia_15min.pptx) |
| PDF 미리보기 | [ai_mafia_15min.pdf](ai_mafia_15min.pdf) |
| 발표 대본 | [speech.md](speech.md) |
| 구성·장별 시간표 | [outline.md](outline.md) |
| 내용 근거·캡처 기록 | [sources.md](sources.md) |
| 생성 배경 이미지 | [origin_image/](origin_image/) — `slide_01.png`부터 `slide_16.png` |
| 개별 생성 작업 | [prompts/](prompts/) |
| 작업 결과·생성 출처 | [slide_jobs.json](slide_jobs.json) |
| 실행 상태 | [slide_run_state.json](slide_run_state.json) |
| 승인·디자인·원본 예외 계약 | [deck_spec.json](deck_spec.json) |
| 원본 화면 삽입 코드 | [insert_original_screens.py](insert_original_screens.py) |

## 요청 사항 반영

| 요청 | 슬라이드 |
| --- | --- |
| 주제와 선정 이유 | 1–2 |
| 기존 플레이 제약과 팀의 해결 방향 | 3 |
| 실제 홈·역할·게임 화면 | 4, 8 |
| 사용자 Front·관리자 Front·Backend·MCP·DB의 독립 실행 환경 | 5 |
| AI Agent, Resource·Prompt·Tool과 행동 반영 과정 | 6–7 |
| 현재 커스텀 능력 조합·후속 AI Tool 구성 예시 | 9–10 |
| Workflow와 Agent의 확장성 | 10 |
| 실제 관리자 화면·발언 벡터 분석·pgvector·RAG 확장 | 11 |
| 개발 문제와 해결: 투표·채팅 입력·반복 대화 | 12–14 |
| 의의·상품화 가능성·다음 단계 | 15–16 |

## 생성과 수정

- 백엔드는 전체 과정에서 **built-in image tool / `image_gen__imagegen`**을 사용했다. 별도 API·CLI 생성 경로는 사용하지 않았다.
- 수정된 Slide 5를 사용자가 승인했고, 동일한 편집 방식과 스타일 참조를 다른 15개 슬라이드 작업에 전달했다. 구체 모델·품질 옵션은 도구가 노출하지 않는다.
- Slide 5는 `accepted`, 나머지 15장은 모두 `recorded`다. 각 작업자의 실제 반환 경로와 해시, QA 메모를 `record_slide_dispatch.py`와 `record_slide_result.py`로 기록했다. 최종 실행 상태는 `assembled`다.
- 샘플은 다섯 서버가 각각 독립 환경에서 실행 중이라는 가정으로 수정했다. 9장은 특수 직업 열람이 **진영이 아니라 직업을 표시**한다는 본문을 수정하고, 확대 PDF 렌더로 최종 단어를 확인했다. 12·13·15장은 생성 과정의 과도한 설명·중복 요소·근거 없는 표현을 정리한 후보를 선택했다.
- 4·8·9·11장의 생성된 화면은 문구·수치·배치가 재구성되는 문제가 있었다. 사용자가 승인한 예외에 따라 해당 영역 전체를 가리고, 실제 JPEG 원본을 PowerPoint 이미지로 직접 삽입했다. 이미지 원본을 수정하지 않고 PowerPoint 자르기 속성만 사용한다. 이 네 장의 최종 화면은 PPTX/PDF가 기준이며 `origin_image/`는 삽입 전 디자인 배경이다.
- 상태 도구가 기록 후 재작업 전환을 지원하지 않아, 원본 삽입 승인 시점과 9장 최종 수정 시점에 번들 준비 도구로 상태를 초기화하고 실제 작업 이력을 다시 기록했다. 상태를 수동 변경하거나 새 생성 결과가 없는 작업을 생성 완료로 처리하지 않았다.

## 검증 결과

| 검증 | 결과 |
| --- | --- |
| 승인된 구성과 시간 | 16장, 합계 900초 |
| 최종 PPTX 열기·슬라이드 수 | `python-pptx`로 정상 로드, 16장 |
| PowerPoint 캔버스 | 정확한 16:9 |
| 발표자 노트 | `speech.md`의 16개 본문과 PPTX의 노트 16개가 일치 |
| 생성 배경 보존 | PPTX 내부 배경 16개가 `origin_image/` 파일과 바이트 단위로 일치 |
| 원본 스크린샷 보존 | 홈·역할·토론·대화·직업 설정·능력 선택·관리자 지표·발언 분석 8개 JPEG가 PPTX 내부 이미지와 바이트 단위로 일치 |
| 생성 출처 | 비샘플 15개 모두 선택 백엔드 일치와 최종 파일 SHA-256 확인 |
| 배치 범위 | 모든 도형이 슬라이드 안에 있고, 이미지 자르기 범위가 유효함 |
| PDF 변환 | LibreOfficeDev 26.8로 정상 변환, `pdfinfo` 16페이지 확인 |
| 시각 검토 | Poppler 렌더 16장 확인. 원본 삽입 네 장은 가장자리와 남은 UI 조각 수정 후 다시 렌더해 확인 |
| 내용·가독성 | 제목·핵심 문구·화살표·현재/후속 표기·주요 숫자·화면 표시 확인 |
| 문서 링크 | 구성안·근거·샘플 기록의 로컬 참조 누락 없음 |

발표 대본은 900초 배분에 맞춰 작성했다. 실제 발화 시간을 측정한 리허설 결과는 아니므로 발표자의 속도에 따라 조정할 수 있다. 질의응답 시간은 15분에서 제외했다.

## 내용과 형식의 범위

- 분산 구조는 사용자 요청에 따라 다섯 독립 서버가 실행 중인 가정으로 설명했다. 다섯 원격 서버 동시 기동을 이번 제작에서 검증했다는 의미는 아니다.
- 현재 커스텀 능력은 인간 플레이어 전용이다. 사용자가 AI의 Tool을 구성하는 예시는 후속 확장으로 표시했다.
- 발언 분석은 PostgreSQL 배열 임베딩 비교다. 별도 pgvector 검색 코드와 RAG 생성 연결의 후속 범위를 구분했다. DB 적용 여부와 화면 숫자는 2026-09-09 조사·캡처 시점 기준이다.
- 개발 사례의 수치는 날짜와 관찰 범위를 함께 제시했다. 전후 범위가 다른 투표 기록을 일반적인 개선율로 계산하지 않았다. 상품화 항목은 검증할 가설이다.
- 배경의 본문·도식은 이미지형이므로 개별 텍스트 상자로 편집할 수 없다. 발표자 노트와 직접 삽입한 실제 화면은 PowerPoint 개체로 편집할 수 있다.
- 이번 작업에서 애플리케이션 코드는 변경하지 않았다. 문서·발표 자료 작업 지침에 따라 앱 단위 테스트·lint·전체 회귀·유료 API 통합 테스트를 생략했다. 기존 개발 기록의 테스트 결과를 이번 실행 결과로 보고하지 않았다.
- 기존의 무관한 작업 변경을 보존했다. 커밋과 푸시는 하지 않았다.

## 파일 식별값

| 파일 | 크기 | SHA-256 |
| --- | ---: | --- |
| PPTX | 21,192,876 bytes | `daf8a6d6f32268d055c012d0a0a0c144f0413f240d2b11a72cb4457cdbfdf9d0` |
| PDF | 4,267,230 bytes | `f76360b8891fa9c2ac3a671481a933f615a3f5564aa1fe8aa0c8ba963ae8635d` |

## 같은 파일 다시 조립하기

프로젝트 루트에서 다음 순서로 실행한다. 첫 명령은 배경과 노트로 PPTX를 새로 만들고, 다음 명령은 원본 화면을 삽입한다. 원본 삽입 코드는 이미 화면을 삽입한 PPTX에 중복 실행되지 않도록 검사한다.

```bash
/Users/shsmac/.codex-ppt-skill/.venv/bin/python /Users/shsmac/.codex/skills/codex-ppt/scripts/assemble_ppt.py /Users/shsmac/encore_proj/Team4_Proj_0831/docs ai_mafia_15min.pptx --aspect-ratio 16:9
/Users/shsmac/.codex-ppt-skill/.venv/bin/python docs/ai_mafia_15min/insert_original_screens.py
soffice --headless -env:UserInstallation=file:///private/tmp/ai-mafia-lo-profile --convert-to pdf --outdir docs/ai_mafia_15min docs/ai_mafia_15min/ai_mafia_15min.pptx
```

재조립하면 내부 파일의 기록 시각과 해시가 달라질 수 있다. 배경·원본 캡처·대본의 내용으로 일치 여부를 확인한다.
