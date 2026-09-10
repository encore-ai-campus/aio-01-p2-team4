"""공개 게임 API의 요청 검증과 응답용 타입."""

from typing import Literal
from uuid import UUID

import unicodedata

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CUSTOM_ROLE_CATALOG_VERSION = "custom-role-v1"
CUSTOM_ROLE_ABILITIES = {
    "night.attack.v1": {"label": "공격", "factions": ["MAFIA"]},
    "night.investigate.v1": {"label": "조사", "factions": ["CITIZEN", "MAFIA"]},
    "night.protect.v1": {"label": "보호", "factions": ["CITIZEN", "MAFIA"]},
    "vote.triple.v1": {"label": "투표 조작", "factions": ["CITIZEN", "MAFIA"]},
    "intel.special_roles.v1": {"label": "특수 직업 열람", "factions": ["CITIZEN", "MAFIA"]},
}


class CustomRoleRequest(BaseModel):
    """자유 직업 입력을 표시 문자열과 versioned 능력 ID로만 제한한다."""

    model_config = ConfigDict(extra="forbid")

    name: str
    faction: Literal["CITIZEN", "MAFIA"]
    catalog_version: Literal["custom-role-v1"]
    ability_ids: list[Literal[
        "night.attack.v1", "night.investigate.v1", "night.protect.v1",
        "vote.triple.v1", "intel.special_roles.v1",
    ]] = Field(min_length=1, max_length=3)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        """제어문자를 거부하고 NFC·Unicode 공백 축약을 적용한다."""

        if any(unicodedata.category(character).startswith("C") for character in value):
            raise ValueError("직업명에는 제어문자를 사용할 수 없습니다.")
        normalized = " ".join(unicodedata.normalize("NFC", value).split())
        if not 1 <= len(normalized) <= 40:
            raise ValueError("직업명은 정규화 후 1~40자여야 합니다.")
        return normalized

    @model_validator(mode="after")
    def validate_abilities(self) -> "CustomRoleRequest":
        """중복과 진영별 능력 조합을 폐쇄형 catalog로 검증한다."""

        if len(set(self.ability_ids)) != len(self.ability_ids):
            raise ValueError("능력 ID는 중복될 수 없습니다.")
        abilities = set(self.ability_ids)
        if self.faction == "CITIZEN" and "night.attack.v1" in abilities:
            raise ValueError("시민 진영은 공격 능력을 선택할 수 없습니다.")
        if self.faction == "MAFIA" and "night.attack.v1" not in abilities:
            raise ValueError("마피아 진영은 공격 능력이 필요합니다.")
        return self


class CreateGameRequest(BaseModel):
    """정본에 정의된 게임 생성 요청이다."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    player_count: int = Field(ge=6, le=9)
    ruleset_version: Literal["mystery-v1"]
    scenario_version: Literal["scenario-v1"]
    mode: Literal["STANDARD", "CUSTOM_ROLE"] = "STANDARD"
    custom_role: CustomRoleRequest | None = None

    @model_validator(mode="after")
    def validate_mode(self) -> "CreateGameRequest":
        """STANDARD와 CUSTOM_ROLE payload가 서로 섞이지 않게 거부한다."""

        if (self.mode == "CUSTOM_ROLE") != (self.custom_role is not None):
            raise ValueError("mode와 custom_role 조합이 올바르지 않습니다.")
        return self


class GameListQuery(BaseModel):
    """게임 목록 조회 조건을 서비스에 전달하기 전 검증한다."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["IN_PROGRESS", "SAVED", "COMPLETED", "FAILED"] | None = None
    cursor: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


class CreateGameData(BaseModel):
    """게임 생성 성공 data다."""

    model_config = ConfigDict(extra="forbid")

    game_id: UUID
    status: Literal["IN_PROGRESS"]
    phase: Literal["ROLE_REVEAL"]
    round: int
    state_version: int
    snapshot_url: str
