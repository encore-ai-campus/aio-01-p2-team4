"""모델이 반환한 신뢰할 수 없는 JSON을 게임 proposal로 검증한다."""

import unicodedata
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.app.llm_provider.errors import LLMResponseError

PUBLIC_DECISION_BASES = {
    "PUBLIC_EVIDENCE": "공개된 사건 단서를 근거로 의견을 냈습니다.",
    "COMPARE_STATEMENTS": "공개 발언과 알리바이를 비교했습니다.",
    "ASK_FOR_CLARIFICATION": "불분명한 진술을 확인하기 위해 질문했습니다.",
    "INSUFFICIENT_EVIDENCE": "판단할 공개 근거가 아직 부족하다고 보았습니다.",
    "NO_NEW_INFORMATION": "이미 나온 의견 외에 추가할 내용이 없다고 보았습니다.",
}


class GameProposal(BaseModel):
    """Backend가 후속 phase·권한 검증을 수행할 최소 proposal이다."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    action: str = Field(min_length=1, max_length=32)
    target_player_id: UUID | None = None
    source_state_version: int = Field(ge=1)
    # 공개 발언은 게임 화면과 이벤트 payload에 그대로 들어가므로
    # 제품 정본의 200자 제한을 Provider schema 단계에서도 동일하게 전달한다.
    message: str | None = Field(default=None, max_length=200)


class NormalizedAgentProposal(BaseModel):
    """B6 Agent Manager가 사용하는 폐쇄형 proposal union이다.

    LLM이 자연어 설명이나 내부 추론을 덧붙이지 못하도록 허용 field를 고정한다.
    이 모델은 게임 규칙을 판정하지 않고 형식만 확인하며, role·phase·target의
    실제 허용 여부는 Engine이 다시 검사한다.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["SPEAK", "PASS", "NIGHT_ACTION", "VOTE"]
    target_player_id: UUID | None = None
    message: str | None = Field(default=None, max_length=2_000)
    public_rationale: str | None = Field(default=None, max_length=500)


def normalize_agent_proposal(payload: Any) -> NormalizedAgentProposal:
    """Provider의 JSON을 canonical proposal로 바꾸고 형식 오류를 거부한다.

    새 Provider는 ``type``을 반환한다. 기존 scaffold Provider가 사용하던 ``action``
    응답은 B1~B4 호환을 위해 여기서만 임시 변환한다. 변환 후에는 DB와 Engine에
    항상 canonical field만 전달되며, ``PING`` 같은 scaffold 전용 action은 거부된다.
    """

    if not isinstance(payload, dict):
        raise LLMResponseError("Agent proposal must be a JSON object")
    candidate = dict(payload)
    legacy_payload = "type" not in candidate and "action" in candidate
    if legacy_payload:
        candidate["type"] = candidate.pop("action")
    # 기존 응답의 version은 Agent proposal 최종 계약에 포함하지 않는다. 실제 상태
    # version은 reservation과 재검증 결과를 Backend가 보유한다.
    if legacy_payload:
        candidate.pop("source_state_version", None)
    try:
        proposal = NormalizedAgentProposal.model_validate(candidate)
    except ValidationError as error:
        raise LLMResponseError("Agent proposal does not match the canonical schema") from error
    if proposal.type == "SPEAK":
        if not proposal.message:
            raise LLMResponseError("SPEAK proposal requires message")
        message = " ".join(unicodedata.normalize("NFC", proposal.message).split())
        if not 1 <= len(message) <= 200 or any(ord(char) < 32 for char in message):
            raise LLMResponseError("SPEAK proposal message length is invalid")
        if proposal.target_player_id is not None:
            raise LLMResponseError("SPEAK proposal cannot contain a target")
        if message != proposal.message:
            proposal = proposal.model_copy(update={"message": message})
    elif proposal.type == "PASS":
        if (proposal.message is not None or proposal.target_player_id is not None
                or proposal.public_rationale not in {None, *PUBLIC_DECISION_BASES}):
            raise LLMResponseError("PASS proposal cannot contain message or target")
    elif proposal.type in {"NIGHT_ACTION", "VOTE"}:
        if proposal.target_player_id is None:
            raise LLMResponseError(f"{proposal.type} proposal requires target")
        if proposal.message is not None or proposal.public_rationale is not None:
            raise LLMResponseError(f"{proposal.type} proposal cannot contain message or rationale")
    return proposal


def agent_proposal_schema(*, job_kind: str | None = None) -> dict[str, Any]:
    """새 Agent adapter에 전달할 Provider 공통 JSON schema를 반환한다."""

    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "type": {"type": "string", "enum": {
                "SPEECH": ["SPEAK", "PASS"], "NIGHT_ACTION": ["NIGHT_ACTION"], "VOTE": ["VOTE"],
            }.get(job_kind, ["SPEAK", "PASS", "NIGHT_ACTION", "VOTE"])},
            "target_player_id": {"type": ["string", "null"], "format": "uuid"},
            "message": {"type": ["string", "null"], "maxLength": 200},
            "public_rationale": {"type": ["string", "null"], "maxLength": 500,
                                 "enum": [None] if job_kind in {"VOTE", "NIGHT_ACTION"}
                                 else [None, *PUBLIC_DECISION_BASES]},
        },
        "required": ["type", "target_player_id", "message", "public_rationale"],
    }


def parse_game_proposal(payload: Any, *, expected_state_version: int) -> GameProposal:
    """JSON object와 상태 버전을 검증해 안전한 proposal만 반환한다.

    Provider가 반환한 값은 외부 입력과 같으므로 필드 누락·추가 필드·잘못된
    UUID를 허용하지 않는다. 상태 버전 검사는 오래된 모델 응답이 MCP로
    전달되는 것을 막는 마지막 방어선이며, phase와 역할 검사는 Backend가
    proposal을 제출하기 직전에 별도로 수행한다.
    """

    if not isinstance(payload, dict):
        raise LLMResponseError("LLM response must be a JSON object")
    try:
        proposal = GameProposal.model_validate(payload)
    except ValidationError as error:
        raise LLMResponseError("LLM response does not match the proposal schema") from error
    if proposal.source_state_version != expected_state_version:
        raise LLMResponseError("LLM proposal uses a stale game state version")
    return proposal


def proposal_schema() -> dict[str, Any]:
    """OpenAI·Gemini에 전달할 Provider 독립 JSON schema를 반환한다."""

    # OpenAI structured output은 선택 필드도 required에 포함하고 nullable로
    # 표현해야 하므로, Pydantic 입력 모델과 Provider 출력 schema를 분리한다.
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {"type": "string", "minLength": 1, "maxLength": 32},
            "target_player_id": {"type": ["string", "null"], "format": "uuid"},
            "source_state_version": {"type": "integer", "minimum": 1},
            "message": {"type": ["string", "null"], "maxLength": 2_000},
        },
        "required": ["action", "target_player_id", "source_state_version", "message"],
    }
