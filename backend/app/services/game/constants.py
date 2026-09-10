"""게임 생성과 공개 이벤트가 공유하는 고정 콘텐츠 상수."""

from typing import Any


INTRO_MESSAGE = (
    "사건이 발생한 뒤, 현장에 있던 사람들은 범인을 찾기 위해 서로를 추궁하기 시작했습니다. "
    "그러나 범인은 자신의 정체가 드러나는 것을 막기 위해 밤마다 다른 플레이어를 제거하려 합니다."
)

SCENARIOS: tuple[dict[str, Any], ...] = (
    {
        "scenario_id": "BLACKOUT_STUDIO",
        "title": "정전된 방송국",
        "background": "생방송 준비 중 정전된 방송국에서 PD가 사망했다.",
        "victim": "생방송 PD",
        "locations": ["스튜디오", "조정실", "분장실", "대기실", "장비실"],
    },
    {
        "scenario_id": "SNOWBOUND_LODGE",
        "title": "눈 내리는 산장",
        "background": "폭설로 고립된 산장에서 관리인이 약병 사건으로 사망했다.",
        "victim": "산장 관리인",
        "locations": ["거실", "주방", "복도", "관리인 방", "창고"],
    },
    {
        "scenario_id": "CLOSING_MUSEUM",
        "title": "폐관 직전의 박물관",
        "background": "폐관 직전 박물관에서 전시 담당자가 사망했다.",
        "victim": "전시 담당자",
        "locations": ["중앙 전시장", "보안실", "안내 데스크", "복원실", "직원 휴게실"],
    },
    {
        "scenario_id": "LAST_BANQUET_GUEST",
        "title": "호텔 만찬의 마지막 손님",
        "background": "비공개 호텔 만찬 도중 주최자가 사망했다.",
        "victim": "만찬 주최자",
        "locations": ["연회장", "주방", "로비", "복도", "VIP룸"],
    },
    {
        "scenario_id": "STOPPED_NIGHT_TRAIN",
        "title": "멈춰 선 야간열차",
        "background": "열차가 터널에 멈춘 사이 승무원이 사망했다.",
        "victim": "열차 승무원",
        "locations": ["승무원실", "객차", "식당칸", "연결 통로", "화물칸"],
    },
)
