"""게임 command 입력의 Front guard와 정규화 규칙."""

from __future__ import annotations

import unicodedata
from collections import deque
from concurrent.futures import Future
from copy import deepcopy
from datetime import datetime
from threading import Event, RLock, Thread
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

from frontend_user.core.api_client import ApiResponseError


def normalize_message(value: str) -> str:
    """Unicode NFC와 공백 정규화 후 1~200자, 제어 문자 없는 본문만 허용한다."""

    # 팀 전달 사항: Backend도 동일하게 공백 정규화·1~200 Unicode code point와
    # 제어 문자 규칙을 검증해야 한다. Front 검증은 UX용이며 서버 판정을 대체하지 않는다.
    if any(unicodedata.category(char).startswith("C") for char in value):
        raise ValueError("발언은 제어 문자 없이 1자부터 200자까지 입력해 주세요.")
    normalized = " ".join(unicodedata.normalize("NFC", value).split())
    if not normalized or len(normalized) > 200:
        raise ValueError("발언은 제어 문자 없이 1자부터 200자까지 입력해 주세요.")
    return normalized


ABILITY_DESCRIPTIONS = {
    "night.attack.v1": "공격: 자신을 제외한 생존자 한 명을 공격합니다.",
    "night.investigate.v1": "조사: 자신을 제외한 생존자 한 명의 진영을 확인합니다.",
    "night.protect.v1": "보호: 자신을 포함한 생존자 한 명을 보호합니다.",
    "vote.triple.v1": "투표 조작: 낮 투표·재투표에서 선택한 한 표를 3표로 제출합니다.",
    "intel.special_roles.v1": "특수 직업 열람: 첫 밤 종료 후 다른 탐정·의사의 직업을 나에게만 표시합니다.",
}


CUSTOM_ABILITY_LABELS = {
    "night.attack.v1": "공격", "night.investigate.v1": "조사", "night.protect.v1": "보호",
    "vote.triple.v1": "투표 조작", "intel.special_roles.v1": "특수 직업 열람",
}


def validate_ability_catalog(response: Any) -> dict[str, Any] | None:
    """success envelope 안의 폐쇄형 다섯 descriptor만 신뢰하고 구버전도 거부한다."""

    data = response.get("data") if isinstance(response, dict) and "error" not in response else None
    if (not isinstance(data, dict) or set(data) != {"catalog_version", "abilities"}
            or data["catalog_version"] != "custom-role-v1" or not isinstance(data["abilities"], list)
            or len(data["abilities"]) != 5):
        return None
    seen = set()
    for item in data["abilities"]:
        if not isinstance(item, dict) or set(item) != {"id", "label", "factions"}:
            return None
        value = item["id"]
        if not isinstance(value, str) or value not in CUSTOM_ABILITY_LABELS or value in seen:
            return None
        factions = ["MAFIA"] if value == "night.attack.v1" else ["CITIZEN", "MAFIA"]
        if (not isinstance(item["label"], str) or item["label"] != CUSTOM_ABILITY_LABELS[value]
                or type(item["factions"]) is not list or item["factions"] != factions):
            return None
        seen.add(value)
    return deepcopy(data)


def owns_custom_ability(snapshot: dict[str, Any], ability_id: str) -> bool:
    """본인과 공개 명부의 HUMAN 좌석이 일치할 때만 커스텀 능력 UI를 허용한다."""

    game, me = snapshot.get("game", {}), snapshot.get("me", {})
    players = snapshot.get("players", [])
    if not isinstance(game, dict) or not isinstance(me, dict):
        return False
    return (game.get("mode") == "CUSTOM_ROLE" and game.get("status") == "IN_PROGRESS"
            and me.get("alive") is True and me.get("spectator") is not True
            and isinstance(me.get("ability_ids"), list) and ability_id in me["ability_ids"]
            and isinstance(players, list) and any(isinstance(player, dict)
                and player.get("player_id") == me.get("player_id") and player.get("kind") == "HUMAN"
                for player in players))


def can_use_triple_vote(snapshot: dict[str, Any]) -> bool:
    """최종 지목과 표준 게임에서는 능력 선택과 전송을 모두 차단한다."""

    return (snapshot.get("game", {}).get("phase") in {"DAY_VOTE", "REVOTE"}
            and owns_custom_ability(snapshot, "vote.triple.v1"))


