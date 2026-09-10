"""Backend HTTP 경계에서 사용하는 안전한 애플리케이션 오류 타입."""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    """내부 예외나 비밀값을 노출하지 않는 고정 API 오류를 표현한다.

    화면에는 이 객체의 공개 필드만 전달한다. 따라서 DB 오류 원문이나
    비밀번호 같은 민감한 정보가 실수로 API 응답에 섞이지 않는다.
    """

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: Any = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        # 일시적인 장애인지 여부다. 모르는 오류는 안전하게 재시도하지 않는다.
        self.retryable = retryable
