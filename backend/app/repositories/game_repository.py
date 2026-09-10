"""게임 seed 보호와 PostgreSQL 게임 상태 저장을 담당하는 모듈."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

if TYPE_CHECKING:
    from backend.app.core.config import Settings
    from backend.app.models.game_state import GameState


KEYRING_MAX_BYTES = 64 * 1024
AES_256_KEY_BYTES = 32
AES_GCM_NONCE_BYTES = 12


@dataclass(frozen=True, slots=True, repr=False)
class EncryptedGameSeed:
    """DB의 세 seed 컬럼에 그대로 저장할 암호화 결과."""

    ciphertext: bytes
    nonce: bytes
    key_id: str


class GameStateKeyring:
    """저장소 밖 keyring을 읽어 게임 seed를 AES-256-GCM으로 보호한다.

    키 원문은 객체 외부로 반환하지 않는다. DB에는 암호문, 매번 새로 만든 nonce,
    복호화에 사용할 key ID만 저장한다. 설정이나 keyring이 잘못되면 평문 저장으로
    넘어가지 않고 게임 쓰기 자체를 거부한다.
    """

    __slots__ = ("_active_key_id", "_keys")

    def __init__(self, *, active_key_id: str, keys: Mapping[str, bytes]) -> None:
        self._active_key_id = active_key_id
        self._keys = dict(keys)

    @classmethod
    def legacy_plaintext(cls) -> GameStateKeyring:
        """신규 MVP 게임에 사용할 legacy seed adapter를 만든다.

        현재 DB의 필수 `seed_ciphertext`, `seed_nonce`, `seed_key_id` 컬럼은
        migration 호환을 위해 그대로 채워야 한다. 신규 MVP에서는 별도 keyring을
        요구하지 않으므로 이 adapter가 seed 원문을 ciphertext 위치에 저장하고,
        기존 암호화 행은 설정된 keyring을 사용할 때만 복호화한다.
        """

        return cls(active_key_id="legacy-plaintext", keys={})

    @classmethod
    def from_settings(cls, settings: Settings) -> GameStateKeyring:
        """검증된 설정이 가리키는 JSON keyring을 안전하게 불러온다."""

        keyring_file = settings.game_state_keyring_file
        active_key_id = settings.game_state_active_key_id
        if not keyring_file or not active_key_id:
            raise RuntimeError("Game state encryption is not configured")

        path = Path(keyring_file)
        try:
            if not path.is_file() or path.stat().st_size > KEYRING_MAX_BYTES:
                raise RuntimeError("Game state keyring is unavailable")
            # POSIX에서는 다른 사용자에게 읽기 권한이 열려 있는 파일을 거부한다.
            # Windows ACL은 mode bit만으로 판별할 수 없어 배포 환경에서 제한한다.
            if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) & 0o077:
                raise RuntimeError("Game state keyring permissions are not restricted")
            raw_document = path.read_text(encoding="utf-8")
        except RuntimeError:
            raise
        except (OSError, UnicodeError) as exc:
            # 경로나 파일 내용은 운영 로그에 노출하지 않고 고정 메시지만 남긴다.
            raise RuntimeError("Game state keyring is unavailable") from exc

        keys = _parse_keyring(raw_document)
        if active_key_id not in keys:
            raise RuntimeError("Active game state key is unavailable")
        return cls(active_key_id=active_key_id, keys=keys)

    def encrypt_seed(self, seed: bytes) -> EncryptedGameSeed:
        """게임 seed를 현재 active key와 매번 새로운 nonce로 암호화한다."""

        if not isinstance(seed, bytes) or not seed:
            raise ValueError("Game seed must be non-empty bytes")
        if not self._keys:
            return EncryptedGameSeed(
                ciphertext=seed,
                nonce=b"legacy-mvp",
                key_id=self._active_key_id,
            )
        nonce = os.urandom(AES_GCM_NONCE_BYTES)
        ciphertext = AESGCM(self._keys[self._active_key_id]).encrypt(nonce, seed, None)
        return EncryptedGameSeed(
            ciphertext=ciphertext,
            nonce=nonce,
            key_id=self._active_key_id,
        )

    def decrypt_seed(self, *, ciphertext: bytes, nonce: bytes, key_id: str) -> bytes:
        """DB의 key ID로 기존 seed를 복호화하며 위변조는 즉시 거부한다."""

        if not self._keys and key_id == self._active_key_id and nonce == b"legacy-mvp":
            if not ciphertext:
                raise RuntimeError("Legacy game seed is empty")
            return ciphertext
        key = self._keys.get(key_id)
        if key is None:
            raise RuntimeError("Game state decryption key is unavailable")
        if not ciphertext or len(nonce) != AES_GCM_NONCE_BYTES:
            raise RuntimeError("Encrypted game state is invalid")
        try:
            return AESGCM(key).decrypt(nonce, ciphertext, None)
        except (InvalidTag, ValueError) as exc:
            # 실패 시 새 seed를 뽑거나 게임을 이어가면 결과가 달라지므로 거부한다.
            raise RuntimeError("Encrypted game state authentication failed") from exc


def _parse_keyring(raw_document: str) -> dict[str, bytes]:
    """정본 JSON 구조와 모든 AES-256 key 길이를 한 번에 검증한다."""

    try:
        document = json.loads(raw_document)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Game state keyring is malformed") from exc
    if not isinstance(document, dict) or set(document) != {"version", "keys"}:
        raise RuntimeError("Game state keyring is malformed")
    if document["version"] != 1 or not isinstance(document["keys"], dict):
        raise RuntimeError("Game state keyring is malformed")
    if not document["keys"]:
        raise RuntimeError("Game state keyring contains no keys")

    decoded_keys: dict[str, bytes] = {}
    for key_id, encoded_key in document["keys"].items():
        if not isinstance(key_id, str) or not key_id.strip() or len(key_id) > 64:
            raise RuntimeError("Game state keyring contains an invalid key ID")
        if key_id != key_id.strip() or not isinstance(encoded_key, str):
            raise RuntimeError("Game state keyring contains an invalid key")
        # 일반 Base64의 '+'와 '/'는 받지 않고 정본이 지정한 Base64URL 문자만
        # 허용한다. '=' padding은 문자열 끝에 최대 두 개만 올 수 있다.
        if re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", encoded_key) is None:
            raise RuntimeError("Game state keyring contains an invalid key")
        try:
            padding = "=" * (-len(encoded_key) % 4)
            decoded = base64.b64decode(
                encoded_key + padding,
                altchars=b"-_",
                validate=True,
            )
        except (binascii.Error, ValueError) as exc:
            raise RuntimeError("Game state keyring contains an invalid key") from exc
        if len(decoded) != AES_256_KEY_BYTES:
            raise RuntimeError("Game state keyring contains an invalid key")
        decoded_keys[key_id] = decoded
    return decoded_keys


GAME_COLUMNS = """
    id, owner_user_id, status, phase, round, day_number, state_version,
    next_event_sequence, next_front_sequence, player_count, mafia_count,
    ruleset_version, scenario_version, scenario_id, scenario_content_hash,
    seed_ciphertext, seed_nonce, seed_key_id, agent_config_version,
    fast_forward_enabled, mode, winner, win_reason, saved_at, finished_at,
    created_at, updated_at
