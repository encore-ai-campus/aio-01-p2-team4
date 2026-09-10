# README 도식 검증 기록

2026-09-08 · 문서 전용 변경. 애플리케이션 코드·DB·실행 중인 게임 서비스는 변경하지 않았습니다.

## 시스템 관계도

- `diagram_type`: `architecture`
- 원본: [system-map.architecture.json](system-map.architecture.json)
- 생성 HTML: [system-map.html](system-map.html)
- README 이미지: [system-map.svg](system-map.svg), 뷰어의 SVG 내보내기 결과
- 생성기: Archify 2.16 · `showcase`
- `validation`: **9/9**, composition 오류 0 · 경고 0
- `visual_review`: **passed** — 실제 light/dark 캡처 4장 및 Orca 브라우저의 SVG 확인
- `correction_rounds`: **0** — 최종 HTML의 시각 검토 후 추가 수정 없음

| 대상 | 바이트 | SHA-256 |
| --- | ---: | --- |
| specification | 2,620 | `591b58f97aa68d21b313d675691764cff7c84dbfb9179ab755ce33b08cc7a112` |
| HTML artifact | 711,171 | `b45f3d9ea92f34e12bccf593db5507780cafcef4c0403cf316cfa582f9a6e10c` |
| SVG export | 54,301 | `8c8c146b271347723e326daa578a73d56a3b9e0f25b1d013c79db4f07edac3e3` |

`deliver`의 원본·HTML 식별값을 별도 SHA-256 계산과 대조했습니다. SVG 내보내기는
HTML의 바이트를 변경하지 않습니다. SVG는 dark theme·정적 상태이며 외부 글꼴·이미지
다운로드나 script 없이 표시됩니다. 뷰어의 고정 UI와 HTML 언어 표시는 영어입니다.

자동 측정은 1440×900, 1600×1000, 1920×1080, 2048×1320에서 문서 전체의 가로·세로
넘침이 없음을 확인했습니다. 최소·최대 크기의 두 테마 캡처에서 노드·라벨·화살표·하단
카드의 겹침과 잘림을 직접 확인했습니다.

- [자동 측정 영수증](system-map.visual-check.json)
- [light/dark 캡처 모음](system-map.visual-check.html)

자동 영수증의 `visualReview: "pending"`은 도구가 사람의 시각 판단을 자동 판정하지
않는다는 뜻입니다. 이 문서의 `visual_review`는 별도로 수행한 캡처 검토 결과입니다.

## 에이전트 의사결정 흐름

[README](../../README.md#agents)에 6단계 Mermaid 흐름도로 작성했습니다. 별도로 시도한
Archify workflow v2는 `composition/desktop-readability`와 `layout/constraint`
진단이 남았습니다. 두 연속 보정에서 최저 오류 수가 개선되지 않아 스킬의 제한에 따라
해당 후보 수정을 중단·제거했습니다. 실패한 후보의 HTML은 생성하거나 배포하지 않았으며,
README의 Mermaid에 Archify 9/9 검증 결과를 적용하지 않습니다.

README는 Orca 내장 브라우저의 로컬 Markdown 미리보기에서 확인했습니다. Mermaid
파싱·렌더링 후 노드 6개와 연결 5개, 이미지 2개의 로딩, 접이식 섹션 15개의 본문과
실행 안내 펼치기를 확인했습니다. 긴 노드 문구의 불필요한 줄바꿈을 줄인 뒤 다시
렌더링했습니다. README·이 문서의 로컬 링크와 앵커 66건은 누락이 없었으며,
`git diff --check`도 통과했습니다. GitHub 원격 페이지에서 확인한 결과는 아닙니다.

## 코드 근거와 작업 범위

Orca orchestration으로 두 작업자를 같은 체크아웃에서 읽기 전용으로 실행했습니다.
한 작업자는 AI별 컨텍스트·Provider 요청·행동 적용을, 다른 작업자는 MCP 등록부·시스템
호출 경계를 조사했습니다. 결과를 합쳐 다음 실제 코드와 정본을 대조했습니다.

- [actor별 실행과 제출 경로](../../backend/app/services/game/postgres_runtime.py)
- [새 컨텍스트·메시지·제안 검증](../../backend/app/agent/orchestrator.py)
- [Backend의 private 정보 투영](../../backend/app/services/game/actor_context.py)
- [MCP Resource와 모델 입력 축약](../../mcp_server/mafia_game/api/resources/registry.py)
- [MCP Tool 등록](../../mcp_server/mafia_game/api/tools/registry.py)
- [공개·내부·MCP API 정본](../개발상세플랜/01_core/AI_MAFIA_API_SPEC.md)

문서 변경이므로 전체 회귀·유료 모델 호출·실게임·팀 DB 검증은 생략했습니다.
기존 README의 기능 테스트 결과는 과거 기록으로 보존하며 새 실행 결과로 표기하지 않습니다.

## 재생성

Archify skill 디렉터리의 `bin/archify.mjs`를 사용합니다. 원본을 수정하면 검증·생성·
시각 검토·SVG 내보내기 및 위 바이트 식별값을 함께 갱신해야 합니다.

```bash
node /path/to/archify/bin/archify.mjs validate architecture docs/diagrams/system-map.architecture.json --quality showcase --json
node /path/to/archify/bin/archify.mjs deliver architecture docs/diagrams/system-map.architecture.json docs/diagrams/system-map.html --quality showcase --json
node /path/to/archify/bin/archify.mjs visual-check docs/diagrams/system-map.html --json
```
