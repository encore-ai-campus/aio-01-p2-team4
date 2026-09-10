"""게임 replay와 규칙 판정에 사용하는 결정적 난수 도구."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Sequence
from typing import TypeVar

T = TypeVar("T")


def generate_seed() -> bytes:
    """새 게임용 256-bit seed를 만든다.

    실제 게임에서는 이 값을 암호화해 DB에 저장하고, 공개 응답에는 노출하지 않는다.
    테스트와 replay는 같은 seed를 다시 전달해 동일한 결정을 재현한다.
    """

    return secrets.token_bytes(32)


class DeterministicRng:
    """seed와 목적 문자열만으로 항상 같은 결과를 내는 난수 생성기.

    Python 기본 random의 전역 상태를 사용하지 않아 테스트 순서나 다른 요청이
    바뀌어도 결과가 흔들리지 않는다. 목적 문자열을 바꾸면 역할 배정과 투표
    자동 선택이 서로의 난수 소비 순서에 영향을 주지 않는다.
    """

    def __init__(self, seed: bytes | str) -> None:
        self.seed = seed.encode("utf-8") if isinstance(seed, str) else bytes(seed)
        if not self.seed:
            raise ValueError("seed must not be empty")

    def _digest(self, purpose: str, index: int = 0) -> bytes:
        return hashlib.sha256(
            self.seed + b"\x00" + purpose.encode("utf-8") + b"\x00" + index.to_bytes(8, "big")
        ).digest()

    def index(self, purpose: str, size: int, index: int = 0) -> int:
        """목록에서 사용할 결정적 인덱스를 반환한다."""

        if size <= 0:
            raise ValueError("size must be positive")
        return int.from_bytes(self._digest(purpose, index)[:8], "big") % size

    def choice(self, values: Sequence[T], purpose: str) -> T:
        """빈 목록이 아니면 같은 목적에 대해 같은 항목을 선택한다."""

        if not values:
            raise ValueError("cannot choose from an empty sequence")
        return values[self.index(purpose, len(values))]

    def shuffle(self, values: Sequence[T], purpose: str) -> list[T]:
        """원본을 수정하지 않고 결정적으로 섞은 새 목록을 반환한다."""

        result = list(values)
        for current in range(len(result) - 1, 0, -1):
            swap = self.index(purpose, current + 1, index=len(result) - current)
            result[current], result[swap] = result[swap], result[current]
        return result

    def proof_hash(self, purpose: str, value: object) -> str:
        """결정 결과를 검증할 수 있는 공개용 hash를 만든다."""

        raw = f"{purpose}:{value}".encode("utf-8")
        return hashlib.sha256(self.seed + b"\x00" + raw).hexdigest()
