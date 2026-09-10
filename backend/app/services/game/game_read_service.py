"""PostgreSQL 게임 목록·snapshot 조회와 row 변환을 담당하는 모듈."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from psycopg import IsolationLevel
from psycopg.rows import dict_row

from backend.app.core.errors import ApiError
from backend.app.game_engine.rules.night_rules import ABILITY_ACTIONS, required_actors
from backend.app.infrastructure.transaction import TransactionManager
from backend.app.infrastructure.redis.cache import RedisConversationHistory
from backend.app.models.enums import Faction, GamePhase, GameStatus, PlayerKind, PlayerRole, WinReason
from backend.app.models.game_state import GameState, PlayerState
from backend.app.repositories.game_repository import GameStateKeyring
from backend.app.repositories.game_repository import PostgresGameRepository
from backend.app.repositories.player_repository import PostgresPlayerRepository
from backend.app.repositories.action_repository import PostgresActionRepository
from backend.app.repositories.event_repository import PostgresEventRepository
from backend.app.services.game.constants import INTRO_MESSAGE
from backend.app.services.game.helpers import window_id as uuid5_for_window
from backend.app.services.game.models import CanonicalGameRecord
from backend.app.services.game.result_service import build_result
from backend.app.services.game.postgres_helpers import restore_action_submissions, restore_revote_candidates


class PostgresGameReadService:
    """DB 원본에서 게임 목록·snapshot·sync를 읽는 facade다."""

    def __init__(
        self,
        *,
        transactions: TransactionManager,
        keyring: GameStateKeyring,
        games: PostgresGameRepository | None = None,
        players: PostgresPlayerRepository | None = None,
        events: PostgresEventRepository | None = None,
        actions: PostgresActionRepository | None = None,
        conversation_history: RedisConversationHistory | None = None,
    ) -> None:
        """읽기 업무에 필요한 transaction과 repository를 주입한다."""

        self._transactions = transactions
        self._keyring = keyring
        self._games = games or PostgresGameRepository()
        self._players = players or PostgresPlayerRepository()
        self._events = events or PostgresEventRepository(self._games)
        self._actions = actions or PostgresActionRepository()
        self._conversation_history = conversation_history

    def cache_public_history(self, record: CanonicalGameRecord, *, through_sequence: int,
                             events: list[dict[str, Any]]) -> bool:
        """공개 projection만 읽기 transaction 밖에서 저장하며 실패해도 원본은 보존한다."""

        if self._conversation_history is None:
            return False
        return self._conversation_history.set(
            str(record.state.game_id), state_version=record.state.state_version,
            through_sequence=through_sequence, front_sequence=record.front_sequence, events=events,
        )

    def refresh_public_history(self, owner_user_id: UUID, game_id: UUID) -> int:
        """commit된 공개 사건·발언을 소유권 확인 후 읽어 현재 버전의 Redis 이력으로 만든다."""

        with self._transactions.transaction() as connection:
            connection.isolation_level = IsolationLevel.REPEATABLE_READ
            connection.read_only = True
            with connection.cursor(row_factory=dict_row) as cursor:
                game = self._games.get_owned_game(cursor, owner_user_id=owner_user_id, game_id=game_id)
                if game is None:
                    raise ApiError(status_code=404, code="GAME_NOT_FOUND", message="게임을 찾을 수 없습니다.")
                players = self._players.list_players(cursor, game_id=game_id)
                record = initial_record_from_rows(keyring=self._keyring, game=game, player_rows=players)
                through_sequence = int(game["next_event_sequence"]) - 1
                events = read_public_history(self, cursor, record, through_sequence=through_sequence)
        self.cache_public_history(record, through_sequence=through_sequence, events=events)
        return len(events)

    def list_games(self, owner_user_id: UUID, *, status: str | None, limit: int) -> list[dict[str, Any]]:
        """소유자 게임 목록을 반환한다."""

        return list_games(self, owner_user_id, status=status, limit=limit)

    def snapshot(self, owner_user_id: UUID, game_id: UUID) -> dict[str, Any]:
        """소유자 snapshot을 반환한다."""

        return read_snapshot(self, owner_user_id, game_id)

    def sync(self, owner_user_id: UUID, game_id: UUID, *, after_state_version: int, after_sequence: int) -> dict[str, Any]:
        """event 정본에서 sync envelope를 반환한다."""

        from backend.app.services.game.event_sync_service import read_sync

        return read_sync(self, owner_user_id, game_id, after_state_version=after_state_version, after_sequence=after_sequence)

    def _initial_record_from_rows(self, game: Mapping[str, Any], player_rows: list[Mapping[str, Any]], window: Mapping[str, Any] | None = None, submissions: list[Mapping[str, Any]] | None = None) -> CanonicalGameRecord:
        """DB row를 canonical record로 변환한다."""

        return initial_record_from_rows(keyring=self._keyring, game=game, player_rows=player_rows, window=window, submissions=submissions)

    @staticmethod
    def _attach_human_facts(record: CanonicalGameRecord, facts: list[Mapping[str, Any]]) -> None:
        """인간에게 공개할 단서를 record에 결합한다."""

        attach_human_facts(record, facts)

    @staticmethod
    def _list_item(row: Mapping[str, Any]) -> dict[str, Any]:
        """게임 목록 row를 공개 projection으로 변환한다."""

        return list_item(row)


def list_games(reader: Any, owner_user_id: UUID, *, status: str | None, limit: int) -> list[dict[str, Any]]:
    """소유자 게임 목록을 DB에서 읽어 공개 목록 projection으로 변환한다."""

    try:
        with reader._transactions.transaction() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                rows = reader._games.list_owned_games(
                    cursor,
                    owner_user_id=owner_user_id,
                    status=status,
                    limit=limit,
                )
        return [list_item(row) for row in rows]
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(
            status_code=503,
            code="DEPENDENCY_UNAVAILABLE",
            message="게임 저장소를 사용할 수 없습니다.",
            retryable=True,
        ) from exc


def read_special_roles(reader: Any, *, owner_user_id: UUID, game_id: UUID) -> dict[str, Any]:
    """소유 HUMAN의 해금·능력을 같은 읽기 snapshot에서 검증한 뒤 특수 직업만 반환한다.

    AI context나 공개 cache를 경유하지 않으며 개인 단서·이벤트·제출 원장도 읽지 않는다.
    임의 actor 선택을 받지 않아 호출자가 다른 플레이어의 권한을 빌릴 수 없다.
    """

    try:
        with reader._transactions.transaction() as connection:
            connection.isolation_level = IsolationLevel.REPEATABLE_READ
            connection.read_only = True
            with connection.cursor(row_factory=dict_row) as cursor:
                game = reader._games.get_owned_game(
                    cursor, owner_user_id=owner_user_id, game_id=game_id,
                )
                if (game is None or UUID(str(game["id"])) != game_id
                        or UUID(str(game["owner_user_id"])) != owner_user_id):
                    raise ApiError(status_code=404, code="GAME_NOT_FOUND", message="게임을 찾을 수 없습니다.")
                rows = reader._players.list_players(cursor, game_id=game_id)
                humans = [row for row in rows if row["kind"] == "HUMAN"]
                if (game.get("mode") != "CUSTOM_ROLE" or len(humans) != 1
                        or humans[0].get("user_id") is None
                        or UUID(str(humans[0]["user_id"])) != owner_user_id):
                    raise ApiError(status_code=403, code="ABILITY_NOT_ALLOWED", message="사용할 수 없는 능력입니다.")
                # DB 행도 외부 입력이므로 bool 문자열이나 다른 게임의 행을 그대로 투영하지 않는다.
                if any(type(row["alive"]) is not bool or UUID(str(row["game_id"])) != game_id for row in rows):
                    raise ValueError("특수 직업 조회의 저장 행이 올바르지 않습니다.")
                record = initial_record_from_rows(keyring=reader._keyring, game=game, player_rows=rows)
                state = record.state
                human = state.player_by_id[record.human_player_id]
                if "intel.special_roles.v1" not in human.custom_ability_ids:
                    raise ApiError(status_code=403, code="ABILITY_NOT_ALLOWED", message="사용할 수 없는 능력입니다.")
                if state.status is not GameStatus.IN_PROGRESS or not human.alive or state.day_number < 2:
                    raise ApiError(status_code=409, code="ABILITY_NOT_AVAILABLE", message="아직 사용할 수 없는 능력입니다.")
                return {
                    "game_id": str(game_id), "player_id": str(human.player_id),
                    "ability_id": "intel.special_roles.v1", "state_version": state.state_version,
                    "roles": [
                        {"player_id": str(player.player_id), "display_name": player.display_name,
                         "role": player.role.value, "alive": player.alive}
                        for player in sorted(state.players, key=lambda player: player.seat)
                        if player.player_id != human.player_id
                        and player.role in {PlayerRole.DETECTIVE, PlayerRole.DOCTOR}
                    ],
                }
    except ApiError:
        raise
    except Exception:
        raise ApiError(
            status_code=503, code="DEPENDENCY_UNAVAILABLE",
            message="능력 정보를 조회할 수 없습니다.", retryable=True,
        ) from None


def read_snapshot(reader: Any, owner_user_id: UUID, game_id: UUID) -> dict[str, Any]:
    """소유자 검증부터 공개 snapshot 반환까지의 DB 조회 흐름을 실행한다."""

    try:
        with reader._transactions.transaction() as connection:
            # player·window·event가 서로 다른 command의 전후 상태로 섞이지 않게 한다.
            connection.isolation_level = IsolationLevel.REPEATABLE_READ
            connection.read_only = True
            with connection.cursor(row_factory=dict_row) as cursor:
                game = reader._games.get_owned_game(
                    cursor,
                    owner_user_id=owner_user_id,
                    game_id=game_id,
                )
                if game is None:
                    raise ApiError(
                        status_code=404,
                        code="GAME_NOT_FOUND",
                        message="게임을 찾을 수 없습니다.",
                    )
                player_rows = reader._players.list_players(cursor, game_id=game_id)
                window = reader._actions.active_window(cursor, game_id=game_id)
                submissions = (
                    reader._actions.list_discussion_submissions(
                        cursor,
                        game_id=game_id,
                        phase=str(game["phase"]),
                        round=int(game["round"]),
                        cycle=int(window["cycle"]),
                    )
                    if window is not None
                    and str(game["phase"]) in {GamePhase.DAY_DISCUSSION.value, GamePhase.FINAL_DISCUSSION.value}
                    else []
                )
                action_submissions = (
                    reader._actions.list_window_action_submissions(cursor, window_id=UUID(str(window["id"])))
                    if window is not None and str(game["phase"]) in {"NIGHT_ACTION", "DAY_VOTE", "REVOTE", "FINAL_ACCUSATION"}
                    else []
                )
                record = initial_record_from_rows(
                    keyring=reader._keyring, game=game, player_rows=player_rows,
                    window=window, submissions=submissions,
                )
                facts = reader._players.list_player_facts(
                    cursor,
                    game_id=game_id,
                    player_id=record.human_player_id,
                )
                through_sequence = int(game["next_event_sequence"]) - 1
                record.public_events = read_public_history(
                    reader, cursor, record, through_sequence=through_sequence,
                )
                private_rows = reader._events.list_snapshot_private_events(
                    cursor, game_id=game_id, player_id=record.human_player_id,
                    through_sequence=through_sequence,
                    through_state_version=record.state.state_version,
                    through_front_sequence=record.front_sequence,
                )
                record.private_events = _snapshot_private_events(record, private_rows, through_sequence=through_sequence)
                record.resolutions = reader._actions.list_resolutions(cursor, game_id=game_id, through_state_version=record.state.state_version)
                restore_revote_candidates(record.state, record.resolutions)
                if window is not None and record.state.phase in {GamePhase.NIGHT_ACTION, GamePhase.DAY_VOTE, GamePhase.REVOTE, GamePhase.FINAL_ACCUSATION}:
                    restore_action_submissions(record.state, action_submissions)
        reader.cache_public_history(record, through_sequence=through_sequence, events=record.public_events)
        attach_human_facts(record, facts)
        return build_snapshot(record)
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(
            status_code=503,
            code="DEPENDENCY_UNAVAILABLE",
            message="게임 저장소를 사용할 수 없습니다.",
            retryable=True,
        ) from exc


def read_public_history(reader: Any, cursor: Any, record: CanonicalGameRecord,
                        *, through_sequence: int) -> list[dict[str, Any]]:
    """현재 DB 상한의 Redis 이력을 재검증하고 miss이면 제한 없이 전체 원장을 읽는다."""

    history = getattr(reader, "_conversation_history", None)
    cached = history.get(
        str(record.state.game_id), state_version=record.state.state_version,
        through_sequence=through_sequence, front_sequence=record.front_sequence,
    ) if history is not None else None
    if cached is not None:
        try:
            result, identifiers = [], set()
            for event in cached:
                if set(event) != {"event_id", "event_type", "created_at", "data"}:
                    raise ValueError("대화 cache의 공개 필드가 올바르지 않습니다.")
                identifier = str(UUID(event["event_id"]))
                created_at = datetime.fromisoformat(event["created_at"].replace("Z", "+00:00"))
                if identifier in identifiers or created_at.utcoffset() is None:
                    raise ValueError("대화 cache의 순서 식별자가 올바르지 않습니다.")
                identifiers.add(identifier)
                data = _public_event_data(event["event_type"], event["data"], record)
                if data != event["data"]:
                    raise ValueError("대화 cache에 승인되지 않은 데이터가 있습니다.")
                result.append({**event, "event_id": identifier, "data": data})
            return result
        except (KeyError, TypeError, ValueError, AttributeError):
            pass
    rows = reader._events.list_snapshot_public_events(
        cursor, game_id=record.state.game_id, through_sequence=through_sequence,
        through_state_version=record.state.state_version, through_front_sequence=record.front_sequence,
    )
    return _snapshot_public_events(record, rows, through_sequence=through_sequence)


def _snapshot_public_events(
    record: CanonicalGameRecord,
    rows: list[Mapping[str, Any]],
    *,
    through_sequence: int,
) -> list[dict[str, Any]]:
    """승인된 공개 event만 새 object로 투영하고 내부 sequence 순서로 복원한다.

    legacy ACTION_RESOLVED는 PUBLIC으로 저장됐어도 개별 밤 행동·투표 대상을
    포함하므로 허용하지 않는다. 확정 투표는 승인된 boolean tied와 후보별 합계만
    복원하며 개별 표는 종료 결과에만 포함한다. 잘못된 행은 원문을 로그에 남기지 않고 건너뛰며,
    저장소 조회 자체의 실패는 호출자의 기존 503 경로로 전달한다.
    """

    events: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        try:
            if (
                UUID(str(row["game_id"])) != record.state.game_id
                or row["audience"] != "PUBLIC"
                or row["audience_player_id"] is not None
                or row["operation_type"] != "APPEND_PUBLIC_EVENT"
                or type(row["schema_version"]) is not int
                or row["schema_version"] != 1
            ):
                continue
            sequence = _event_integer(row["sequence"], 1, through_sequence)
            _event_integer(row["state_version"], 1, record.state.state_version)
            _event_integer(row["front_sequence"], 1, record.front_sequence)
            _event_integer(row["operation_index"], 0, 32767)
            event_id = str(UUID(str(row["id"])))
            created_at = row["created_at"]
            if not isinstance(created_at, datetime) or created_at.utcoffset() is None:
                continue
            event_type = row["event_type"]
            payload = row["payload"]
            if not isinstance(event_type, str) or not isinstance(payload, Mapping):
                continue
            data = _public_event_data(event_type, payload, record)
            events.append((sequence, {
                "event_id": event_id,
                "event_type": event_type,
                "created_at": created_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                "data": data,
            }))
        except (KeyError, TypeError, ValueError):
            continue
    return [event for _, event in sorted(events, key=lambda item: item[0])]


def _snapshot_private_events(record: CanonicalGameRecord, rows: list[Mapping[str, Any]], *, through_sequence: int) -> list[dict[str, Any]]:
    """소유 게임 인간에게 지정된 조사·밤 접수 event만 상한 안에서 복원한다."""

    events = []
    for row in rows:
        try:
            if (UUID(str(row["game_id"])) != record.state.game_id or row["audience"] != "PLAYER"
                    or UUID(str(row["audience_player_id"])) != record.human_player_id
                    or row["operation_type"] != "APPEND_PRIVATE_EVENT"
                    or type(row["schema_version"]) is not int or row["schema_version"] != 1):
                continue
            sequence = _event_integer(row["sequence"], 1, through_sequence)
            _event_integer(row["state_version"], 1, record.state.state_version)
            _event_integer(row["front_sequence"], 1, record.front_sequence)
            _event_integer(row["operation_index"], 0, 32767)
            payload = row["payload"]
            if not isinstance(payload, Mapping):
                continue
            target = UUID(str(payload["target_player_id"]))
            if target not in record.state.player_by_id:
                continue
            data = {"round": _event_integer(payload["round"], 1, 5), "target_player_id": str(target)}
            human_role = record.state.player_by_id[record.human_player_id].role
            human = record.state.player_by_id[record.human_player_id]
            if row["event_type"] == "INVESTIGATION_RESULT":
                can_investigate = (
                    human_role is PlayerRole.DETECTIVE
                    or "night.investigate.v1" in human.custom_ability_ids
                )
                if not can_investigate or type(payload["is_mafia"]) is not bool:
                    continue
                data["is_mafia"] = payload["is_mafia"]
            elif row["event_type"] == "NIGHT_ACTION_ACCEPTED":
                standard_action = {
                    PlayerRole.MAFIA: "ATTACK", PlayerRole.DOCTOR: "PROTECT",
                    PlayerRole.DETECTIVE: "INVESTIGATE",
                }.get(human_role)
                custom_actions = {
                    {"night.attack.v1": "ATTACK", "night.investigate.v1": "INVESTIGATE",
                     "night.protect.v1": "PROTECT"}[ability]
                    for ability in human.custom_ability_ids if ability in ABILITY_ACTIONS
                }
                if payload["action_type"] not in ({standard_action} if not custom_actions else custom_actions):
                    continue
                data["action_type"] = payload["action_type"]
            else:
                continue
            created_at = row["created_at"]
            if not isinstance(created_at, datetime) or created_at.utcoffset() is None:
                continue
            events.append((sequence, {"event_id": str(UUID(str(row["id"]))), "event_type": row["event_type"], "created_at": created_at.astimezone(UTC).isoformat().replace("+00:00", "Z"), "data": data}))
        except (KeyError, TypeError, ValueError):
            continue
    return [event for _, event in sorted(events, key=lambda item: item[0])]


def _event_integer(value: Any, minimum: int, maximum: int) -> int:
    """bool과 숫자 문자열의 암묵적 변환을 막고 공개 계약의 정수 범위를 검사한다."""

    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("공개 event 정수 범위가 올바르지 않습니다.")
    return value


def _public_event_data(
    event_type: str, payload: Mapping[str, Any], record: CanonicalGameRecord
) -> dict[str, Any]:
    """API 정본의 필수 필드만 명시적으로 복사해 추가 payload의 유출을 막는다.

    공개 player ID는 조회한 게임의 참가자 집합으로 제한한다. 발언 외의 자유 문자열과
    다른 플레이어의 역할·행동 대상 등 unknown 필드는 공개 data로 전파하지 않는다.
    """

    def player_id(value: Any) -> str:
        """UUID 형식뿐 아니라 같은 게임의 공개 참가자인지도 확인한다."""

        identifier = UUID(str(value))
        if identifier not in record.state.player_by_id:
            raise ValueError("공개 event의 참가자가 올바르지 않습니다.")
        return str(identifier)

    if event_type == "GAME_BEGAN":
        if payload["message"] != INTRO_MESSAGE:
            raise ValueError("공개 시작 문구가 정본과 일치하지 않습니다.")
        return {"message": INTRO_MESSAGE}
    if event_type == "PLAYER_SPOKE":
        message = payload["message"]
        if not isinstance(message, str):
            raise ValueError("공개 발언 형식이 올바르지 않습니다.")
        message = " ".join(message.split())
        if not 1 <= len(message) <= 200:
            raise ValueError("공개 발언 길이가 올바르지 않습니다.")
        return {"player_id": player_id(payload["player_id"]), "message": message}
    if event_type == "PLAYER_PASSED":
        return {"player_id": player_id(payload["player_id"])}
    if event_type == "TURN_OPENED":
        cycle = _event_integer(payload["cycle"], 1, 2)
        expected_prompt = "현재 가장 의심되는 플레이어와 그 이유를 한 문장으로 말해 주세요." if cycle == 2 else None
        if payload["prompt"] != expected_prompt:
            raise ValueError("공개 턴 안내가 정본과 일치하지 않습니다.")
        return {"player_id": player_id(payload["player_id"]), "cycle": cycle, "prompt": expected_prompt}
    if event_type == "NIGHT_RESOLVED":
        killed = payload["killed_player_id"]
        return {
            "round": _event_integer(payload["round"], 1, 5),
            "killed_player_id": player_id(killed) if killed is not None else None,
        }
    if event_type == "VOTE_RESOLVED":
        phase = GamePhase(payload["phase"])
        if phase not in {GamePhase.DAY_VOTE, GamePhase.REVOTE, GamePhase.FINAL_ACCUSATION}:
            raise ValueError("공개 투표 단계가 올바르지 않습니다.")
        if type(payload["tied"]) is not bool or type(payload["needs_revote"]) is not bool:
            raise ValueError("공개 투표 동률 형식이 올바르지 않습니다.")
        if payload["needs_revote"] != (phase is GamePhase.DAY_VOTE and payload["tied"]):
            raise ValueError("공개 재투표 상태가 올바르지 않습니다.")
        raw_counts = payload["counts"]
        if not isinstance(raw_counts, list) or not raw_counts:
            raise ValueError("공개 투표 집계가 비어 있습니다.")
        counts = []
        seats = []
        # 과거 공개 집계에는 현재 사망한 능력자의 표도 포함될 수 있으므로 생존으로 좁히지 않는다.
        max_votes = len(record.state.players) + (2 if (
            phase in {GamePhase.DAY_VOTE, GamePhase.REVOTE}
            and record.state.mode == "CUSTOM_ROLE"
            and any(player.kind is PlayerKind.HUMAN and "vote.triple.v1" in player.custom_ability_ids
                    for player in record.state.players)
        ) else 0)
        for item in raw_counts:
            if not isinstance(item, Mapping) or set(item) != {"target_player_id", "vote_count"}:
                raise ValueError("공개 집계에 허용되지 않은 필드가 있습니다.")
            identifier = player_id(item["target_player_id"])
            seats.append(record.state.player_by_id[UUID(identifier)].seat)
            counts.append({"target_player_id": identifier, "vote_count": _event_integer(item["vote_count"], 0, max_votes)})
        total = sum(item["vote_count"] for item in counts)
        maximum = max(item["vote_count"] for item in counts)
        if seats != sorted(set(seats)) or not 2 <= total <= max_votes:
            raise ValueError("공개 집계 순서 또는 표 수가 올바르지 않습니다.")
        if payload["tied"] != (sum(item["vote_count"] == maximum for item in counts) > 1):
            raise ValueError("공개 집계와 동률 상태가 다릅니다.")
        return {"round": _event_integer(payload["round"], 1, 5), "phase": phase.value, "counts": counts, "tied": payload["tied"], "needs_revote": payload["needs_revote"]}
    if event_type == "PLAYER_EXECUTED":
        return {
            "player_id": player_id(payload["player_id"]),
            "revealed_role": PlayerRole(payload["revealed_role"]).value,
        }
    if event_type == "FAST_FORWARD_ENABLED":
        if payload["enabled"] is not True:
            raise ValueError("공개 빠른 진행 event는 활성화만 허용합니다.")
        return {"enabled": True}
    if event_type in {"GAME_SAVED", "GAME_RESUMED"}:
        return {
            "phase": GamePhase(payload["phase"]).value,
            "round": _event_integer(payload["round"], 0, 5),
        }
    if event_type == "GAME_ENDED":
        return {
            "winner": Faction(payload["winner"]).value,
            "win_reason": WinReason(payload["win_reason"]).value,
        }
    raise ValueError("승인되지 않은 공개 event입니다.")


def initial_record_from_rows(
    *,
    keyring: GameStateKeyring,
    game: Mapping[str, Any],
    player_rows: list[Mapping[str, Any]],
    window: Mapping[str, Any] | None = None,
    submissions: list[Mapping[str, Any]] | None = None,
) -> CanonicalGameRecord:
    """DB row를 현재 GameState와 공개 snapshot 원장으로 복원한다."""

    if not isinstance(game["updated_at"], datetime):
        raise RuntimeError("Persisted game timestamp is invalid")
    seed = keyring.decrypt_seed(
        ciphertext=bytes(game["seed_ciphertext"]),
        nonce=bytes(game["seed_nonce"]),
        key_id=str(game["seed_key_id"]),
    )
    from backend.app.services.game.postgres_helpers import validate_custom_player_rows

    validate_custom_player_rows(game, player_rows)
    players: list[PlayerState] = []
    human_player_id: UUID | None = None
    eliminated: dict[UUID, tuple[str, int]] = {}
    for row in player_rows:
        player_id = UUID(str(row["id"]))
        player = PlayerState(
            player_id=player_id,
            seat=int(row["seat"]),
            role=PlayerRole(str(row["role"])),
            kind=PlayerKind(str(row["kind"])),
            display_name=str(row["display_name"]),
            alive=bool(row["alive"]),
            custom_role_name=row.get("custom_role_name"),
            custom_role_catalog_version=row.get("custom_role_catalog_version"),
            custom_ability_ids=tuple(row.get("custom_ability_ids") or ()),
            custom_faction=Faction(str(row["faction"])) if row.get("custom_ability_ids") else None,
        )
        players.append(player)
        if player.kind is PlayerKind.HUMAN:
            if human_player_id is not None or row["user_id"] is None:
                raise RuntimeError("Persisted human player is invalid")
            human_player_id = player_id
        if not player.alive:
            phase = row["eliminated_phase"]
            round_number = row["eliminated_round"]
            if phase is None or round_number is None:
                raise RuntimeError("Persisted eliminated player is invalid")
            eliminated[player_id] = (str(phase), int(round_number))
    if human_player_id is None or len(players) != int(game["player_count"]):
        raise RuntimeError("Persisted players are incomplete")

    state = GameState(
        game_id=UUID(str(game["id"])),
        seed=seed,
        players=players,
        phase=GamePhase(str(game["phase"])),
        status=GameStatus(str(game["status"])),
        round=int(game["round"]),
        day_number=int(game["day_number"]),
        state_version=int(game["state_version"]),
        updated_at=game["updated_at"],
        winner=Faction(str(game["winner"])) if game["winner"] is not None else None,
        win_reason=WinReason(str(game["win_reason"])) if game["win_reason"] is not None else None,
        mode=str(game.get("mode") or "STANDARD"),
    )
    state.fast_forward_enabled = game.get("fast_forward_enabled") is True
    # 구형 엔진은 지난 밤 수를 round로 저장했다. 새 계약과 구분되는 밤 상태만
    # 메모리에서 정규화하고 제출 window·마감·이미 확정된 원장은 건드리지 않는다.
    if state.phase is GamePhase.NIGHT_ACTION and 1 <= state.day_number <= 5 and state.round == state.day_number - 1:
        state.round = state.day_number
    if window is not None and state.phase in {GamePhase.DAY_DISCUSSION, GamePhase.FINAL_DISCUSSION}:
        discussion_submissions = submissions or []
        state.speech_actors = {UUID(str(row["actor_player_id"])) for row in discussion_submissions}
        state.speech_had_content = any(row["action_type"] == "SPEAK" for row in discussion_submissions)
        state.speech_question_cycle_used = state.day_number >= 2 and int(window["cycle"]) == 2
    locations = game["scenario_locations"]
    if not isinstance(locations, list) or not all(isinstance(item, str) for item in locations):
        raise RuntimeError("Persisted scenario locations are invalid")
    return CanonicalGameRecord(
        state=state,
        scenario={
            "scenario_id": str(game["scenario_id"]),
            "title": str(game["scenario_title"]),
            "background": str(game["scenario_background"]),
            "victim": str(game["scenario_victim"]),
            "locations": list(locations),
        },
        human_player_id=human_player_id,
        owner_user_id=UUID(str(game["owner_user_id"])),
        alibi="",
        observation="",
        front_sequence=max(int(game["next_front_sequence"]) - 1, 0),
        eliminated=eliminated,
        action_window=dict(window) if window is not None else None,
    )


def attach_human_facts(record: CanonicalGameRecord, facts: list[Mapping[str, Any]]) -> None:
    """공개 snapshot에 현재 인간 플레이어의 두 단서만 연결한다."""

    by_kind = {str(fact["fact_kind"]): str(fact["rendered_text"]) for fact in facts}
    if set(by_kind) != {"ALIBI", "OBSERVATION"}:
        raise RuntimeError("Persisted human facts are incomplete")
    record.alibi = by_kind["ALIBI"]
    record.observation = by_kind["OBSERVATION"]


def build_snapshot(record: CanonicalGameRecord) -> dict[str, Any]:
    """PostgreSQL에서 복원한 canonical record를 공개 snapshot으로 투영한다.

    이 함수는 저장소나 InMemory service를 생성하지 않는 순수 projection이다. 공개
    player 정보와 인간 본인의 private facts를 한 곳에서 분리해, read service가
    테스트용 실행 runtime을 presenter로 우회하지 않도록 한다.
    """

    state = record.state
    players = []
    for player in sorted(state.players, key=lambda item: item.seat):
        eliminated = record.eliminated.get(player.player_id)
        revealed = (
            player.role.value
            if state.status is GameStatus.COMPLETED
            or (
                not player.alive
                and eliminated
                and eliminated[0] in {"DAY_VOTE", "REVOTE", "FINAL_ACCUSATION"}
            )
            else None
        )
        players.append(
            {
                "player_id": str(player.player_id),
                "seat": player.seat,
                "display_name": player.display_name,
                "kind": player.kind.value,
                "alive": player.alive,
                "revealed_role": revealed,
                "revealed_role_name": (
                    player.custom_role_name if revealed is not None else None
                ),
                "eliminated_phase": eliminated[0] if eliminated else None,
                "eliminated_round": eliminated[1] if eliminated else None,
            }
        )
    human = state.player_by_id[record.human_player_id]
    legal = legal_actions(record)
    return {
        "game": {
            "game_id": str(state.game_id),
            "status": state.status.value,
            "phase": state.phase.value,
            "round": state.round,
            "day_number": state.day_number,
            "state_version": state.state_version,
            "last_sequence": record.front_sequence,
            "ruleset_version": "mystery-v1",
            "scenario_version": "scenario-v1",
            "mode": state.mode,
            "player_count": len(state.players),
            "mafia_count": sum(player.faction is Faction.MAFIA for player in state.players),
            "fast_forward_enabled": record.state.fast_forward_enabled,
            "updated_at": state.updated_at.isoformat(),
        },
        "scenario": copy.deepcopy(record.scenario),
        "players": players,
        "me": {
            "player_id": str(record.human_player_id),
            "role": human.role.value,
            "alive": human.alive,
            "spectator": not human.alive,
            "alibi": record.alibi,
            "observation": record.observation,
            "private_events": copy.deepcopy(record.private_events),
            **({
                "role_name": human.custom_role_name,
                "faction": human.faction.value,
                "ability_ids": list(human.custom_ability_ids),
                "ability_options": _ability_options(record),
            } if state.mode == "CUSTOM_ROLE" else {}),
        },
        "action_window": action_window(record, legal),
        "legal_actions": legal,
        "public_events": copy.deepcopy(record.public_events),
        "result": build_result(state, resolutions=record.resolutions, eliminated=record.eliminated, public_events=record.public_events),
    }


def legal_actions(record: CanonicalGameRecord) -> list[str]:
    """현재 상태에서 인간에게 공개할 command 종류를 계산한다."""

    state = record.state
    human = state.player_by_id[record.human_player_id]
    if state.status is GameStatus.SAVED:
        return ["RESUME"]
    if state.status is not GameStatus.IN_PROGRESS or not human.alive:
        return (["SAVE_AND_EXIT"] if record.state.fast_forward_enabled else ["FAST_FORWARD", "SAVE_AND_EXIT"]) if not human.alive and state.status is GameStatus.IN_PROGRESS else []
    if state.phase is GamePhase.ROLE_REVEAL:
        return ["BEGIN_GAME", "SAVE_AND_EXIT"]
    if state.phase in {GamePhase.DAY_DISCUSSION, GamePhase.FINAL_DISCUSSION} and record.action_window and record.action_window.get("deadline_at") is not None:
        now = datetime.now(UTC)
        if record.action_window["deadline_at"] <= now:
            return ["SAVE_AND_EXIT"]
        count = sum(event.get("event_type") == "PLAYER_SPOKE"
                    and event.get("data", {}).get("player_id") == str(record.human_player_id)
                    and datetime.fromisoformat(event["created_at"].replace("Z", "+00:00")) > now - timedelta(seconds=60)
                    for event in record.public_events)
        return ["SPEAK", "SAVE_AND_EXIT"] if count < 7 else ["SAVE_AND_EXIT"]
    if state.phase in {GamePhase.DAY_DISCUSSION, GamePhase.FINAL_DISCUSSION} and (record.action_window and record.action_window.get("deadline_at") is not None or record.human_player_id not in state.speech_actors):
        return (["SPEAK", "SAVE_AND_EXIT"] if state.phase is GamePhase.DAY_DISCUSSION
                and state.day_number == 1 else ["SPEAK", "PASS", "SAVE_AND_EXIT"])
    if (state.phase is GamePhase.NIGHT_ACTION and human in required_actors(state)
            and record.human_player_id not in state.night_actions):
        return ["SUBMIT_NIGHT_ACTION", "SAVE_AND_EXIT"]
    if state.phase in {GamePhase.DAY_VOTE, GamePhase.REVOTE, GamePhase.FINAL_ACCUSATION} and record.human_player_id not in state.votes:
        return ["SUBMIT_VOTE", "SAVE_AND_EXIT"]
    return ["SAVE_AND_EXIT"]


def action_window(record: CanonicalGameRecord, legal: list[str]) -> dict[str, Any] | None:
    """복원된 DB window를 공개 action window projection으로 변환한다."""

    state = record.state
    kind = {
        GamePhase.DAY_DISCUSSION: "SPEECH",
        GamePhase.FINAL_DISCUSSION: "SPEECH",
        GamePhase.NIGHT_ACTION: "NIGHT",
        GamePhase.DAY_VOTE: "VOTE",
        GamePhase.REVOTE: "REVOTE",
        GamePhase.FINAL_ACCUSATION: "FINAL_VOTE",
    }.get(state.phase)
    if kind is None or state.status is GameStatus.COMPLETED:
        return None
    persisted = record.action_window
    if persisted is not None:
        timed = kind != "SPEECH" or persisted.get("deadline_at") is not None or persisted.get("remaining_ms_on_save") is not None
        now = datetime.now(UTC)
        if timed and state.status is GameStatus.IN_PROGRESS:
            deadline = persisted["deadline_at"]
            if not isinstance(deadline, datetime):
                raise RuntimeError("Active timed action window deadline is invalid")
            remaining_ms = max(int((deadline - now).total_seconds() * 1000), 0)
        elif timed:
            remaining_ms = (
                int(persisted["remaining_ms_on_save"])
                if persisted["remaining_ms_on_save"] is not None
                else None
            )
        else:
            remaining_ms = None
        return {
            "window_id": str(persisted["id"]),
            "kind": kind,
            "cycle": int(persisted["cycle"]),
            "paused": persisted["status"] == "PAUSED" or state.status is GameStatus.SAVED,
            "opened_state_version": int(persisted["opened_state_version"]),
            "server_time": now.isoformat().replace("+00:00", "Z"),
            "deadline_at": None if not timed or state.status is GameStatus.SAVED else (
                persisted["deadline_at"].isoformat().replace("+00:00", "Z")
                if persisted["deadline_at"] is not None else None
            ),
            "remaining_ms": remaining_ms,
            "turn_player_id": str(persisted["turn_player_id"]) if persisted["turn_player_id"] is not None else None,
            "has_submitted": not any(action in legal for action in {"SPEAK", "PASS", "SUBMIT_NIGHT_ACTION", "SUBMIT_VOTE"}),
            "legal_actions": legal if state.status is GameStatus.IN_PROGRESS else [],
            "valid_targets": _valid_targets(record, kind),
        }
    timed = kind != "SPEECH"
    now = datetime.now(UTC)
    return {
        "window_id": str(uuid5_for_window(state.game_id, state.state_version)),
        "kind": kind,
        "cycle": 1,
        "paused": state.status is GameStatus.SAVED,
        "opened_state_version": state.state_version,
        "server_time": now.isoformat().replace("+00:00", "Z"),
        "deadline_at": None if not timed or state.status is GameStatus.SAVED else (now + timedelta(seconds=30)).isoformat().replace("+00:00", "Z"),
        "remaining_ms": 30_000 if timed and state.status is GameStatus.IN_PROGRESS else None,
        "turn_player_id": str(record.human_player_id) if kind == "SPEECH" else None,
        "has_submitted": not any(action in legal for action in {"SPEAK", "PASS", "SUBMIT_NIGHT_ACTION", "SUBMIT_VOTE"}),
        "legal_actions": legal if state.status is GameStatus.IN_PROGRESS else [],
        "valid_targets": _valid_targets(record, kind),
    }


def _valid_targets(record: CanonicalGameRecord, kind: str) -> list[dict[str, str]]:
    """현재 공개 window에서 선택 가능한 생존 대상만 반환한다."""

    if kind == "SPEECH":
        return []
    human = record.state.player_by_id[record.human_player_id]
    return [
        {"player_id": str(player.player_id), "display_name": player.display_name}
        for player in record.state.alive_players
        if (player.player_id != record.human_player_id or (kind == "NIGHT" and human.role is PlayerRole.DOCTOR))
        and (kind != "REVOTE" or player.player_id in record.state.revote_candidates)
    ]


def _ability_options(record: CanonicalGameRecord) -> list[dict[str, Any]]:
    """본인에게 저장된 CUSTOM_ROLE 능력과 능력별 현재 대상만 반환한다."""

    from backend.app.schemas.game_schema import CUSTOM_ROLE_ABILITIES

    human = record.state.player_by_id[record.human_player_id]
    if (record.state.phase is not GamePhase.NIGHT_ACTION
            or record.human_player_id in record.state.night_actions or not human.alive):
        return []
    options = []
    for ability_id in human.custom_ability_ids:
        if ability_id not in ABILITY_ACTIONS:
            continue
        allow_self = ability_id == "night.protect.v1"
        targets = [
            {"player_id": str(player.player_id), "display_name": player.display_name}
            for player in record.state.alive_players
            if allow_self or player.player_id != human.player_id
        ]
        options.append({
            "ability_id": ability_id,
            "label": CUSTOM_ROLE_ABILITIES[ability_id]["label"],
            "valid_targets": targets,
        })
    return options


def list_item(row: Mapping[str, Any]) -> dict[str, Any]:
    """게임 목록용 공개 projection을 만든다."""

    updated_at = row["updated_at"]
    if not isinstance(updated_at, datetime):
        raise RuntimeError("Persisted game timestamp is invalid")
    status = GameStatus(str(row["status"]))
    return {
        "game_id": str(row["id"]),
        "status": status.value,
        "phase": str(row["phase"]),
        "round": int(row["round"]),
        "day_number": int(row["day_number"]),
        "state_version": int(row["state_version"]),
        "scenario_title": str(row["scenario_title"]),
        "player_count": int(row["player_count"]),
        "human_alive": bool(row["human_alive"]),
        "winner": str(row["winner"]) if row["winner"] is not None else None,
        "can_resume": status is GameStatus.SAVED,
        "updated_at": updated_at.isoformat(),
    }

__all__ = [
    "PostgresGameReadService",
    "attach_human_facts",
    "action_window",
    "build_snapshot",
    "initial_record_from_rows",
    "legal_actions",
    "list_item",
]
