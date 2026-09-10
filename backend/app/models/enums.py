"""AI Mafia 게임에서 사용하는 고정된 값 모음.

DB의 CHECK 제약조건과 같은 값을 Python에서도 먼저 검사한다. 문자열을 곳곳에서
직접 만들지 않으면 오탈자로 잘못된 phase가 저장되는 일을 줄일 수 있다.
"""

from enum import StrEnum


class GamePhase(StrEnum):
    """DB에 저장할 수 있는 게임 phase이다.

    NIGHT_RESOLUTION은 여기에 넣지 않는다. 밤 결과를 계산하는 동안만 존재하는
    Backend 내부 처리 단계이므로, DB나 공개 응답의 phase로 노출하면 안 된다.
    """

    ROLE_REVEAL = "ROLE_REVEAL"
    DAY_DISCUSSION = "DAY_DISCUSSION"
    NIGHT_ACTION = "NIGHT_ACTION"
    DAY_VOTE = "DAY_VOTE"
    REVOTE = "REVOTE"
    FINAL_DISCUSSION = "FINAL_DISCUSSION"
    FINAL_ACCUSATION = "FINAL_ACCUSATION"
    ENDED = "ENDED"


class GameStatus(StrEnum):
    """games.status에 저장되는 게임 상태이다."""

    IN_PROGRESS = "IN_PROGRESS"
    SAVED = "SAVED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class PlayerRole(StrEnum):
    """플레이어의 역할이다."""

    MAFIA = "MAFIA"
    DETECTIVE = "DETECTIVE"
    DOCTOR = "DOCTOR"
    CITIZEN = "CITIZEN"


class Faction(StrEnum):
    """승패를 계산하는 진영이다."""

    MAFIA = "MAFIA"
    CITIZEN = "CITIZEN"


class PlayerKind(StrEnum):
    """사람 플레이어와 AI 플레이어를 구분한다."""

    HUMAN = "HUMAN"
    AI = "AI"


class NightActionType(StrEnum):
    """밤에 제출할 수 있는 역할별 행동이다."""

    ATTACK = "ATTACK"
    INVESTIGATE = "INVESTIGATE"
    PROTECT = "PROTECT"


class WinReason(StrEnum):
    """games.win_reason에 저장할 수 있는 종료 사유이다."""

    ALL_MAFIA_ELIMINATED = "ALL_MAFIA_ELIMINATED"
    MAFIA_PARITY = "MAFIA_PARITY"
    FINAL_MAFIA_SELECTED = "FINAL_MAFIA_SELECTED"
    FINAL_NON_MAFIA_SELECTED = "FINAL_NON_MAFIA_SELECTED"
