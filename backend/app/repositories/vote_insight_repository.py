"""투표 보조 조회에 필요한 공개 필드만 일관된 읽기 transaction으로 가져온다."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

from psycopg import IsolationLevel
from psycopg.rows import dict_row

from backend.app.core.errors import ApiError
from backend.app.game_engine.rules.vote_rules import valid_targets
from backend.app.models.enums import GamePhase

DISCUSSION_PHASES = {"DAY_DISCUSSION", "FINAL_DISCUSSION"}


def stale_window() -> ApiError:
    """현재 토론·투표 창을 잃은 요청에 비밀값 없는 고정 오류를 사용한다."""
    return ApiError(status_code=409, code="VOTE_INSIGHTS_STALE_WINDOW",
                    message="현재 진행 중인 토론·투표 창에서만 보조 정보를 조회할 수 있습니다.")


def validate_game_source(source, owner_user_id, game_id, window_id, now):
    """주입된 저장소도 신뢰하지 않고 소유권과 공개 후보 경계를 다시 검사한다.

    후보 규칙은 역할과 무관하므로 공개 필드로 구성한 view에 서버 공통 함수를 적용한다.
    private 역할·seed·개별 표를 읽거나 가짜 역할을 생성할 필요가 없다.
    """
    game, window = source.get("game"), source.get("window")
    if (not game or str(game["id"]) != str(game_id)
            or str(game["owner_user_id"]) != str(owner_user_id)):
        raise ApiError(status_code=404, code="GAME_NOT_FOUND", message="게임을 찾을 수 없습니다.")
    discussion = game["phase"] in DISCUSSION_PHASES
    kinds = {"DAY_VOTE": "VOTE", "REVOTE": "REVOTE", "FINAL_ACCUSATION": "FINAL_VOTE",
             "DAY_DISCUSSION": "SPEECH", "FINAL_DISCUSSION": "SPEECH"}
    if (game["status"] != "IN_PROGRESS" or game["phase"] not in kinds or not window
            or str(window["id"]) != str(window_id) or str(window["game_id"]) != str(game_id)
            or window["status"] != "OPEN" or window["phase"] != game["phase"]
            or window["round"] != game["round"] or window["window_kind"] != kinds[game["phase"]]):
        raise stale_window()
    deadline = window["deadline_at"]
    # 구형 순차 토론에는 deadline이 없고 마감된 자유 토론은 분석 준비 상태일 수 있다.
    # 투표의 유효 시간 검사는 그대로 유지하며 읽기 허용이 제출 권한을 늘리지 않는다.
    if (deadline is not None and (not isinstance(deadline, datetime) or deadline.utcoffset() is None)
            or not discussion and (deadline is None or deadline <= now)):
        raise stale_window()
    players = source["players"]
    if (not 2 <= len(players) <= 9 or len({str(p["id"]) for p in players}) != len(players)
            or any(str(p["game_id"]) != str(game_id) for p in players)):
        raise ValueError("공개 참가자 소속이 올바르지 않습니다.")
    humans = [p for p in players if p["kind"] == "HUMAN"]
    if (len(humans) != 1 or str(humans[0]["user_id"]) != str(owner_user_id)
            or not discussion and humans[0]["alive"] is not True):
        raise stale_window()
    if discussion:
        return []
    views = [SimpleNamespace(player_id=UUID(str(p["id"])), seat=p["seat"])
             for p in players if p["alive"] is True]
    tied = set()
    if game["phase"] == "REVOTE":
        resolution = source.get("revote")
        if not resolution or resolution["needs_revote"] is not True:
            raise ValueError("확정 재투표 후보가 없습니다.")
        counts = resolution["counts"]
        known = {str(p["id"]) for p in players}
        if (not isinstance(counts, list) or not counts
                or any(c["target_player_id"] not in known or type(c["vote_count"]) is not int
                       or c["vote_count"] < 0 for c in counts)
                or len({c["target_player_id"] for c in counts}) != len(counts)):
            raise ValueError("확정 투표 집계가 올바르지 않습니다.")
        maximum = max(c["vote_count"] for c in counts)
        leaders = {c["target_player_id"] for c in counts if c["vote_count"] == maximum}
        if (maximum < 1 or len(leaders) < 2
                or set(resolution["tied_candidates"]) != leaders
                or len(resolution["tied_candidates"]) != len(leaders)):
            raise ValueError("확정 동률 후보가 집계와 다릅니다.")
        tied = {UUID(p) for p in leaders}
    state = SimpleNamespace(alive_players=views, phase=GamePhase(game["phase"]), revote_candidates=tied)
    actor = SimpleNamespace(player_id=UUID(str(humans[0]["id"])))
    return [str(p.player_id) for p in sorted(valid_targets(state, actor), key=lambda p: p.seat)]


class PostgresVoteInsightRepository:
    """원본 발언을 LEFT JOIN의 기준으로 삼아 분석 탐색 지연도 coverage에 포함한다."""

    def __init__(self, transactions):
        self._transactions = transactions

    def load(self, *, owner_user_id, game_id, window_id, scope, settings):
        """검증과 cutoff·원문·분석 조회를 한 snapshot에 묶고 DB 쓰기는 하지 않는다."""
        with self._transactions.transaction() as connection:
            connection.isolation_level = IsolationLevel.REPEATABLE_READ
            connection.read_only = True
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute("""
                    SELECT id, owner_user_id, status, phase, round FROM public.games
                    WHERE id = %s AND owner_user_id = %s
                """, (game_id, owner_user_id))
                game = cursor.fetchone()
                if game is None:
                    raise ApiError(status_code=404, code="GAME_NOT_FOUND", message="게임을 찾을 수 없습니다.")
                cursor.execute("""
                    SELECT id, game_id, status, phase, round, window_kind, deadline_at
                    FROM public.action_windows WHERE game_id = %s
                      AND status IN ('OPEN', 'PAUSED', 'RESOLVING')
                """, (game_id,))
                window = cursor.fetchone()
                cursor.execute("""
                    SELECT id, game_id, user_id, kind, alive, seat, display_name
                    FROM public.game_players WHERE game_id = %s ORDER BY seat
                """, (game_id,))
                source = {"game": game, "window": window, "players": cursor.fetchall(),
                          "speeches": [], "revote": None}
                if game["phase"] == "REVOTE":
                    cursor.execute("""
                        SELECT result_payload->'counts' AS counts,
                               result_payload->'tied_candidates' AS tied_candidates,
                               result_payload->'needs_revote' AS needs_revote
                        FROM public.action_window_resolutions r
                        JOIN public.action_windows w ON w.game_id=r.game_id AND w.id=r.window_id
                        WHERE r.game_id=%s AND w.phase='DAY_VOTE' AND w.round=%s
                          AND r.resolution_type='VOTE'
                        ORDER BY r.resolved_state_version DESC LIMIT 1
                    """, (game_id, game["round"]))
                    source["revote"] = cursor.fetchone()
                validate_game_source(source, owner_user_id, game_id, window_id, datetime.now(UTC))
                if game["phase"] in DISCUSSION_PHASES:
                    # private 이벤트만 추가된 경우 공개 cutoff나 revision은 변하지 않는다.
                    cursor.execute("""
                        SELECT coalesce(max(sequence), 0) + 1 AS cutoff_sequence
                        FROM public.game_events WHERE game_id=%s
                          AND audience='PUBLIC' AND audience_player_id IS NULL AND schema_version=1
                    """, (game_id,))
                    source["cutoff_sequence"] = cursor.fetchone()["cutoff_sequence"]
                    source["discussion_segment"] = f"{window['phase']}:{window['round']}"
                else:
                    cursor.execute("""
                        SELECT min(sequence) AS cutoff_sequence FROM public.game_events
                        WHERE game_id=%s AND audience='PUBLIC' AND audience_player_id IS NULL
                          AND schema_version=1 AND operation_type='SET_ACTION_WINDOW' AND payload->>'window_id'=%s
                    """, (game_id, str(window_id)))
                    source["cutoff_sequence"] = cursor.fetchone()["cutoff_sequence"]
                    if type(source["cutoff_sequence"]) is not int:
                        raise ValueError("투표 창 최초 개설 원장이 없습니다.")
                    cursor.execute("""
                        SELECT w.phase || ':' || w.round::text AS discussion_segment
                        FROM public.game_events e JOIN public.action_windows w
                          ON w.game_id=e.game_id AND w.id::text=e.payload->>'window_id'
                        WHERE e.game_id=%s AND e.sequence<%s AND e.audience='PUBLIC'
                          AND e.audience_player_id IS NULL AND e.schema_version=1
                          AND e.operation_type='SET_ACTION_WINDOW' AND w.window_kind='SPEECH'
                          AND w.phase IN ('DAY_DISCUSSION','FINAL_DISCUSSION')
                        ORDER BY e.sequence DESC LIMIT 1
                    """, (game_id, source["cutoff_sequence"]))
                    segment = cursor.fetchone()
                    source["discussion_segment"] = segment["discussion_segment"] if segment else None
                if not settings.speech_analysis_enabled:
                    return source
                cursor.execute("""
                    SELECT e.id AS event_id, e.game_id, e.audience, e.audience_player_id,
                           e.operation_type, e.event_type, e.schema_version, e.created_at,
                           e.sequence, e.payload->>'player_id' AS player_id,
                           e.payload->>'message' AS message,
                           w.phase || ':' || w.round::text AS discussion_segment,
                           w.round AS source_round,
                           a.event_id AS analysis_event_id, a.game_id AS analysis_game_id,
                           a.player_id AS analysis_player_id, a.source_sequence,
                           a.discussion_segment AS analysis_segment, a.round AS analysis_round,
                           a.content_hash, a.analysis_version, a.embedding_model, a.dimensions,
                           a.claims_model, a.embedding_status, a.claims_status, a.embedding, a.claims
                    FROM public.game_events e
                    JOIN public.game_players p ON p.game_id=e.game_id
                      AND p.id::text=e.payload->>'player_id' AND p.kind IN ('HUMAN','AI')
                    JOIN LATERAL (
                        SELECT se.payload FROM public.game_events se WHERE se.game_id=e.game_id
                          AND se.sequence<e.sequence AND se.audience='PUBLIC'
                          AND se.audience_player_id IS NULL AND se.schema_version=1
                          AND se.operation_type='SET_ACTION_WINDOW'
                        ORDER BY se.sequence DESC LIMIT 1
                    ) opening ON true
                    JOIN public.action_windows w ON w.game_id=e.game_id
                      AND w.id::text=opening.payload->>'window_id' AND w.window_kind='SPEECH'
                    LEFT JOIN public.speech_analysis a ON a.game_id=e.game_id AND a.event_id=e.id
                      AND a.analysis_version=%s
                    WHERE e.game_id=%s AND e.sequence<%s AND e.audience='PUBLIC'
                      AND e.audience_player_id IS NULL AND e.operation_type='APPEND_PUBLIC_EVENT'
                      AND e.event_type='PLAYER_SPOKE' AND e.schema_version=1
                      AND jsonb_typeof(e.payload->'message')='string'
                      AND btrim(e.payload->>'message')<>''
                      AND w.phase IN ('DAY_DISCUSSION','FINAL_DISCUSSION')
                      AND (%s='game' OR w.phase || ':' || w.round::text=%s)
                    ORDER BY e.sequence
                """, (settings.effective_speech_analysis_version, game_id,
                      source["cutoff_sequence"], scope, source["discussion_segment"]))
                source["speeches"] = cursor.fetchall()
                return source
