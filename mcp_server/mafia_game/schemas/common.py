"""내부 Engine JSON 계약이 공유하는 폐쇄형 원시 검증 도구다."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from uuid import UUID

GAME_PHASES = frozenset(
    {
        "ROLE_REVEAL",
        "DAY_DISCUSSION",
        "NIGHT_ACTION",
        "DAY_VOTE",
        "REVOTE",
        "FINAL_DISCUSSION",
        "FINAL_ACCUSATION",
        "ENDED",
    }
)
RESOURCE_SCOPE_ORDER = ("public", "me", "turn", "persona", "gm-guide")
_UTC_RFC3339 = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})T(?P<time>\d{2}:\d{2}:\d{2})"
    r"(?P<fraction>\.\d+)?(?:Z|\+00:00)$"
)


class WireContractError(ValueError):
    """외부 원문을 보존하지 않고 wire 계약 위반임만 나타낸다."""


def strict_json_object(raw: bytes) -> dict[str, Any]:
    """UTF-8 JSON object의 duplicate·비표준 상수·decoder 한계 오류를 단일화한다."""

    if not isinstance(raw, bytes):
        raise WireContractError

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise WireContractError
            result[key] = value
        return result

    def reject_nonstandard_constant(_: str) -> None:
        # Python decoder의 확장인 NaN·Infinity는 정본 JSON number가 아니므로 값이나
        # 위치를 오류에 담지 않고 parsing 단계에서 즉시 거부한다.
        raise WireContractError

    try:
        decoded = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_nonstandard_constant,
        )
    except (ValueError, RecursionError) as error:
        # JSONDecodeError뿐 아니라 Python 정수 자릿수 상한의 bare ValueError까지 외부
        # 경계가 공유하는 안전한 계약 오류로 바꿔 원문이 ASGI·Engine 응답으로 새지 않는다.
        raise WireContractError from error
    if not isinstance(decoded, dict):
        raise WireContractError
    return decoded


def require_keys(value: Any, keys: set[str]) -> dict[str, Any]:
    """unknown field를 제거하지 않고 정확한 object key 집합만 허용한다."""

    if not isinstance(value, dict) or set(value) != keys:
        raise WireContractError
    return value


def canonical_uuid(value: Any) -> str:
    """UUID version을 재해석하지 않고 canonical hyphen 문자열만 허용한다."""

    if not isinstance(value, str):
        raise WireContractError
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as error:
        raise WireContractError from error
    if str(parsed) != value:
        raise WireContractError
    return value


def integer(value: Any, *, minimum: int | None = None, maximum: int | None = None) -> int:
    """JSON boolean이 정수 하위 타입으로 통과하지 못하게 분리해 검사한다."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise WireContractError
    if minimum is not None and value < minimum:
        raise WireContractError
    if maximum is not None and value > maximum:
        raise WireContractError
    return value


def string(value: Any, *, minimum: int = 1, maximum: int | None = None) -> str:
    """API의 문자 수 경계와 빈 문자열 거부를 그대로 적용한다."""

    if not isinstance(value, str) or len(value) < minimum:
        raise WireContractError
    if maximum is not None and len(value) > maximum:
        raise WireContractError
    # JSON escape는 단독 surrogate도 Python 문자열로 만들 수 있지만 해당 문자는
    # UTF-8로 직렬화할 수 없다. SDK 응답 단계의 예외가 되기 전에 계약 오류로 닫는다.
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise WireContractError
    return value


def normalized_text(value: Any, *, maximum: int) -> str:
    """문장형 필드가 앞뒤·연속 공백이나 개행의 다른 표현을 갖지 않게 한다."""

    checked = string(value, maximum=maximum)
    if " ".join(checked.split()) != checked:
        raise WireContractError
    return checked


def utc_rfc3339(value: Any) -> datetime:
    """UTC인 Z와 +00:00 표현만 받고 원본 문자열은 변경하지 않는다."""

    if not isinstance(value, str) or _UTC_RFC3339.fullmatch(value) is None:
        raise WireContractError
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise WireContractError from error


def utc_rfc3339_order_key(value: Any) -> tuple[datetime, str]:
    """초 단위 시각과 원본 소수초로 RFC3339 순서를 정밀도 손실 없이 비교한다.

    datetime은 미세초까지만 보존하므로 이를 그대로 비교하면 더 정밀한 마감을
    같은 시각으로 오판한다. 유효한 UTC 시각을 확인한 뒤 소수초의 후행 0만 제거하면
    숫자 변환이나 자릿수 상한 없이 문자열 순서가 실제 소수초 순서와 같아진다.
    """

    instant = utc_rfc3339(value)
    match = _UTC_RFC3339.fullmatch(value)
    if match is None:
        raise WireContractError
    fraction = (match.group("fraction") or "").removeprefix(".").rstrip("0")
    return instant.replace(microsecond=0), fraction