"""
# scenario_catalog과 join할 때 id 같은 공통 컬럼이 모호해지지 않도록 games alias를
# 모든 고정 컬럼에 붙인 목록이다. 외부 입력을 조합하지 않는다.
GAME_COLUMNS_QUALIFIED = ", ".join(
    f"games.{column.strip()}" for column in GAME_COLUMNS.split(",")
)


class PostgresGameRepository:
    """게임별 PostgreSQL row lock과 sequence 발급을 담당한다."""

    def insert_initial_game(
        self,
        cursor: Any,
        *,
        state: GameState,
        owner_user_id: UUID,
        scenario_version: str,
        scenario_id: str,
        scenario_content_hash: str,
        encrypted_seed: EncryptedGameSeed,
        agent_config_version: str = "agent-config-v1",
    ) -> Mapping[str, Any]:
        """역할 배정이 끝난 최초 ROLE_REVEAL 게임 행을 저장한다.

        이 메서드는 연결을 직접 열지 않는다. 호출 서비스가 users, players, facts,
        event, receipt와 함께 하나의 transaction으로 묶을 수 있도록 같은 cursor를
        전달받는다.
        """

        if (
            state.status.value != "IN_PROGRESS"
            or state.phase.value != "ROLE_REVEAL"
            or state.round != 0
            or state.day_number != 1
            or state.state_version != 1
        ):
            raise ValueError("Initial game state is invalid")
        if not 6 <= len(state.players) <= 9:
            raise ValueError("Initial game player count is invalid")
        if len(scenario_content_hash) != 64 or any(
            character not in "0123456789abcdef" for character in scenario_content_hash
        ):
            raise ValueError("Scenario content hash is invalid")

        mafia_count = sum(player.faction.value == "MAFIA" for player in state.players)
        cursor.execute(
            """
            INSERT INTO public.games (
                id, owner_user_id, status, phase, round, day_number,
                state_version, next_event_sequence, next_front_sequence,
                player_count, mafia_count, ruleset_version, scenario_version,
                scenario_id, scenario_content_hash, seed_ciphertext, seed_nonce,
                seed_key_id, agent_config_version, fast_forward_enabled,
                mode, winner, win_reason, saved_at, finished_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, 1, 1,
                %s, %s, 'mystery-v1', %s,
                %s, %s, %s, %s,
                %s, %s, FALSE,
                %s, NULL, NULL, NULL, NULL
            )
            RETURNING id, owner_user_id, status, phase, round, day_number,
                      state_version, player_count, mafia_count, scenario_id
            """,
            (
                state.game_id,
                owner_user_id,
                state.status.value,
                state.phase.value,
                state.round,
                state.day_number,
                state.state_version,
                len(state.players),
                mafia_count,
                scenario_version,
                scenario_id,
                scenario_content_hash,
                encrypted_seed.ciphertext,
                encrypted_seed.nonce,
                encrypted_seed.key_id,
                agent_config_version,
                state.mode,
            ),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("게임 생성 결과가 반환되지 않았습니다.")
        return row

    def lock_game(self, cursor: Any, game_id: UUID) -> Mapping[str, Any] | None:
        """동시 command가 같은 게임 상태를 동시에 읽지 못하도록 행을 잠근다."""

        # GAME_COLUMNS는 사용자 입력이 아닌 이 모듈의 고정 상수다. game_id는 아래
        # bound parameter로 전달하므로 문자열 조합을 통한 SQL 주입 경로가 없다.
        cursor.execute(
            f"""
            SELECT {GAME_COLUMNS}
            FROM public.games
            WHERE id = %s
            FOR UPDATE
            """,  # noqa: S608
            (game_id,),
        )
        return cursor.fetchone()

    def list_owned_games(
        self,
        cursor: Any,
        *,
        owner_user_id: UUID,
        status: str | None,
        limit: int,
    ) -> list[Mapping[str, Any]]:
        """소유자 목록에 필요한 공개 게임 요약만 최신순으로 읽는다."""

        cursor.execute(
            """
            SELECT g.id, g.status, g.phase, g.round, g.day_number,
                   g.state_version, g.player_count, g.winner, g.updated_at,
                   s.title AS scenario_title,
                   human.alive AS human_alive
            FROM public.games AS g
            JOIN public.scenario_catalog AS s
              ON s.id = g.scenario_id AND s.version = g.scenario_version
            JOIN public.game_players AS human
              ON human.game_id = g.id AND human.kind = 'HUMAN'
            WHERE g.owner_user_id = %s
              AND (%s::varchar IS NULL OR g.status = %s::varchar)
            ORDER BY g.updated_at DESC, g.id DESC
            LIMIT %s
            """,
            (owner_user_id, status, status, limit),
        )
        return list(cursor.fetchall())

    def get_owned_game(
        self,
        cursor: Any,
        *,
        owner_user_id: UUID,
        game_id: UUID,
    ) -> Mapping[str, Any] | None:
        """소유자 확인을 SQL 조건에 포함해 타인 게임 존재를 숨긴다."""

        # GAME_COLUMNS는 이 모듈의 고정 상수이며 두 UUID는 bound parameter다.
        cursor.execute(
            f"""
            SELECT {GAME_COLUMNS_QUALIFIED},
                   scenario.title AS scenario_title,
                   scenario.background AS scenario_background,
                   scenario.victim AS scenario_victim,
                   scenario.locations AS scenario_locations
            FROM public.games
            JOIN public.scenario_catalog AS scenario
              ON scenario.id = games.scenario_id
             AND scenario.version = games.scenario_version
            WHERE games.id = %s AND games.owner_user_id = %s
            """,  # noqa: S608
            (game_id, owner_user_id),
        )
        return cursor.fetchone()

    def update_game_state(
        self,
        cursor: Any,
        *,
        state: GameState,
        expected_state_version: int,
        user_action: bool = False,
    ) -> Mapping[str, Any]:
        """상태 version과 검증된 사용자 동작 시각을 같은 transaction에 저장한다.

        AI·AUTO 처리도 같은 상태 저장 메서드를 사용하므로 호출자가 명시한 인간
        command만 보존 시각을 갱신한다. 기본값은 false로 두어 새 내부 경로가 사용자
        활동을 잘못 연장하지 않게 한다.
        """

        if state.state_version != expected_state_version + 1:
            raise ValueError("Game state version must increase by exactly one")
        if type(user_action) is not bool:
            raise TypeError("user_action은 bool이어야 합니다.")
        if type(state.fast_forward_enabled) is not bool or (state.fast_forward_enabled and state.human_alive):
            raise ValueError("빠른 진행 선택은 사망한 인간에게만 허용됩니다.")
        cursor.execute(
            """
            UPDATE public.games
            SET status = %s, phase = %s, round = %s, day_number = %s,
                state_version = %s, fast_forward_enabled = %s, winner = %s,
                win_reason = %s, saved_at = %s, finished_at = %s,
                updated_at = CURRENT_TIMESTAMP,
                last_user_action_at = CASE
                    WHEN %s THEN CURRENT_TIMESTAMP
                    ELSE last_user_action_at
                END
            WHERE id = %s AND state_version = %s
            RETURNING id, status, phase, round, day_number, state_version,
                      fast_forward_enabled, winner, win_reason, updated_at
            """,
            (
                state.status.value,
                state.phase.value,
                state.round,
                state.day_number,
                state.state_version,
                state.fast_forward_enabled,
                state.winner.value if state.winner else None,
                state.win_reason.value if state.win_reason else None,
                state.updated_at if state.status.value == "SAVED" else None,
                state.updated_at if state.status.value == "COMPLETED" else None,
                user_action,
                state.game_id,
                expected_state_version,
            ),
        )
        row = cursor.fetchone()
        if row is None:
            raise LookupError("게임 상태가 이미 변경되었습니다.")
        return row

    def delete_owned_game(
        self, cursor: Any, *, game_id: UUID, owner_user_id: UUID, expected_state_version: int,
    ) -> None:
        """소유권·버전을 확인하고 잠근 게임만 삭제하며 다른 상태의 기록은 보존한다."""

        cursor.execute(
            """
            DELETE FROM public.games
            WHERE id = %s AND owner_user_id = %s AND state_version = %s
              AND status IN ('IN_PROGRESS', 'SAVED')
            RETURNING id
            """,
            (game_id, owner_user_id, expected_state_version),
        )
        if cursor.fetchone() is None:
            raise LookupError("삭제 대상 게임 상태가 변경되었습니다.")

    def delete_stale_in_progress(
        self,
        cursor: Any,
        *,
        limit: int = 100,
    ) -> list[UUID]:
        """15분간 사용자 command가 없던 진행 게임을 잠긴 소량만 삭제한다.

        후보를 먼저 잠그고 현재 행을 다시 확인하므로 다른 Backend instance와 중복
        처리하지 않는다. 사용자 command가 행 잠금을 먼저 얻으면 이번 sweep은 그
        게임을 건너뛰고 다음 주기에 갱신된 시각을 다시 판정한다.
        """

        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("정리 batch 크기는 1~100이어야 합니다.")
        cursor.execute(
            """
            WITH stale_games AS (
                SELECT id
                FROM public.games
                WHERE status = 'IN_PROGRESS'
                  AND last_user_action_at <= CURRENT_TIMESTAMP - INTERVAL '15 minutes'
                ORDER BY last_user_action_at, id
                LIMIT %s
                FOR UPDATE SKIP LOCKED
            ), deleted_games AS (
                DELETE FROM public.games AS game
                USING stale_games AS stale
                WHERE game.id = stale.id
                  AND game.status = 'IN_PROGRESS'
                  AND game.last_user_action_at <= CURRENT_TIMESTAMP - INTERVAL '15 minutes'
                RETURNING game.id
            )
            SELECT id
            FROM deleted_games
            ORDER BY id
            """,
            (limit,),
        )
        return [UUID(str(row["id"])) for row in cursor.fetchall()]

    def next_event_sequence(self, cursor: Any, game_id: UUID) -> int:
        """게임의 다음 내부 event sequence를 원자적으로 예약한다."""

        cursor.execute(
            """
            UPDATE public.games
            SET next_event_sequence = next_event_sequence + 1
            WHERE id = %s
            RETURNING next_event_sequence - 1 AS sequence
            """,
            (game_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise LookupError("게임을 찾을 수 없습니다.")
        return int(row["sequence"])

    def next_front_sequence(self, cursor: Any, game_id: UUID) -> int:
        """client-visible transaction 하나의 Front batch 번호를 예약한다."""

        cursor.execute(
            """
            UPDATE public.games
            SET next_front_sequence = next_front_sequence + 1
            WHERE id = %s
            RETURNING next_front_sequence - 1 AS front_sequence
            """,
            (game_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise LookupError("게임을 찾을 수 없습니다.")
        return int(row["front_sequence"])
