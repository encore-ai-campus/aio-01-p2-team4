# 사용자 전용 커스텀 직업 MCP 툴 구현 요약

작성일: 2026-09-08 · 작업 단위: WU-M10

두 MCP 툴과 Backend 실행·권한 검증, 커스텀 직업 catalog 연결을 구현했다.
이 문서는 해당 작업 완료 시점의 요약이며, 상세 계약은 아래 정본을 따른다.

## 추가한 능력

| 능력 | MCP 툴 | 능력 ID | 동작 |
| --- | --- | --- | --- |
| 투표 조작 | `manipulate_vote` | `vote.triple.v1` | 능력자가 제출하는 처형 투표 한 장을 3표로 계산 |
| 특수 직업 열람 | `inspect_special_roles` | `intel.special_roles.v1` | 첫 밤 종료 후 다른 플레이어의 특수 직업을 본인만 조회 |

투표 조작은 일반 처형 투표(`DAY_VOTE`)와 재투표(`REVOTE`)에 적용한다.
예를 들어 능력자 A가 B에게 능력 투표를 제출하면 B의 득표수에 3표가 더해진다.
대상 선택과 투표 제출을 한 번에 처리하며, 창당 첫 유효 제출만 허용한다.
능력을 사용하지 않은 일반 제출·자동 투표·최종 지목은 1표이고 반복 강화는 없다.
사용한 능력 ID를 원장에 남겨 저장·재개와 replay에서도 같은 가중치를 복원한다.

특수 직업 열람은 첫 밤이 완전히 끝난 뒤(`day_number >= 2`) 해금된다.
마피아·시민·본인을 제외하며, 현재 표준 특수 직업인 탐정·의사를 사망자까지 포함해
조회한다. 생존한 능력 보유자만 진행 중인 본인 게임에서 사용할 수 있다.
조회는 밤 행동 횟수를 소모하지 않고 공개 이벤트·AI context·Redis cache에 기록하지 않는다.

## 커스텀 직업 연결과 구현 경계

- `CUSTOM_ROLE`의 인간 사용자 전용이다. 두 능력 모두 시민·마피아 진영에서 선택할 수 있다.
- `custom-role-v1` catalog에 기존 공격·조사·보호와 함께 등록했다. 능력 1~3개 제한과
  마피아 진영의 공격 필수 조건은 유지한다.
- 낮·조회 능력을 밤 행동에서 제외했다. 두 새 능력만 가진 시민 직업도 밤을 정상 진행한다.
- MCP는 Backend 내부 HTTP API에 위임하고, 소유권·능력·생존·phase·대상·마감·중복·
  멱등성 검증과 상태 저장은 Backend가 담당한다. 기존 `submit_action` 서명은 유지한다.
- 투표는 기존 공개 `SUBMIT_VOTE` command에 능력 ID를 전달한다. 직업 조회는 현재
  내부 `GET /internal/mcp/special-roles` 경계를 제공한다. Front는 MCP를 직접 호출하지 않는다.

핵심 구현 위치는 [MCP 툴 등록부](../../../mcp_server/mafia_game/api/tools/registry.py),
[Backend 내부 API](../../../backend/app/routers/mcp_registry_router.py),
[투표 규칙](../../../backend/app/game_engine/rules/vote_rules.py),
[직업 조회 서비스](../../../backend/app/services/game/game_read_service.py)다.

## 검증 결과

아래 수치는 구현 완료 시 실행한 검증 결과이며, 이번 요약 문서 작성 중 재실행하지 않았다.

| 범위 | 통과 | 기존 실패 | 선택 생략 |
| --- | ---: | ---: | ---: |
| Backend 비DB 회귀 | 1,140 | 6 | 17 |
| MCP 비DB 검증 | 167 | 0 | — |
| 사용자 Front 회귀 | 605 | 5 | — |
| 관리자 Front 회귀 | 19 | 0 | — |

신규 능력의 권한 거부, 첫 밤 경계, 비공개 응답, 실제 MCP→Backend HTTP 연결,
3표 집계, 재투표, 원장 복원, 중복·멱등·마감, 밤 능력 없는 직업 진행 검증은 통과했다.
MCP 수치는 최초 비DB 검증과 수정 후 adapter 집중 검증으로 확인한 고유 사례 수다.

기존 실패 11건은 Backend 계층 경계 검사 3건·MCP 공개 context 테스트 대역 누락 3건,
사용자 Front UUID 교체·결과 화면 버튼 5건이다. 이번 범위에서 수정하지 않았다.
실제 DB·DB subprocess·유료 API 통합·화면 수동 검증은 생략했다.

## 남은 적용 작업

1. 팀 DB의 적용 상태를 확인하고 `010_add_custom_role.sql` 다음에
   [011_add_custom_role_tool_abilities.sql](../../../backend/migrations/011_add_custom_role_tool_abilities.sql)을 적용한다.
   011은 기존 행을 보존하고 HUMAN의 능력 투표를 허용하는 CHECK를 확장한다.
2. Backend와 MCP를 재시작하고 팀 DB에서 실제 사용을 검증한다.
3. 새 능력 사용 버튼·직업 조회 결과 화면과 필요한 Front용 조회 API를 후속 연결한다.

구현 작업에서는 팀 DB 적용·프로세스 재시작·커밋·푸시를 수행하지 않았다.

### 후속 통합 반영 (2026-09-08)

위 목록은 WU-M10 완료 당시 기록이다. 이후 공개 `GET /api/v1/games/{game_id}/special-roles`
API와 Front 능력 투표·비공개 조회·종료 역할 표시를 연결했고, custom 능력 목록의
JSONB 저장을 보완했다. 사용자 승인으로 팀 DB에 010→011을 적용하고 같은 순서의
재실행, 기존 행 수·STANDARD/default·NULL 보존 및 새 열·CHECK를 검증했다.
현재 브라우저 통합과 커밋·푸시 상태는 [루트 README](../../../README.md)의 검증 기록을 따른다.

## 관련 정본

- [마스터플랜의 WU-M10 범위](../01_core/AI_MAFIA_MASTER_PLAN.md)
- [API 계약](../01_core/AI_MAFIA_API_SPEC.md)
- [MCP 서버 설계](../03_mcp_agent/AI_MAFIA_MCP_SERVER_DESIGN.md)
- [DB 저장 계약](../02_backend_data/AI_MAFIA_DB_DESIGN.md)
- [화면 연결 계획](../04_frontend/AI_MAFIA_SCREEN_FLOW.md)
- [실행·검증 안내](../../../README.md)
