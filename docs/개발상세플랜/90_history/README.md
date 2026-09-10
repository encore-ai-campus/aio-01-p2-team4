# 날짜별 변경 이력

이 디렉터리는 루트 [README.md](../../../README.md)에 누적돼 있던 날짜별 변경·검증
기록을 주제별로 옮겨 놓은 문서 모음입니다. 각 문서는 기록 시점의 작업 내용과
검증 결과를 보존하는 이력이며, 현재 상태의 설치·실행 안내는 루트 README를
기준으로 합니다.

| 문서 | 기록 범위 |
|---|---|
| [2026-09-08-persona-and-prompts.md](2026-09-08-persona-and-prompts.md) | WU-M6 역할별 프롬프트, WU-B6 페르소나 추론 수치(009), 첫날 발언 지침, system 메시지 축소, `dialogue_focus`, 실게임 검증 |
| [2026-09-08-speech-analysis.md](2026-09-08-speech-analysis.md) | WU-B11~B14·WU-M9 공개 발언 분석 구현, migration 006·008, Team DB 적용, 브라우저 실게임 점검 |
| [2026-09-08-game-lifecycle.md](2026-09-08-game-lifecycle.md) | 저장·재개·수동 삭제·뒤로가기, 병렬 투표 수정, 승패 원장 검토, WU-B15 stale 게임 자동 정리(007) |
| [2026-09-07-08-frontend-ui.md](2026-09-07-08-frontend-ui.md) | WU-F5 발언 대기열, 홈 목록·UUID 복구, 타임라인·채팅 UI, 색상 대비, UI·UX 플레이테스트 후속 |
| [2026-09-07-infra-merge-admin.md](2026-09-07-infra-merge-admin.md) | 섹터 병합, 가상환경 준비, 관리자 앱 연결, Redis 공개 이력 캐시, 터미널 로그 정리, 회귀 기록 |

## 미구현 후속 과제 메모

루트 README 말미에 남아 있던 후속 과제 메모를 옮깁니다. 구현이 확정되면 정본
문서와 루트 README를 먼저 갱신해야 합니다.

- 타 직업의 Tool을 호출할 수 있는 agent 생성 기능 (환경설정 페이지)과
  agent parameters 편집(0.1 초과·1.0 미만만 허용)
- 위 변경이 의미를 가지려면 게임 시작 전 커스텀 메뉴에서 플레이어 직업 선택이
  가능해야 함
