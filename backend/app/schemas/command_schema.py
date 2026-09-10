"""공개 게임 command 요청의 폐쇄형 입력 타입."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

CommandType = Literal[
    "BEGIN_GAME",
    "SPEAK",
    "PASS",
    "SUBMIT_NIGHT_ACTION",
    "SUBMIT_VOTE",
    "SAVE_AND_EXIT",
    "RESUME",
    "FAST_FORWARD",
]


class GameCommandRequest(BaseModel):
    """모든 게임 변경을 하나의 endpoint에서 받는 요청이다.

    command 종류별 필수 field는 schema가 아닌 service에서 phase와 함께
    확인한다. 같은 필드가 다른 command에서 재사용될 수 있고, 이 검증을
    service에 두어 HTTP·내부 Agent 경로가 동일한 규칙을 사용하게 한다.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: CommandType
    expected_state_version: int = Field(ge=1)
    window_id: UUID | None = None
    target_player_id: UUID | None = None
    message: str | None = None
    ability_id: Literal[
        "night.attack.v1", "night.investigate.v1", "night.protect.v1", "vote.triple.v1",
    ] | None = None

    @model_validator(mode="after")
    def validate_ability_command(self) -> "GameCommandRequest":
        """사용 의사를 보낸 능력이 무관한 command에서 조용히 무시되지 않게 한다."""

        if self.ability_id is not None:
            expected = "SUBMIT_VOTE" if self.ability_id == "vote.triple.v1" else "SUBMIT_NIGHT_ACTION"
            if self.type != expected:
                raise ValueError("능력 ID와 command 종류가 일치하지 않습니다.")
        return self

    def receipt_body(self) -> dict[str, object]:
        """기존 command의 멱등 hash에는 새 nullable 필드를 추가하지 않는다."""

        body = self.model_dump(mode="json")
        if self.ability_id is None:
            body.pop("ability_id")
        return body


class CommandAcceptedData(BaseModel):
    """command 성공 시 snapshot 대신 반환하는 최소 결과다."""

    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    command_type: CommandType
    accepted_state_version: int
    result_state_version: int
    sync_url: str
