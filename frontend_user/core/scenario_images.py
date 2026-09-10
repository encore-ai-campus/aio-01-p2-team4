"""시나리오 식별자와 사용자 화면용 맵 이미지의 연결을 관리한다."""

from __future__ import annotations

from pathlib import Path
from typing import Any

MAP_IMAGE_DIR = Path(__file__).resolve().parents[1] / "assets" / "maps"
RESULT_IMAGE_DIR = Path(__file__).resolve().parents[1] / "assets" / "results"
HOME_IMAGE_PATH = Path(__file__).resolve().parents[1] / "assets" / "main.png"

# Backend의 scenario-v1 식별자는 변경하지 않고, Front의 정적 이미지 자산만 연결한다.
SCENARIO_IMAGE_FILES = {
    "BLACKOUT_STUDIO": "5.png",
    "SNOWBOUND_LODGE": "2.png",
    "CLOSING_MUSEUM": "3.png",
    "LAST_BANQUET_GUEST": "4.png",
    "STOPPED_NIGHT_TRAIN": "1.png",
}

RESULT_IMAGE_FILES = {
    "CITIZEN": "end.jpg",
    "MAFIA": "end_mafia.png",
}


def scenario_image_path(scenario: Any) -> Path | None:
    """scenario id에 해당하는 존재하는 이미지 경로만 반환한다.

    홈 목록처럼 식별자가 축약되거나 제목만 전달되는 화면도 안전하게 처리하며,
    매핑되지 않은 시나리오는 기존 기본 배경을 사용할 수 있도록 None을 반환한다.
    """

    if not isinstance(scenario, dict):
        return None
    scenario_id = str(scenario.get("scenario_id", "")).upper()
    title = str(scenario.get("scenario_title", scenario.get("title", "")))
    title_map = {
        "정전된 방송국": "BLACKOUT_STUDIO",
        "눈 내리는 산장": "SNOWBOUND_LODGE",
        "폐관 직전의 박물관": "CLOSING_MUSEUM",
        "호텔 만찬의 마지막 손님": "LAST_BANQUET_GUEST",
        "멈춰 선 야간열차": "STOPPED_NIGHT_TRAIN",
        "멈춰 선 야간 열차": "STOPPED_NIGHT_TRAIN",
    }
    key = scenario_id if scenario_id in SCENARIO_IMAGE_FILES else title_map.get(title)
    filename = SCENARIO_IMAGE_FILES.get(key)
    path = MAP_IMAGE_DIR / filename if filename else None
    return path if path is not None and path.is_file() else None


def result_image_path(winner: Any) -> Path | None:
    """승리 진영에 맞는 결과 배너 자산을 반환하고, 잘못된 값은 노출하지 않는다."""

    winner_key = str(winner or "").upper()
    filename = RESULT_IMAGE_FILES.get(winner_key)
    path = RESULT_IMAGE_DIR / filename if filename else None
    return path if path is not None and path.is_file() else None


def home_image_path() -> Path | None:
    """홈 상단 소개 카드에 사용할 main 이미지를 반환한다."""

    return HOME_IMAGE_PATH if HOME_IMAGE_PATH.is_file() else None
