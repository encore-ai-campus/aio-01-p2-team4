"""사용자 화면에 표시하는 서버 시각의 형식을 관리한다."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

_RFC3339_WITH_ZONE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?"
    r"(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)"
)


def display_timestamp(value: Any) -> str:
    """시간대가 포함된 RFC 3339 시각을 서울 시각의 초 단위로 표시한다.

    밀리초·시간대 이름·원본 문자열은 사용자에게 노출하지 않는다. 형식이 맞지
    않거나 존재하지 않는 날짜는 임의의 로컬 시간으로 보정하지 않고 안내 문구로
    대체하여, 서버 기록과 화면 표시가 서로 다른 시각을 가리키지 않게 한다.
    """

    if not isinstance(value, str) or _RFC3339_WITH_ZONE.fullmatch(value) is None:
        return "확인할 수 없음"
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return moment.astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OverflowError):
        return "확인할 수 없음"
