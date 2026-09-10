"""AI·GM audience별 context projection을 만드는 모듈.

같은 게임 상태라도 주체에 따라 볼 수 있는 정보가 다르다. 이 파일은 공개 정보와
개인 정보를 한 함수에서 섞지 않도록 분리하고, MCP가 DB에 직접 접근하지 않아도
받은 context만 전달할 수 있는 평범한 dict를 반환한다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping, Sequence
from types import SimpleNamespace
from uuid import UUID

from backend.app.models.enums import GamePhase, GameStatus, PlayerRole
from backend.app.models.game_state import GameState


SCOPE_PERMISSIONS = {
    "AI_PLAYER": frozenset({"public", "me", "turn", "persona"}),
    "GM": frozenset({"public", "gm-guide"}),
}
WINDOW_BY_PHASE = {
    GamePhase.DAY_DISCUSSION: "SPEECH",
    GamePhase.FINAL_DISCUSSION: "SPEECH",
    GamePhase.NIGHT_ACTION: "NIGHT",
    GamePhase.DAY_VOTE: "VOTE",
    GamePhase.REVOTE: "REVOTE",
    GamePhase.FINAL_ACCUSATION: "FINAL_VOTE",
}
TOOL_BY_WINDOW = {
    "SPEECH": ["propose_speech", "propose_pass"],
    "NIGHT": ["propose_night_action"],
    "VOTE": ["propose_vote"],
    "REVOTE": ["propose_vote"],
    "FINAL_VOTE": ["propose_vote"],
}


def build_context(
    state: GameState,
    *,
    subject_type: str,
    subject_id: UUID,
    scope: str,
    window_id: UUID | None = None,
    deadline_at: datetime | None = None,
    scenario: Mapping[str, Any] | None = None,
    public_events: Sequence[Mapping[str, Any]] = (),
    private_events: Sequence[Mapping[str, Any]] = (),
    facts: Mapping[str, str] | None = None,
    persona: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    window: Mapping[str, Any] | None = None,
    eliminated: Mapping[UUID, tuple[str, int]] | None = None,
    last_sequence: int = 0,
    valid_target_ids: Sequence[UUID] | None = None,
) -> dict[str, Any]:
    """정본의 context envelope와 scope별 허용 data를 만든다."""

    if subject_type not in SCOPE_PERMISSIONS or scope not in SCOPE_PERMISSIONS[subject_type]:
        raise PermissionError("CAPABILITY_DENIED")
    expected_subject = state.game_id if subject_type == "GM" else subject_id
    if subject_type == "GM" and subject_id != state.game_id:
        raise PermissionError("CAPABILITY_DENIED")
    if subject_type == "AI_PLAYER":
        player = state.player_by_id.get(subject_id)
        if player is None or player.kind.value != "AI":
            raise PermissionError("CAPABILITY_DENIED")

    if deadline_at is not None and (window is None or deadline_at != window.get("deadline_at")):
        raise PermissionError("CAPABILITY_DENIED")
    if window_id is None:
        raise PermissionError("CAPABILITY_DENIED")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    envelope = {
        "context_version": 1,
        "game_id": str(state.game_id),
        "subject_type": subject_type,
        "subject_id": str(expected_subject),
        "phase": state.phase.value,
        "state_version": state.state_version,
        "window_id": str(window_id),
        "scope": scope,
        "data": {},
    }
    if scope == "public":
        envelope["data"] = _public_data(state, scenario, public_events, eliminated or {}, last_sequence)
    elif scope == "me":
        envelope["data"] = _me_data(state, subject_id, facts, private_events)
    elif scope == "turn":
        envelope["data"] = _turn_data(state, subject_id, envelope["window_id"], current, window, valid_target_ids)
    elif scope == "persona":
        envelope["data"] = _persona_data(persona)
    else:
        envelope["data"] = _gm_guide_data(state, public_events)
    return envelope


def _public_data(
    state: GameState,
    scenario: Mapping[str, Any] | None,
    public_events: Sequence[Mapping[str, Any]],
    eliminated: Mapping[UUID, tuple[str, int]],
    last_sequence: int,
) -> dict[str, Any]:
    """모든 subject가 같은 상태에서 동일하게 받는 공개 projection."""

    if not scenario:
        raise PermissionError("CAPABILITY_DENIED")
    scenario_data = {
        name: _text(scenario.get(name), maximum)
        for name, maximum in {"scenario_id": 64, "title": 120, "background": None, "victim": 120}.items()
    }
    locations = scenario.get("locations")
    if not isinstance(locations, list) or not 4 <= len(locations) <= 5:
        raise PermissionError("CAPABILITY_DENIED")
    scenario_data["locations"] = [_text(location, 80) for location in locations]
    if len(set(scenario_data["locations"])) != len(locations):
        raise PermissionError("CAPABILITY_DENIED")
    return {
        "game": {
            "game_id": str(state.game_id),
            "status": state.status.value,
            "phase": state.phase.value,
            "round": state.round,
            "day_number": state.day_number,
            "state_version": state.state_version,
            "last_sequence": last_sequence,
            "ruleset_version": "mystery-v1",
            "scenario_version": "scenario-v1",
            "player_count": len(state.players),
            # 인원별 공개 규칙으로 계산해 비공개 role 변경에 영향을 받지 않는다.
            "mafia_count": 1 if len(state.players) <= 7 else 2,
            "fast_forward_enabled": state.fast_forward_enabled,
            "updated_at": state.updated_at.astimezone(timezone.utc).isoformat(),
        },
        "scenario": scenario_data,
        "players": [
            {
                "player_id": str(player.player_id),
                "seat": player.seat,
                "display_name": _text(player.display_name, 40),
                "kind": player.kind.value,
                "alive": player.alive,
                "revealed_role": player.role.value if state.status is GameStatus.COMPLETED or (
                    not player.alive and eliminated.get(player.player_id, (None,))[0]
                    in {"DAY_VOTE", "REVOTE", "FINAL_ACCUSATION"}
                ) else None,
                "eliminated_phase": eliminated.get(player.player_id, (None, None))[0],
                "eliminated_round": eliminated.get(player.player_id, (None, None))[1],
            }
            for player in sorted(state.players, key=lambda item: item.seat)
        ],
        # caller가 이미 PUBLIC으로 분류한 event만 복사한다. private payload를 이
        # projection 함수가 새로 만들지 않는 것이 audience 혼입을 막는 핵심이다.
        "public_events": _closed_events(state, public_events),
    }


def _me_data(
    state: GameState,
    subject_id: UUID,
    facts: Mapping[str, str] | None,
    private_events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """AI 자기 자신의 role·fact·private event만 반환한다."""

    player = state.player_by_id[subject_id]
    if not facts:
        raise PermissionError("CAPABILITY_DENIED")
    given = facts
    return {
        "player_id": str(subject_id),
        "role": player.role.value,
        "alive": player.alive,
        "alibi": _text(given.get("alibi"), 240),
        "observation": _text(given.get("observation"), 240),
        "private_events": _closed_events(state, private_events, player_id=subject_id),
    }


def _turn_data(
    state: GameState,
    subject_id: UUID,
    window_id: str,
    now: datetime,
    window: Mapping[str, Any] | None,
    valid_target_ids: Sequence[UUID] | None,
) -> dict[str, Any]:
    """서비스가 확정한 후보만 투영하며 만료·중복·다른 차례를 거부한다.

    Agent projection은 규칙 엔진을 호출하거나 후보를 추정하지 않는다. 전달된
    ID를 같은 상태의 공개 참가자로만 변환하고 누락·다른 게임·사망자는 거부한다.
    """

    player = state.player_by_id[subject_id]
    kind = WINDOW_BY_PHASE.get(state.phase)
    if not window or not player.alive or state.status is not GameStatus.IN_PROGRESS:
        raise PermissionError("CAPABILITY_DENIED")
    if kind is None or window.get("window_kind") != kind or str(window.get("id")) != window_id:
        raise PermissionError("CAPABILITY_DENIED")
    if valid_target_ids is None or any(not isinstance(identifier, UUID) for identifier in valid_target_ids):
        raise PermissionError("CAPABILITY_DENIED")
    identifiers = set(valid_target_ids)
    targets = [candidate for candidate in state.alive_players if candidate.player_id in identifiers]
    if len(identifiers) != len(valid_target_ids) or len(targets) != len(identifiers):
        raise PermissionError("CAPABILITY_DENIED")
    if subject_id in identifiers and not (kind == "NIGHT" and player.role is PlayerRole.DOCTOR):
        raise PermissionError("CAPABILITY_DENIED")
    if kind == "SPEECH":
        if targets or str(window.get("turn_player_id")) != str(subject_id) or (window.get("deadline_at") is None and subject_id in state.speech_actors):
            raise PermissionError("CAPABILITY_DENIED")
    elif kind == "NIGHT":
        if player.role not in {PlayerRole.MAFIA, PlayerRole.DETECTIVE, PlayerRole.DOCTOR} or subject_id in state.night_actions:
            raise PermissionError("CAPABILITY_DENIED")
    else:
        if subject_id in state.votes:
            raise PermissionError("CAPABILITY_DENIED")
    deadline = window.get("deadline_at")
    if kind == "SPEECH" and deadline is not None and (not isinstance(deadline, datetime) or deadline.utcoffset() is None or deadline <= now):
        raise PermissionError("CAPABILITY_DENIED")
    if kind != "SPEECH" and (
        not isinstance(deadline, datetime) or deadline.utcoffset() is None
        or deadline <= now or not targets
    ):
        raise PermissionError("CAPABILITY_DENIED")
    return {
        "window_id": window_id,
        "window_kind": kind,
        "cycle": window["cycle"],
        "opened_state_version": window["opened_state_version"],
        "server_time": now.astimezone(timezone.utc).isoformat(),
        "deadline_at": deadline.astimezone(timezone.utc).isoformat() if deadline is not None else None,
        "turn_player_id": str(subject_id) if kind == "SPEECH" else None,
        "allowed_tools": (["propose_speech"] if state.phase is GamePhase.DAY_DISCUSSION
                          and state.day_number == 1 else list(TOOL_BY_WINDOW[kind])),
        "valid_targets": [
            {"player_id": str(candidate.player_id), "display_name": _text(candidate.display_name, 40)}
            for candidate in targets
        ],
    }


def _persona_data(persona: Mapping[str, Any] | None) -> dict[str, Any]:
    """persona의 정본 field만 허용한다."""

    if not persona:
        raise PermissionError("CAPABILITY_DENIED")
    limits = {"persona_id": 64, "version": 32, "display_name": 40, "speech_style": 240, "backstory": 500}
    result = {name: _text(persona.get(name), maximum) for name, maximum in limits.items()}
    keys = {"sociability", "assertiveness", "suspicion", "deception", "risk_tolerance",
            "memory_recall", "reasoning_skill", "emotionality", "cooperativeness", "verbosity"}
    parameters = persona.get("parameters")
    if not isinstance(parameters, Mapping) or set(parameters) != keys or any(
        type(value) not in {int, float} or not isfinite(value) or not 0 <= value <= 1
        for value in parameters.values()
    ):
        raise PermissionError("CAPABILITY_DENIED")
    result["parameters"] = dict(parameters)
    return result


def _text(value: Any, maximum: int | None) -> str:
    """저장 문자열의 공백을 정규화하고 누락·잘못된 타입을 대체 문구 없이 거부한다."""

    if not isinstance(value, str):
        raise PermissionError("CAPABILITY_DENIED")
    value = " ".join(value.split())
    if not value or (maximum is not None and len(value) > maximum):
        raise PermissionError("CAPABILITY_DENIED")
    return value


def _gm_guide_data(state: GameState, public_events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """GM에게 공개 진행 지침만 제공한다. role·행동·조사 결과는 제외한다."""

    events = _closed_events(state, public_events)
    source = events[-1] if events else None
    return {
        "narration_kind": "PUBLIC_EVENT" if source else "FIXED_MESSAGE",
        "source_public_event": source,
        "fixed_message_key": None if source else "GAME_INTRO",
    }



def _closed_events(state: GameState, events: Sequence[Mapping[str, Any]], *, player_id: UUID | None = None) -> list[dict[str, Any]]:
    """조회 계층에서 audience를 거른 event도 마지막 직렬화에서 필드·중복을 제한한다.

    원장 수신자 검증은 read service가 담당한다. 여기서는 중첩 data의 추가 비공개
    필드와 중복 ID가 재사용된 dict를 통해 envelope 안에 들어오는 것을 막는다.
    """

    from backend.app.services.game.game_read_service import _public_event_data
    from backend.app.services.game.actor_context import private_event_data

    result, seen = [], set()
    for event in events:
        try:
            identifier = str(UUID(str(event["event_id"])))
            if identifier in seen:
                continue
            created = datetime.fromisoformat(event["created_at"].replace("Z", "+00:00"))
            if created.utcoffset() is None:
                continue
            event_type = event["event_type"]
            data = (_public_event_data(event_type, event["data"], SimpleNamespace(state=state))
                    if player_id is None else private_event_data(state, event_type, event["data"], player_id=player_id))
            seen.add(identifier)
            result.append({"event_id": identifier, "event_type": event_type,
                           "created_at": created.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), "data": data})
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return result
