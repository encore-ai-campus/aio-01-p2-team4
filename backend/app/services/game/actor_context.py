"""인간·AI 게임 행동 주체를 표현하는 내부 공통 계약."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import Literal
from uuid import UUID

from backend.app.core.errors import ApiError
from backend.app.models.enums import GamePhase, PlayerRole
from backend.app.models.game_state import GameState

ActorKind = Literal["HUMAN", "AGENT"]


@dataclass(frozen=True, slots=True)
class ActorContext:
    """Engine command가 사용할 player와 저장 principal을 함께 고정한다.

    공개 API의 사용자 인증과 게임 안의 player identity는 서로 다른 값일 수
    있다. 특히 AI는 소유자 사용자를 대신하지만 행동 원장과 idempotency는 AI
    player 기준으로 남겨야 하므로 두 식별자를 분리해 보관한다.
    """

    kind: ActorKind
    owner_user_id: UUID
    player_id: UUID
    principal_id: UUID

    def __post_init__(self) -> None:
        """허용된 actor 종류와 빈 식별자를 생성 시점에 차단한다."""

        if self.kind not in {"HUMAN", "AGENT"}:
            raise ValueError("actor kind must be HUMAN or AGENT")
        for name, value in (
            ("owner_user_id", self.owner_user_id),
            ("player_id", self.player_id),
            ("principal_id", self.principal_id),
        ):
            if not isinstance(value, UUID):
                raise TypeError(f"{name} must be UUID")

    @classmethod
    def human(cls, *, owner_user_id: UUID, player_id: UUID) -> "ActorContext":
        """사용자 principal과 human player를 연결한다."""

        return cls(
            kind="HUMAN",
            owner_user_id=owner_user_id,
            player_id=player_id,
            principal_id=owner_user_id,
        )

    @classmethod
    def agent(cls, *, owner_user_id: UUID, player_id: UUID) -> "ActorContext":
        """소유자 게임 안의 AI player를 Agent principal로 연결한다."""

        return cls(
            kind="AGENT",
            owner_user_id=owner_user_id,
            player_id=player_id,
            principal_id=player_id,
        )

    @property
    def source(self) -> str:
        """action_submissions에 기록할 행동 출처를 반환한다."""

        return self.kind

    @property
    def principal_type(self) -> str:
        """idempotency·receipt에 사용할 principal 종류를 반환한다."""

        return "USER" if self.kind == "HUMAN" else "AGENT"


def validate_discussion_actor(
    *,
    state: object,
    window: Mapping[str, object] | None,
    actor: ActorContext,
    window_id: UUID | None,
) -> None:
    """human·AI 공통으로 현재 speech actor와 window를 검증한다.

    actor 종류별 인증은 호출 계층이 담당하고, 게임 안에서 실제로 발언할 수
    있는지에 대한 phase·window·순서 조건은 이 helper에서 동일하게 적용한다.
    """

    phase = getattr(state, "phase", None)
    if phase not in {GamePhase.DAY_DISCUSSION, GamePhase.FINAL_DISCUSSION}:
        raise ApiError(status_code=409, code="INVALID_PHASE", message="현재 발언 단계가 아닙니다.")
    if (
        window is None
        or window_id is None
        or UUID(str(window["id"])) != window_id
        or window.get("status") != "OPEN"
        or window.get("window_kind") != "SPEECH"
        or window.get("phase") != phase.value
        or (not (window.get("deadline_at") is not None and actor.kind == "HUMAN")
            and UUID(str(window.get("turn_player_id"))) != actor.player_id)
    ):
        raise ApiError(status_code=409, code="ACTION_NOT_ALLOWED", message="현재 발언 차례가 아닙니다.")


def read_actor_context(
    reader: object,
    *,
    owner_user_id: UUID,
    game_id: UUID,
    player_id: UUID | None,
    scope: str,
    agents: object,
) -> dict:
    """소유권·actor를 검증한 하나의 읽기 snapshot에서 내부 MCP context를 조립한다.

    인간 snapshot을 먼저 만든 뒤 필드를 덜어내면 개인 단서가 잘못 재사용되기 쉽다.
    같은 게임의 AI를 먼저 확정하고 요청 scope의 저장 자료만 읽는다. 복수 SELECT가
    다른 command의 전후 상태를 섞지 않도록 첫 조회 전에 읽기 전용 repeatable read를
    설정하며, 외부 호출이나 상태 변경은 이 transaction 안에서 실행하지 않는다.
    """

    from datetime import UTC, datetime
    from psycopg import IsolationLevel
    from psycopg.rows import dict_row

    from backend.app.agent.projections import build_context
    from backend.app.services.game.game_read_service import initial_record_from_rows, read_public_history
    from backend.app.services.game.postgres_helpers import restore_action_submissions, restore_revote_candidates

    allowed = {"public"} if player_id is None else {"public", "me", "turn", "persona"}
    if scope not in allowed:
        raise _context_denied()
    try:
        with reader._transactions.transaction() as connection:
            connection.isolation_level = IsolationLevel.REPEATABLE_READ
            connection.read_only = True
            with connection.cursor(row_factory=dict_row) as cursor:
                game = reader._games.get_owned_game(cursor, owner_user_id=owner_user_id, game_id=game_id)
                if game is None or UUID(str(game["id"])) != game_id or UUID(str(game["owner_user_id"])) != owner_user_id:
                    raise ApiError(status_code=404, code="GAME_NOT_FOUND", message="게임을 찾을 수 없습니다.")
                rows = reader._players.list_players(cursor, game_id=game_id)
                if (not 6 <= len(rows) <= 9
                    or len({UUID(str(row["id"])) for row in rows}) != len(rows)
                    or any(UUID(str(row["game_id"])) != game_id or type(row["seat"]) is not int
                           or not 1 <= row["seat"] <= 9 or type(row["alive"]) is not bool for row in rows)
                    or len({row["seat"] for row in rows}) != len(rows)):
                    raise _context_denied()
                actor = next((row for row in rows if UUID(str(row["id"])) == player_id), None)
                if player_id is not None and (actor is None or actor["kind"] != "AI"):
                    raise _context_denied()
                window = reader._actions.active_window(cursor, game_id=game_id)
                _validate_context_window(game, window, datetime.now(UTC))
                record = initial_record_from_rows(keyring=reader._keyring, game=game, player_rows=rows, window=window)
                facts, persona, public_events, private_events = None, None, [], []
                valid_target_ids = None
                through_sequence = int(game["next_event_sequence"]) - 1
                if scope == "public":
                    public_events = read_public_history(
                        reader, cursor, record, through_sequence=through_sequence,
                    )
                elif scope == "me":
                    fact_rows = reader._players.list_player_facts(cursor, game_id=game_id, player_id=player_id)
                    if len(fact_rows) != 2 or {row["fact_kind"] for row in fact_rows} != {"ALIBI", "OBSERVATION"}:
                        raise _context_denied()
                    facts = {row["fact_kind"].lower(): row["rendered_text"] for row in fact_rows}
                    event_rows = reader._events.list_snapshot_private_events(
                        cursor, game_id=game_id, player_id=player_id,
                        through_sequence=through_sequence, through_state_version=record.state.state_version,
                    )
                    private_events = scoped_private_events(record.state, event_rows, player_id, through_sequence)
                elif scope == "persona":
                    matches = [row for row in agents.list_active_personas(cursor, version=game["agent_config_version"])
                               if row["id"] == actor["persona_id"] and row["version"] == game["agent_config_version"]]
                    if len(matches) != 1:
                        raise _context_denied()
                    persona = {**matches[0], "persona_id": matches[0]["id"]}
                else:
                    submissions = reader._actions.list_window_action_submissions(cursor, window_id=UUID(str(window["id"])))
                    if record.state.phase is GamePhase.REVOTE:
                        resolutions = reader._actions.list_resolutions(cursor, game_id=game_id, through_state_version=record.state.state_version)
                        try:
                            restore_revote_candidates(record.state, resolutions)
                        except (RuntimeError, KeyError, ValueError, TypeError) as error:
                            raise _context_denied() from error
                    if window["window_kind"] == "SPEECH":
                        record.state.speech_actors = {
                            UUID(str(row["actor_player_id"])) for row in submissions
                            if row["action_type"] in {"SPEAK", "PASS"}
                        }
                    else:
                        restore_action_submissions(record.state, submissions)
                    valid_target_ids = _actor_target_ids(record.state, player_id)
                current_time = datetime.now(UTC)
                _validate_context_window(game, window, current_time)
                context = build_context(
                    record.state, subject_type="AI_PLAYER" if player_id else "GM",
                    subject_id=player_id or game_id, scope=scope,
                    window_id=UUID(str(window["id"])), window=window,
                    scenario=record.scenario, public_events=public_events, private_events=private_events,
                    facts=facts, persona=persona, eliminated=record.eliminated,
                    last_sequence=record.front_sequence, now=current_time, valid_target_ids=valid_target_ids,
                )
        if scope == "public":
            reader.cache_public_history(record, through_sequence=through_sequence, events=public_events)
        return context
    except ApiError:
        raise
    except PermissionError as error:
        raise _context_denied() from error
    except Exception as error:
        raise ApiError(status_code=503, code="DEPENDENCY_UNAVAILABLE", message="게임 context를 조회할 수 없습니다.", retryable=True) from error



def _actor_target_ids(state: GameState, player_id: UUID) -> tuple[UUID, ...]:
    """같은 읽기 상태에서 규칙 후보를 확정해 Agent에는 ID 목록만 전달한다.

    재투표 후보는 앞서 복원한 확정 원장을 엔진 규칙에 적용한다. 밤은 본인 역할과
    공개 생존 여부만 사용하므로 다른 AI의 역할·개인 자료가 후보를 바꾸지 않는다.
    """

    from backend.app.game_engine.rules.vote_rules import valid_targets

    actor = state.player_by_id[player_id]
    if state.phase in {GamePhase.DAY_VOTE, GamePhase.REVOTE, GamePhase.FINAL_ACCUSATION}:
        return tuple(candidate.player_id for candidate in valid_targets(state, actor))
    if state.phase is GamePhase.NIGHT_ACTION and actor.role in {PlayerRole.MAFIA, PlayerRole.DETECTIVE, PlayerRole.DOCTOR}:
        return tuple(candidate.player_id for candidate in state.alive_players
                     if candidate.player_id != player_id or actor.role is PlayerRole.DOCTOR)
    return ()


def _context_denied() -> ApiError:
    """개인 자료 누락과 권한 위반을 같은 고정 오류로 숨긴다."""

    return ApiError(status_code=403, code="CAPABILITY_DENIED", message="요청한 AI context를 조회할 수 없습니다.")


def _validate_context_window(game: Mapping, window: Mapping | None, now: object) -> None:
    """없는 window나 저장·해소·이전 phase의 상태를 임의 UUID로 대신하지 않는다."""

    from datetime import datetime
    from backend.app.agent.projections import WINDOW_BY_PHASE

    phase = GamePhase(game["phase"])
    valid = (
        game["status"] == "IN_PROGRESS" and window is not None
        and window.get("status") == "OPEN"
        and str(window.get("game_id")) == str(game["id"])
        and window.get("phase") == phase.value
        and window.get("window_kind") == WINDOW_BY_PHASE.get(phase)
        and type(window.get("round")) is int and window["round"] == game["round"]
        and type(window.get("cycle")) is int and (window["cycle"] == 1 or (window["cycle"] == 2 and game["day_number"] >= 2 and window.get("window_kind") == "SPEECH"))
        and type(window.get("opened_state_version")) is int
        and 1 <= window["opened_state_version"] <= game["state_version"]
    )
    if valid:
        if window["window_kind"] == "SPEECH":
            deadline = window.get("deadline_at")
            valid = window.get("turn_player_id") is not None and (deadline is None or (isinstance(deadline, datetime) and deadline.utcoffset() is not None and deadline > now))
        else:
            deadline = window.get("deadline_at")
            valid = isinstance(deadline, datetime) and deadline.utcoffset() is not None and deadline > now and window.get("turn_player_id") is None
    if not valid:
        raise ApiError(status_code=409, code="ACTION_NOT_ALLOWED", message="현재 조회할 수 있는 AI 행동 window가 없습니다.")


def scoped_private_events(state: object, rows: object, player_id: UUID, through_sequence: int) -> list[dict]:
    """해당 AI audience와 현재 snapshot 상한을 다시 확인하고 승인된 두 event만 투영한다.

    PUBLIC으로 잘못 저장된 행동, 다른 게임·다른 AI의 결과와 미승인 추가 필드는
    반환하지 않는다. 거부한 payload의 원문을 로그에 기록하지 않는다.
    """

    from datetime import UTC, datetime

    projected = []
    seen = set()
    for row in rows:
        try:
            if (UUID(str(row["game_id"])) != state.game_id or row["audience"] != "PLAYER"
                or UUID(str(row["audience_player_id"])) != player_id
                or type(row["schema_version"]) is not int or row["schema_version"] != 1
                or type(row["sequence"]) is not int or not 1 <= row["sequence"] <= through_sequence
                or type(row["state_version"]) is not int or not 1 <= row["state_version"] <= state.state_version):
                continue
            payload = row["payload"]
            data = private_event_data(state, row["event_type"], payload, player_id=player_id)
            created = row["created_at"]
            if not isinstance(created, datetime) or created.utcoffset() is None:
                continue
            event_id = str(UUID(str(row["id"])))
            if event_id in seen:
                continue
            seen.add(event_id)
            projected.append((row["sequence"], {
                "event_id": event_id, "event_type": row["event_type"],
                "created_at": created.astimezone(UTC).isoformat().replace("+00:00", "Z"), "data": data,
            }))
        except (KeyError, TypeError, ValueError):
            continue
    return [event for _, event in sorted(projected, key=lambda item: item[0])]


def private_event_data(state: object, event_type: str, payload: Mapping, *, player_id: UUID) -> dict:
    """8.2.2의 폐쇄형 private data를 구성해 sync와 AI 조회의 공통 필드 경계를 지킨다."""

    if not isinstance(payload, Mapping) or type(payload.get("round")) is not int or not 1 <= payload["round"] <= 5:
        raise ValueError("개인 event의 밤 번호가 올바르지 않습니다.")
    target = UUID(str(payload["target_player_id"]))
    if target not in state.player_by_id:
        raise ValueError("개인 event의 대상이 같은 게임에 없습니다.")
    from backend.app.models.enums import PlayerRole

    role = state.player_by_id[player_id].role
    data = {"round": payload["round"], "target_player_id": str(target)}
    if event_type == "INVESTIGATION_RESULT" and role is PlayerRole.DETECTIVE and type(payload.get("is_mafia")) is bool:
        data["is_mafia"] = payload["is_mafia"]
    elif event_type == "NIGHT_ACTION_ACCEPTED" and role is not PlayerRole.CITIZEN and payload.get("action_type") == {PlayerRole.MAFIA: "ATTACK", PlayerRole.DETECTIVE: "INVESTIGATE", PlayerRole.DOCTOR: "PROTECT"}.get(role):
        data["action_type"] = payload["action_type"]
    else:
        raise ValueError("승인되지 않은 개인 event입니다.")
    return data
