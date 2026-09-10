"""게임 엔진 규칙 계층의 공통 오류."""


class RuleViolation(ValueError):
    """사용자 명령이 현재 게임 규칙에 맞지 않을 때 발생한다."""