def normalize_role_name(value: str) -> str:
    """표시용 직업명을 NFC와 공백 기준으로 정리하고 제어 문자 입력을 거부한다."""

    if any(unicodedata.category(char).startswith("C") for char in value):
        raise ValueError("직업명에는 제어 문자를 사용할 수 없습니다.")
    name = " ".join(unicodedata.normalize("NFC", value).split())
    if not 1 <= len(name) <= 40:
        raise ValueError("직업명은 공백 정리 후 1~40자로 입력해 주세요.")
    return name


def custom_ability_options(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """본인에게 저장된 능력과 진영에 일치하는 공개 ID만 밤 입력에 사용한다."""

    me = snapshot.get("me", {})
    if snapshot.get("game", {}).get("mode") != "CUSTOM_ROLE" or me.get("faction") not in {"CITIZEN", "MAFIA"}:
        return []
    owned = me.get("ability_ids", [])
    options = me.get("ability_options", [])
    if not isinstance(owned, list) or not isinstance(options, list):
        return []
    return [option for option in options if isinstance(option, dict)
            and isinstance(option.get("ability_id"), str)
            and option.get("ability_id") in {"night.attack.v1", "night.investigate.v1", "night.protect.v1"}
            and option["ability_id"] in owned
            and (me["faction"] == "MAFIA" or option["ability_id"] != "night.attack.v1")
            and isinstance(option.get("valid_targets"), list)]


def build_command(*, snapshot: dict[str, Any], command_type: str,
                  message: str | None = None, target_player_id: str | None = None,
                  ability_id: str | None = None) -> dict[str, Any]:
    """snapshot에서 입력 형식만 정규화해 Backend 검증용 command를 만든다."""

    # Front snapshot의 legal_actions·valid_targets·turn 정보는 SSE 시점 차이로
    # stale될 수 있다. Front는 형식만 정리하고 행동 가능 여부는 Backend가 최신
    # DB transaction에서 최종 판정하도록 요청을 전송한다.

    game = snapshot.get("game")
    if not isinstance(game, dict):
        raise ValueError("게임 상태를 확인할 수 없습니다.")
    if command_type not in {"SPEAK", "PASS", "SUBMIT_NIGHT_ACTION", "SUBMIT_VOTE", "SAVE_AND_EXIT", "RESUME", "FAST_FORWARD", "BEGIN_GAME"}:
        raise ValueError("지원하지 않는 게임 행동입니다.")
    window = snapshot.get("action_window")
    body: dict[str, Any] = {
        "type": command_type,
        "expected_state_version": game.get("state_version"),
    }
    if command_type in {"SPEAK", "PASS", "SUBMIT_NIGHT_ACTION", "SUBMIT_VOTE"} and isinstance(window, dict):
        body["window_id"] = window.get("window_id")
    if command_type == "SPEAK":
        if not isinstance(message, str):
            raise ValueError("발언 내용을 입력해 주세요.")
        body["message"] = normalize_message(message)
    if command_type in {"SUBMIT_NIGHT_ACTION", "SUBMIT_VOTE"}:
        try:
            candidate = str(UUID(str(target_player_id)))
        except (TypeError, ValueError):
            raise ValueError("유효한 대상이 아닙니다.") from None
        body["target_player_id"] = candidate
    if command_type == "SUBMIT_NIGHT_ACTION" and game.get("mode") == "CUSTOM_ROLE":
        if ability_id not in {option["ability_id"] for option in custom_ability_options(snapshot)}:
            raise ValueError("현재 사용할 수 있는 능력을 선택해 주세요.")
        body["ability_id"] = ability_id
    if command_type == "SUBMIT_VOTE" and ability_id is not None:
        if ability_id != "vote.triple.v1" or not can_use_triple_vote(snapshot):
            raise ValueError("현재 사용할 수 있는 투표 능력이 아닙니다.")
        body["ability_id"] = ability_id
    return body


class SpeechQueue:
    """한 사용자의 같은 토론에서 발언 의도를 FIFO로 보내는 비차단 큐다.

    Streamlit runner는 enqueue/observe/advance만 호출한다. 네트워크 스레드는
    이 객체 안의 잠금으로 보호된 값만 사용하며 Streamlit 세션을 참조하지 않는다.
    Future를 잠금 안에서 먼저 공개해 겹친 runner가 같은 head를 두 번 시작하지 않는다.
    """

    def __init__(self, client: Any, snapshot: dict[str, Any], *, clock=monotonic):
        self._lock = RLock()
        self._cancelled = Event()
        self._client = client
        self._clock = clock
        self.user_id = str(client.user_id)
        self._snapshot = self._unpack(snapshot)
        self.game_id = self._snapshot["game"]["game_id"]
        self._scope = self._scope_of(self._snapshot, self.user_id)
        self._cursor = self._cursor_of(self._snapshot)
        self._minimum_version = self._cursor[0]
        self._expires: float | None = None
        self._messages: deque[str] = deque()
        self._future: Future | None = None
        self._attempt: dict[str, Any] | None = None
        self._generation = 0
        self._ever_posted = False
        self._retry_at = 0.0
        self._status = "IDLE"
        self._notice = ""
        self._completed = 0
        self._remember(self._snapshot)
        if not self._open(self._snapshot, allow_waiting=True):
            self.cancel("현재 토론에서 발언을 예약할 수 없습니다.")

    @property
    def scope(self) -> dict[str, Any]:
        """외부의 scope 수정이 큐의 소유권 경계를 바꾸지 않도록 복사본을 준다."""

        with self._lock:
            return deepcopy(self._scope)

    @property
    def busy(self) -> bool:
        """취소된 HTTP가 아직 끝나지 않았다면 자원을 사용 중인 상태로 남긴다."""

        with self._lock:
            return bool(self._messages or self._future is not None and not self._future.done())

    def enqueue(self, message: str) -> None:
        """본문만 예약하며 최신 version·window·멱등 key는 전송 직전에 결정한다."""

        if not isinstance(message, str):
            raise ValueError("발언 내용을 입력해 주세요.")
        normalized = normalize_message(message)
        with self._lock:
            if not self._live():
                raise ValueError("토론이 종료되어 발언을 예약할 수 없습니다.")
            self._messages.append(normalized)
            if self._status in {"IDLE", "REJECTED"}:
                self._status = "WAITING"

    def matches(self, snapshot: dict[str, Any], user_id: Any) -> bool:
        """같은 토론의 UI 관측 지연은 큐를 교체하지 않으며 실제 사용 시 cursor를 검증한다."""

        with self._lock:
            try:
                candidate = self._unpack(snapshot)
                return (not self._cancelled.is_set()
                        and str(self._client.user_id) == self.user_id
                        and self._scope_of(candidate, str(user_id)) == self._scope)
            except (KeyError, TypeError, ValueError):
                return False

    def observe(self, snapshot: dict[str, Any], user_id: Any) -> None:
        """새 범위는 취소하고, 뒤늦은 옛 snapshot은 최신 cursor와 시계를 되돌리지 않는다."""

        with self._lock:
            if self._cancelled.is_set():
                return
            if str(user_id) != self.user_id or str(self._client.user_id) != self.user_id:
                self.cancel("사용자가 바뀌어 미전송 발언 예약을 중단했습니다.")
                return
            try:
                self._adopt(self._unpack(snapshot))
            except (KeyError, TypeError, ValueError):
                self.cancel("게임 상태를 확인할 수 없어 미전송 발언 예약을 중단했습니다.")
            self._live()

    def cancel(self, reason: str) -> None:
        """미전송 의도만 폐기하며 이미 시작한 POST가 서버에서 취소됐다고 주장하지 않는다."""

        with self._lock:
            if self._cancelled.is_set():
                return
            self._cancelled.set()
            self._generation += 1
            self._messages.clear()
            self._status = "CANCELLED"
            self._notice = reason
            if self._ever_posted:
                self._notice += " 이미 보낸 요청은 서버에서 처리되었을 수 있습니다."

    def view(self) -> dict[str, Any]:
        """UI에 원문·상태만 복사하고 내부 Future나 변경 가능한 요청 body는 노출하지 않는다."""

        with self._lock:
            return {"pending": list(self._messages), "status": self._status,
                    "notice": self._notice, "completed": self._completed}

    def advance(self) -> dict[str, Any] | None:
        """완료 Future만 소비하거나 하나를 시작하며 HTTP 완료를 기다리지 않는다."""

        with self._lock:
            if not self._live():
                if self._future is not None and self._future.done():
                    self._future = None
                return None
            if self._future is not None:
                if not self._future.done():
                    return None
                result = self._future.result()
                self._future = None
                return self._consume(result)
            if not self._messages or self._clock() < self._retry_at:
                return None
            future: Future = Future()
            self._future = future
            self._status = "SENDING"
            generation = self._generation
            attempt = deepcopy(self._attempt)
            message = self._messages[0]
            # Future와 head는 네트워크 스레드 시작 전에 하나의 잠금 구간에서 확정한다.
            # 생성된 daemon은 HTTP 한 시도만 맡고 끝나므로 idle 큐에 남는 실행기는 없다.
            thread = Thread(target=self._run, args=(future, generation, attempt, message),
                            name="mafia-speech-request", daemon=True)
            try:
                thread.start()
            except RuntimeError:
                self._future = None
                self._status = "WAITING"
                self._retry_at = self._clock() + 2
                self._notice = "전송을 준비하지 못해 잠시 후 다시 시도합니다."
            return None

    @staticmethod
    def _unpack(value: dict[str, Any]) -> dict[str, Any]:
        """API envelope와 내부 snapshot을 같은 형태로 검증하고 독립 복사한다."""

        if not isinstance(value, dict):
            raise ValueError("INVALID_SNAPSHOT")
        snapshot = value.get("data", value)
        if not isinstance(snapshot, dict):
            raise ValueError("INVALID_SNAPSHOT")
        if any(not isinstance(snapshot.get(key), dict) for key in ("game", "me")):
            raise ValueError("INVALID_SNAPSHOT")
        if snapshot.get("action_window") is not None and not isinstance(snapshot["action_window"], dict):
            raise ValueError("INVALID_WINDOW")
        SpeechQueue._cursor_of(snapshot)
        if not isinstance(snapshot["game"].get("game_id"), str):
            raise ValueError("INVALID_SNAPSHOT")
        return deepcopy(snapshot)

    @staticmethod
    def _cursor_of(snapshot: dict[str, Any]) -> tuple[int, int]:
        """bool·문자열 cursor는 정수로 묵시 변환하지 않는다."""

        game = snapshot["game"]
        version, sequence = game.get("state_version"), game.get("last_sequence")
        if type(version) is not int or version < 1 or type(sequence) is not int or sequence < 0:
            raise ValueError("INVALID_CURSOR")
        return version, sequence

    @staticmethod
    def _scope_of(snapshot: dict[str, Any], user_id: str) -> dict[str, Any]:
        """timed 토론의 AI 예약 window만 제외하고 실제 행동 구간을 모두 고정한다."""

        game, me = snapshot["game"], snapshot["me"]
        window = snapshot.get("action_window") or {}
        if not isinstance(window, dict):
            raise ValueError("INVALID_WINDOW")
        timed = game.get("phase") in {"DAY_DISCUSSION", "FINAL_DISCUSSION"} and window.get("deadline_at") is not None
        return {"user_id": user_id, "game_id": game.get("game_id"),
                "player_id": me.get("player_id"), "alive": me.get("alive"),
                "status": game.get("status"), "phase": game.get("phase"),
                "round": game.get("round"), "day_number": game.get("day_number"),
                "deadline_at": window.get("deadline_at"), "kind": window.get("kind"),
                "window_id": None if timed else window.get("window_id")}

    def _not_older(self, snapshot: dict[str, Any]) -> bool:
        """version과 sequence 중 하나라도 감소한 응답은 사용하지 않는다."""

        return all(new >= old for new, old in zip(self._cursor_of(snapshot), self._cursor))

    def _open(self, snapshot: dict[str, Any], *, allow_waiting: bool = False) -> bool:
        """timed 토론의 일시적인 SPEAK 제한은 예약만 유지하고 실제 전송에는 허용을 요구한다."""

        game, me = snapshot["game"], snapshot["me"]
        window = snapshot.get("action_window") or {}
        return (isinstance(window, dict) and game.get("status") == "IN_PROGRESS"
                and game.get("phase") in {"DAY_DISCUSSION", "FINAL_DISCUSSION"}
                and me.get("alive") is True and bool(me.get("player_id"))
                and window.get("kind") == "SPEECH" and bool(window.get("window_id"))
                and not window.get("paused")
                and (not window.get("has_submitted")
                     or allow_waiting and window.get("deadline_at") is not None)
                and isinstance(snapshot.get("legal_actions"), list)
                and ("SPEAK" in snapshot["legal_actions"]
                     or allow_waiting and window.get("deadline_at") is not None)
                and (window.get("deadline_at") is not None
                     or window.get("turn_player_id") == me.get("player_id")))

    def _remember(self, snapshot: dict[str, Any]) -> None:
        """서버 잔여 시간의 monotonic 상한을 보존해 같은 응답 재관측이 마감을 늘리지 않는다."""

        window = snapshot.get("action_window") or {}
        if window.get("deadline_at") is not None:
            remaining = window.get("remaining_ms")
            if type(remaining) is not int or remaining < 0:
                raise ValueError("INVALID_REMAINING")
            deadline = datetime.fromisoformat(str(window["deadline_at"]).replace("Z", "+00:00"))
            server = datetime.fromisoformat(str(window.get("server_time")).replace("Z", "+00:00"))
            if deadline.tzinfo is None or server.tzinfo is None:
                raise ValueError("INVALID_SERVER_TIME")
            seconds = min(remaining / 1000, max(0, (deadline - server).total_seconds()))
            expires = self._clock() + seconds
            self._expires = expires if self._expires is None else min(self._expires, expires)
        self._snapshot = deepcopy(snapshot)
        self._cursor = self._cursor_of(snapshot)

    def _live(self) -> bool:
        """cancel과 새 POST 시작의 판정을 같은 잠금 경계에서 직렬화한다."""

        if not self._cancelled.is_set() and str(self._client.user_id) != self.user_id:
            self.cancel("사용자가 바뀌어 미전송 발언 예약을 중단했습니다.")
        if not self._cancelled.is_set() and self._expires is not None and self._clock() >= self._expires:
            self.cancel("토론 시간이 끝나 미전송 발언 예약을 중단했습니다.")
        return not self._cancelled.is_set()

    def _adopt(self, snapshot: dict[str, Any]) -> bool:
        """같은 소유자의 최신 상태만 병합하고 새 phase에서는 남은 의도를 취소한다."""

        if (snapshot["game"].get("game_id") != self.game_id
                or snapshot["me"].get("player_id") != self._scope["player_id"]):
            self.cancel("게임 또는 플레이어가 바뀌어 미전송 발언 예약을 중단했습니다.")
            return False
        if not self._not_older(snapshot):
            return False
        same_scope = self._scope_of(snapshot, self.user_id) == self._scope
        if same_scope:
            self._remember(snapshot)
        else:
            self._snapshot = deepcopy(snapshot)
            self._cursor = self._cursor_of(snapshot)
        if not same_scope or not self._open(snapshot, allow_waiting=True):
            self.cancel("토론의 행동 구간이 바뀌어 미전송 발언 예약을 중단했습니다.")
        return True

    def _run(self, future: Future, generation: int, attempt: dict[str, Any] | None,
             message: str) -> None:
        """예상하지 못한 transport 실패도 Future에 기록해 전송 상태가 영구 고착되지 않게 한다."""

        try:
            result = self._request(generation, attempt, message)
        except Exception:
            with self._lock:
                result = {"outcome": "unknown" if self._attempt else "waiting"}
        future.set_result(result)

    def _request(self, generation: int, attempt: dict[str, Any] | None,
                 message: str) -> dict[str, Any]:
        """새 시도는 GET을 선행하고 결과 불명 재확인은 원 body/key만 사용한다."""

        observed = None
        if attempt is None:
            try:
                observed = self._unpack(self._client.get_game(self.game_id))
            except ApiResponseError as error:
                return {"outcome": "cancelled" if error.status_code in {403, 404} else "waiting"}
            except Exception:
                return {"outcome": "waiting"}
        with self._lock:
            if generation != self._generation or not self._live():
                return {"outcome": "cancelled"}
            if observed is not None:
                if (observed["game"].get("game_id") == self.game_id
                        and observed["me"].get("player_id") == self._scope["player_id"]
                        and not self._not_older(observed)):
                    return {"outcome": "waiting"}
                if self._scope_of(observed, self.user_id) != self._scope:
                    return {"outcome": "cancelled", "snapshot": observed}
                if not self._not_older(observed) or self._cursor_of(observed)[0] < self._minimum_version:
                    return {"outcome": "waiting"}
                self._remember(observed)
                if not self._open(observed, allow_waiting=True) or not self._live():
                    return {"outcome": "cancelled", "snapshot": observed}
                if not self._open(observed):
                    return {"outcome": "waiting", "snapshot": observed}
                attempt = {"command": build_command(snapshot=observed, command_type="SPEAK", message=message),
                           "key": str(uuid4())}
                self._attempt = deepcopy(attempt)
            # 이 지점이 POST 시작의 선형화 경계다. cancel이 먼저 잠금을 얻었다면
            # POST는 금지되며, 뒤에 온 cancel은 이미 시작된 요청의 결과를 폐기한다.
            self._ever_posted = True
        assert attempt is not None
        try:
            response = self._client.submit_command(game_id=self.game_id,
                command=deepcopy(attempt["command"]), idempotency_key=attempt["key"])
        except ApiResponseError as error:
            if error.status_code >= 500:
                outcome = "unknown"
            elif error.status_code == 409 and error.code in {"STALE_STATE_VERSION", "WINDOW_CLOSED"}:
                outcome = "refresh"
            elif error.status_code == 429:
                outcome = "waiting"
            elif error.status_code in {401, 403, 404}:
                outcome = "cancelled"
            else:
                outcome = "rejected"
            return {"outcome": outcome, "snapshot": observed}
        except Exception:
            return {"outcome": "unknown", "snapshot": observed}
        if not self._receipt_matches(response, attempt):
            return {"outcome": "unknown", "snapshot": observed}
        result = {"outcome": "success", "version": response["data"]["result_state_version"],
                  "snapshot": observed}
        # receipt 성공을 먼저 확정한 뒤 조회한다. 아래 장애는 성공을 unknown으로
        # 되돌리지 않고 다음 head 또는 정상 sync의 재조회에 맡긴다.
        try:
            with self._lock:
                if generation != self._generation or not self._live():
                    return result
            refreshed = self._unpack(self._client.get_game(self.game_id))
            if self._cursor_of(refreshed)[0] >= result["version"]:
                result["snapshot"] = refreshed
        except Exception:
            pass
        return result

    def _receipt_matches(self, response: Any, attempt: dict[str, Any]) -> bool:
        """다른 요청의 성공이나 불완전한 JSON으로 head를 제거하지 않도록 계약을 대조한다."""

        data = response.get("data") if isinstance(response, dict) else None
        if not isinstance(data, dict):
            return False
        accepted, version = data.get("accepted_state_version"), data.get("result_state_version")
        return (data.get("command_id") == attempt["key"] and data.get("command_type") == "SPEAK"
                and type(accepted) is int and accepted == attempt["command"]["expected_state_version"]
                and type(version) is int and version > accepted
                and data.get("sync_url") == f"/api/v1/games/{self.game_id}/sync")

    def _consume(self, result: dict[str, Any]) -> dict[str, Any] | None:
        """완료된 한 시도만 FIFO에 반영하고 다음 시도는 다음 poll에서 시작한다."""

        outcome = result["outcome"]
        candidate = result.get("snapshot")
        delivered = None
        if outcome == "success":
            # 성공 후 조회가 다음 phase를 반환해도 이미 확인한 성공 수는 남긴다.
            # 외부 cancel의 늦은 Future는 advance에서 폐기하므로 이 경로에 오지 않는다.
            self._messages.popleft()
            self._attempt = None
            self._completed += 1
            self._minimum_version = max(self._minimum_version, result["version"])
        if candidate is not None:
            try:
                if self._adopt(candidate):
                    delivered = deepcopy(self._snapshot)
                elif not self._cancelled.is_set():
                    delivered = deepcopy(self._snapshot)
            except (KeyError, TypeError, ValueError):
                candidate = None
        if self._cancelled.is_set():
            return delivered
        if outcome == "success":
            self._status = "WAITING" if self._messages else "IDLE"
            self._notice = "발언을 제출했습니다."
        elif outcome == "cancelled":
            self.cancel("현재 토론에서 미전송 발언 예약을 중단했습니다.")
        elif outcome == "rejected":
            self._messages.popleft()
            self._attempt = None
            self._status = "REJECTED"
            self._notice = "서버가 발언을 거부해 해당 예약을 제거했습니다."
        else:
            self._status = "UNKNOWN" if outcome == "unknown" else "WAITING"
            if outcome != "unknown":
                self._attempt = None
            self._retry_at = self._clock() + (0 if outcome == "refresh" else 2)
            self._notice = ("이미 보낸 발언의 처리 결과를 같은 요청으로 확인하고 있습니다."
                            if outcome == "unknown" else "최신 상태와 발언 가능 시간을 기다리고 있습니다.")
        return delivered
