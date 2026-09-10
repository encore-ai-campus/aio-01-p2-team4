"""관리자 read-only 조회와 ``admin_audit_events`` 기록 저장소.

관리자 저장소가 반환하는 게임 데이터는 공개 진행 정보만 포함한다. 역할,
개인 사실, 개별 행동·투표, seed와 Agent private context는 SQL 조회 단계에서
아예 선택하지 않는다. 테스트에서는 같은 계약의 메모리 저장소를 주입할 수 있고,
운영에서는 PostgreSQL 저장소로 바꿔 쓸 수 있다.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

_SPEECH_SAMPLE_LIMIT = 500
_SPEECH_EMBEDDING_PROJECTION = 96
_SPEECH_SIMILARITY_THRESHOLD = 0.78
_SPEECH_TOKEN_RE = re.compile(r"[가-힣A-Za-z][가-힣A-Za-z0-9_]{1,}")
# 조사·접속사·게임 화면 공통 단어는 주제 라벨을 흐리므로 화면 집계에서만 제외한다.
_SPEECH_STOPWORDS = frozenset({
    "그리고", "그래서", "그러나", "그런데", "때문", "대한", "대해", "있는", "있어",
    "있습니다", "같은", "것이", "것은", "제가", "나는", "우리", "정말", "이번", "지금",
    "그냥", "아마", "모두", "이제", "하면", "해야", "합니다", "입니다", "같아요", "같습니다",
    "수상한", "사람", "플레이어", "발언", "생각", "느낌", "확인", "보입니다", "보면",
})
_SPEECH_STANCES = ("SUSPICION", "DEFENSE", "QUESTION", "NEUTRAL")
_SPEECH_PARTICLE_SUFFIXES = (
    "으로", "에서", "까지", "부터", "에게", "한테", "처럼", "보다",
    "을", "를", "이", "가", "은", "는", "의", "에", "로", "와", "과", "도", "만",
)
_SPEECH_ENDING_SUFFIXES = ("합니다", "입니다", "됩니다", "했어요", "해요")


class AdminRepository(Protocol):
    """관리자 서비스가 필요한 조회·감사 기록 계약."""

    def list_games(
        self,
        *,
        status: str | None,
        phase: str | None,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], str | None]: ...

    def get_game(self, game_id: UUID) -> dict[str, Any] | None: ...

    def metrics(
        self,
        *,
        from_time: datetime | None,
        to_time: datetime | None,
    ) -> dict[str, Any]: ...

    def append_audit(
        self,
        *,
        admin_user_id: UUID,
        action: str,
        target_game_id: UUID | None,
        request_id: UUID,
    ) -> None: ...

    def role_win_rates(self, *, from_time: datetime | None,
                       to_time: datetime | None) -> list[dict[str, Any]]: ...

    def persona_win_rates(self, *, from_time: datetime | None,
                          to_time: datetime | None) -> list[dict[str, Any]]: ...

    def speech_analytics(
        self,
        *,
        from_time: datetime | None,
        to_time: datetime | None,
        game_id: UUID | None,
        persona_id: str | None,
        round_number: int | None,
        analysis_version: str | None,
        topic_limit: int,
    ) -> dict[str, Any]: ...

    def list_feedback(self, *, feedback_type: str | None, rating: int | None,
                      cursor: UUID | None, limit: int) -> tuple[list[dict], str | None]: ...

    def list_audit_logs(self, *, event_type: str | None, cursor: int | None,
                        limit: int) -> tuple[list[dict], str | None]: ...

    def list_agent_jobs(
        self, *, game_id: UUID | None, job_kind: str | None, status: str | None,
        cursor: UUID | None, limit: int,
    ) -> tuple[list[dict], str | None]: ...

    def search_knowledge(
        self,
        *,
        question: str,
        source_types: list[str],
        rating_lte: int | None,
        from_time: datetime | None,
        to_time: datetime | None,
        top_k: int,
    ) -> list[dict[str, Any]]: ...


def _iso(value: Any) -> str | None:
    """datetime을 API용 UTC 문자열로 바꾸고 나머지는 안전하게 비운다."""

    if value is None:
        return None
    if isinstance(value, datetime):
        normalized = value if value.tzinfo else value.replace(tzinfo=UTC)
        return normalized.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return str(value)


def _window_kind(phase: str, status: str) -> str | None:
    """DB phase를 관리자에게 보여줄 현재 action window 종류로 변환한다."""

    if status != "IN_PROGRESS":
        return None
    return {
        "DAY_DISCUSSION": "SPEECH",
        "NIGHT_ACTION": "NIGHT",
        "DAY_VOTE": "VOTE",
        "REVOTE": "REVOTE",
        "FINAL_ACCUSATION": "FINAL_VOTE",
    }.get(phase)


def _speech_tokens(message: str) -> list[str]:
    """공개 문장을 화면용 키워드로 정규화한다.

    형태소 분석기를 관리자 조회 경로에 추가하지 않고도 재현 가능한 결과를
    만들기 위해 한글·영문·숫자 토큰만 사용한다. 두 글자 미만과 공통 조사·
    연결어는 제외하지만 원문 자체는 근거 응답에서 변경하지 않는다.
    """

    normalized = unicodedata.normalize("NFC", str(message or "")).casefold()
    tokens: list[str] = []
    for token in _SPEECH_TOKEN_RE.findall(normalized):
        if token in _SPEECH_STOPWORDS:
            continue
        for suffix in _SPEECH_ENDING_SUFFIXES:
            if token.endswith(suffix) and len(token) - len(suffix) >= 2:
                token = token[:-len(suffix)]
                break
        for suffix in _SPEECH_PARTICLE_SUFFIXES:
            if token.endswith(suffix) and len(token) - len(suffix) >= 2:
                token = token[:-len(suffix)]
                break
        if len(token) >= 2 and token not in _SPEECH_STOPWORDS:
            tokens.append(token)
    return tokens


def _speech_cosine(left: Any, right: Any) -> float:
    """차원이 같은 유한 벡터의 cosine 유사도를 계산한다."""

    try:
        left_values = [float(value) for value in left]
        right_values = [float(value) for value in right]
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not left_values or len(left_values) != len(right_values):
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left_values))
    right_norm = math.sqrt(sum(value * value for value in right_values))
    if not math.isfinite(left_norm) or not math.isfinite(right_norm) or left_norm == 0 or right_norm == 0:
        return 0.0
    score = sum(a * b for a, b in zip(left_values, right_values, strict=True)) / (left_norm * right_norm)
    return score if math.isfinite(score) else 0.0


def _speech_keyword_rows(rows: list[dict[str, Any]], *, limit: int = 10) -> list[dict[str, Any]]:
    """발언 수와 출현 수를 함께 계산해 정렬된 키워드 목록을 만든다."""

    occurrence: Counter[str] = Counter()
    document_count: Counter[str] = Counter()
    agents: defaultdict[str, set[str]] = defaultdict(set)
    for row in rows:
        tokens = _speech_tokens(row.get("message", ""))
        occurrence.update(tokens)
        document_count.update(set(tokens))
        agent_id = str(row.get("persona_id") or "")
        for token in set(tokens):
            if agent_id:
                agents[token].add(agent_id)
    return [
        {
            "term": term,
            "speech_count": int(document_count[term]),
            "occurrence_count": int(occurrence[term]),
            "agent_count": len(agents[term]),
        }
        for term in sorted(document_count, key=lambda value: (-document_count[value], -occurrence[value], value))[:limit]
    ]


def _speech_stance_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """claims에서 허용된 stance만 세어 비율을 반환한다."""

    counts: Counter[str] = Counter()
    for row in rows:
        claims = row.get("claims")
        if not isinstance(claims, list):
            continue
        for claim in claims:
            if isinstance(claim, dict) and claim.get("stance") in _SPEECH_STANCES:
                counts[str(claim["stance"])] += 1
    total = sum(counts.values())
    return [
        {"stance": stance, "count": int(counts[stance]),
         "share": round(counts[stance] / total, 4) if total else 0.0}
        for stance in _SPEECH_STANCES if counts[stance]
    ]


def _speech_public_event(row: Mapping[str, Any]) -> dict[str, Any]:
    """분석 근거로 사용할 공개 event projection만 구성한다."""

    return {
        "event_id": str(row.get("event_id")),
        "game_id": str(row.get("game_id")),
        "persona_id": str(row.get("persona_id") or ""),
        "persona_name": str(row.get("persona_name") or row.get("persona_id") or "알 수 없는 에이전트"),
        "round": int(row.get("round") or 0),
        "phase": str(row.get("phase") or "UNKNOWN"),
        "message": str(row.get("message") or ""),
        "created_at": _iso(row.get("created_at")),
    }


def _aggregate_speech_rows(
    rows: list[dict[str, Any]],
    *,
    analysis_version: str | None,
    topic_limit: int,
) -> dict[str, Any]:
    """DB 행을 결정적인 주제·에이전트·키워드 집계 응답으로 변환한다.

    임베딩은 관리자 조회에서만 메모리로 사용하고 반환하지 않는다. 입력 행은
    event 시각과 sequence 순서로 정렬한 뒤 첫 번째로 유사한 centroid에 배치해
    같은 snapshot을 반복 조회해도 topic id와 대표 근거가 바뀌지 않게 한다.
    """

    ordered_rows = sorted(
        rows,
        key=lambda row: (
            str(row.get("created_at") or ""),
            int(row.get("source_sequence") or 0),
            str(row.get("event_id") or ""),
        ),
    )
    eligible_total = int(ordered_rows[0].get("eligible_total") or 0) if ordered_rows else 0
    analyzed_total = int(ordered_rows[0].get("analyzed_total") or 0) if ordered_rows else 0
    embedding_ready_total = int(ordered_rows[0].get("embedding_ready_total") or 0) if ordered_rows else 0
    claims_ready_total = int(ordered_rows[0].get("claims_ready_total") or 0) if ordered_rows else 0

    embeddable = [
        row for row in ordered_rows
        if row.get("embedding_status") == "READY" and row.get("embedding") is not None
    ]
    topic_states: list[dict[str, Any]] = []
    for row in embeddable:
        vector = row.get("embedding")
        # 주제가 많아질 때 전체 1536차원 벡터를 모든 주제와 비교하면 관리자
        # 조회가 지나치게 오래 걸릴 수 있다. 먼저 균등 표본 차원으로 후보를
        # 좁히고, 최대 24개 후보에만 전체 cosine을 적용한다.
        candidate_topics = topic_states
        try:
            vector_values = [float(value) for value in vector]
        except (TypeError, ValueError, OverflowError):
            vector_values = []
        if len(topic_states) > 24 and vector_values:
            stride = max(1, len(vector_values) // 24)
            coarse_vector = vector_values[::stride][:24]
            candidate_topics = sorted(
                topic_states,
                key=lambda topic: _speech_cosine(
                    coarse_vector,
                    [float(value) for value in topic["centroid"]][::stride][:24],
                ),
                reverse=True,
            )[:24]
        best_topic = None
        best_score = _SPEECH_SIMILARITY_THRESHOLD
        for topic in candidate_topics:
            score = _speech_cosine(vector, topic["centroid"])
            if score >= best_score:
                best_score = score
                best_topic = topic
        if best_topic is None:
            topic_states.append({"rows": [row], "centroid": list(vector)})
            continue
        best_topic["rows"].append(row)
        previous_count = len(best_topic["rows"]) - 1
        try:
            values = [float(value) for value in vector]
            if len(values) == len(best_topic["centroid"]):
                best_topic["centroid"] = [
                    (old * previous_count + new) / (previous_count + 1)
                    for old, new in zip(best_topic["centroid"], values, strict=True)
                ]
        except (TypeError, ValueError, OverflowError):
            pass

    def topic_sort_key(topic: dict[str, Any]) -> tuple[Any, ...]:
        terms = _speech_keyword_rows(topic["rows"], limit=3)
        return (
            -len(topic["rows"]),
            tuple(item["term"] for item in terms),
            str(topic["rows"][0].get("created_at") or ""),
            str(topic["rows"][0].get("event_id") or ""),
        )

    topic_states.sort(key=topic_sort_key)
    topic_ids: dict[int, str] = {}
    topic_labels: dict[int, str] = {}
    for index, topic in enumerate(topic_states):
        topic_ids[id(topic)] = f"topic-{index + 1:03d}"
        terms = _speech_keyword_rows(topic["rows"], limit=3)
        topic_labels[id(topic)] = " · ".join(item["term"] for item in terms) or f"발언 맥락 {index + 1}"

    topics: list[dict[str, Any]] = []
    topic_by_row: dict[int, dict[str, Any]] = {}
    for topic in topic_states:
        topic_id = topic_ids[id(topic)]
        topic_label = topic_labels[id(topic)]
        for row in topic["rows"]:
            topic_by_row[id(row)] = topic
        agent_counts: Counter[str] = Counter(str(row.get("persona_id") or "") for row in topic["rows"])
        agent_names = {
            str(row.get("persona_id") or ""): str(row.get("persona_name") or row.get("persona_id") or "알 수 없는 에이전트")
            for row in topic["rows"]
        }
        topic_count = len(topic["rows"])
        agent_breakdown = [
            {"persona_id": persona_id, "persona_name": agent_names.get(persona_id, persona_id),
             "speech_count": count, "share": round(count / topic_count, 4) if topic_count else 0.0}
            for persona_id, count in sorted(agent_counts.items(), key=lambda item: (-item[1], item[0]))
            if persona_id
        ]
        topics.append({
            "topic_id": topic_id,
            "label": topic_label,
            "speech_count": topic_count,
            "agent_count": len(agent_counts),
            "agent_breakdown": agent_breakdown,
            "stance_breakdown": _speech_stance_rows(topic["rows"]),
            "keywords": _speech_keyword_rows(topic["rows"], limit=8),
            "related_terms": [item["term"] for item in _speech_keyword_rows(topic["rows"], limit=8)],
            "representative": _speech_public_event(topic["rows"][0]),
            "evidence": [_speech_public_event(row) for row in topic["rows"][:5]],
        })

    agent_groups: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in embeddable:
        persona_id = str(row.get("persona_id") or "")
        if persona_id:
            agent_groups[persona_id].append(row)
    agents: list[dict[str, Any]] = []
    denominator = len(embeddable)
    visible_topics = topics[:topic_limit]
    visible_topic_ids = {topic["topic_id"] for topic in visible_topics}
    topic_records = {topic["topic_id"]: topic for topic in visible_topics}
    for persona_id, agent_rows in sorted(agent_groups.items(), key=lambda item: (-len(item[1]), item[0])):
        persona_name = str(agent_rows[0].get("persona_name") or persona_id)
        topic_counts: Counter[str] = Counter()
        for row in agent_rows:
            topic = topic_by_row.get(id(row))
            if topic is not None:
                topic_counts[topic_ids[id(topic)]] += 1
        topic_rows = []
        for topic_id, count in sorted(topic_counts.items(), key=lambda item: (-item[1], item[0])):
            if topic_id not in visible_topic_ids:
                continue
            topic_rows.append({
                "topic_id": topic_id,
                "label": topic_records[topic_id]["label"],
                "speech_count": count,
            })
            if len(topic_rows) >= 5:
                break
        agents.append({
            "persona_id": persona_id,
            "persona_name": persona_name,
            "speech_count": len(agent_rows),
            "share": round(len(agent_rows) / denominator, 4) if denominator else 0.0,
            "top_topics": topic_rows,
            "top_keywords": _speech_keyword_rows(agent_rows, limit=8),
            "stance_breakdown": _speech_stance_rows(agent_rows),
        })

    coverage_denominator = eligible_total
    return {
        "analysis_version": analysis_version,
        "generated_at": _iso(datetime.now(UTC)),
        "coverage": {
            "eligible_speeches": coverage_denominator,
            "analyzed_speeches": analyzed_total,
            "embedding_ready": embedding_ready_total,
            "claims_ready": claims_ready_total,
            "embedding_coverage": round(embedding_ready_total / coverage_denominator, 4) if coverage_denominator else 0.0,
            "claims_coverage": round(claims_ready_total / coverage_denominator, 4) if coverage_denominator else 0.0,
            "sampled_speeches": len(embeddable),
            "sample_limited": coverage_denominator > _SPEECH_SAMPLE_LIMIT,
        },
        "topics": topics[:topic_limit],
        "topic_count": len(topics),
        "agents": agents,
        "keywords": _speech_keyword_rows(embeddable, limit=30),
        "method": {
            "similarity": "cosine",
            "threshold": _SPEECH_SIMILARITY_THRESHOLD,
            "projection_dimensions": _SPEECH_EMBEDDING_PROJECTION,
            "sample_limit": _SPEECH_SAMPLE_LIMIT,
            "keyword_note": "원문 토큰과 같은 주제의 동시 출현 표현을 표시합니다.",
        },
    }


ConnectionFactory = Callable[..., Any]


class PostgresAdminRepository:
    """정본 PostgreSQL에서 공개 관리자 조회와 감사 event를 수행한다."""

    def __init__(
        self,
        database_url: str,
        *,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self._database_url = database_url
        self._connection_factory = connection_factory or psycopg.connect

    def _connection(self) -> Any:
        """dict row를 사용하는 연결을 열되 URL을 로그나 응답으로 내보내지 않는다."""

        return self._connection_factory(self._database_url, row_factory=dict_row)

    def list_games(
        self,
        *,
        status: str | None,
        phase: str | None,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """게임 목록에서 개인 역할·사실 테이블을 조인하지 않는다."""

        if cursor:
            try:
                UUID(cursor)
            except ValueError as exc:
                raise ValueError("cursor must be a game UUID") from exc
        query = """
            SELECT g.id AS game_id, g.owner_user_id, g.status, g.phase, g.round,
                   g.state_version, g.player_count,
                   CASE WHEN g.status = 'IN_PROGRESS' THEN
                       CASE g.phase
                         WHEN 'DAY_DISCUSSION' THEN 'SPEECH'
                         WHEN 'NIGHT_ACTION' THEN 'NIGHT'
                         WHEN 'DAY_VOTE' THEN 'VOTE'
                         WHEN 'REVOTE' THEN 'REVOTE'
                         WHEN 'FINAL_ACCUSATION' THEN 'FINAL_VOTE'
                         ELSE NULL
                       END
                   ELSE NULL END AS open_window_kind,
                   g.updated_at
            FROM public.games g
            WHERE (%s IS NULL OR g.status = %s)
              AND (%s IS NULL OR g.phase = %s)
              AND (
                  %s IS NULL
                  OR (g.updated_at, g.id) < (
                      SELECT c.updated_at, c.id
                      FROM public.games c
                      WHERE c.id = %s
                  )
              )
            ORDER BY g.updated_at DESC, g.id DESC
            LIMIT %s
        """
        params = [status, status, phase, phase, cursor, cursor, limit + 1]
        with self._connection() as connection:
            with connection.cursor() as cursor_obj:
                cursor_obj.execute(query, params)
                rows = list(cursor_obj.fetchall())
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [self._list_row(row) for row in rows]
        return items, (items[-1]["game_id"] if has_more else None)

    @staticmethod
    def _list_row(row: Mapping[str, Any]) -> dict[str, Any]:
        """DB row를 관리자 목록 폐쇄형 object로 변환한다."""

        return {
            "game_id": str(row["game_id"]),
            "owner_user_id": str(row["owner_user_id"]),
            "status": row["status"],
            "phase": row["phase"],
            "round": int(row["round"]),
            "state_version": int(row["state_version"]),
            "player_count": int(row["player_count"]),
            "open_window_kind": row["open_window_kind"],
            "updated_at": _iso(row["updated_at"]),
        }

    def get_game(self, game_id: UUID) -> dict[str, Any] | None:
        """games·public game_events·현재 window metadata만 읽는다."""

        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id AS game_id, owner_user_id, status, phase, round,
                           state_version, player_count, updated_at, winner, win_reason,
                           finished_at
                    FROM public.games
                    WHERE id = %s
                    """,
                    (game_id,),
                )
                game_row = cursor.fetchone()
                if game_row is None:
                    return None
                cursor.execute(
                    """
                    SELECT id AS event_id, event_type, created_at, payload
                    FROM public.game_events
                    WHERE game_id = %s AND audience = 'PUBLIC'
                    ORDER BY sequence
                    """,
                    (game_id,),
                )
                events = [
                    {
                        "event_id": str(row["event_id"]),
                        "event_type": row["event_type"],
                        "created_at": _iso(row["created_at"]),
                        "data": dict(row["payload"]),
                    }
                    for row in cursor.fetchall()
                ]
                cursor.execute(
                    """
                    SELECT window_kind, cycle, opened_state_version, deadline_at,
                           remaining_ms_on_save, status
                    FROM public.action_windows
                    WHERE game_id = %s AND status IN ('OPEN', 'PAUSED', 'RESOLVING')
                    ORDER BY opened_at DESC, id DESC
                    LIMIT 1
                    """,
                    (game_id,),
                )
                window_row = cursor.fetchone()
        status = game_row["status"]
        result = None
        if status == "COMPLETED":
            result = {
                "winner": game_row["winner"],
                "win_reason": game_row["win_reason"],
                "finished_at": _iso(game_row["finished_at"]),
            }
        return {
            "game": self._list_row(
                {
                    **game_row,
                    "open_window_kind": window_row["window_kind"] if window_row else None,
                }
            ),
            "public_events": events,
            "action_window": (
                {
                    "kind": window_row["window_kind"],
                    "cycle": int(window_row["cycle"]),
                    "opened_state_version": int(window_row["opened_state_version"]),
                    "deadline_at": _iso(window_row["deadline_at"]),
                    "remaining_ms": window_row["remaining_ms_on_save"],
                    "status": window_row["status"],
                }
                if window_row
                else None
            ),
            "failure_code": None,
            "result": result,
        }

    def metrics(
        self,
        *,
        from_time: datetime | None,
        to_time: datetime | None,
    ) -> dict[str, Any]:
        """정본 games와 feedback에서 문서에 정의된 운영 지표만 집계한다."""

        with self._connection() as connection:
            with connection.cursor() as cursor_obj:
                cursor_obj.execute(
                    """
                    SELECT COUNT(*) AS games_created,
                           COUNT(*) FILTER (WHERE g.status = 'COMPLETED') AS games_completed,
                           COUNT(*) FILTER (WHERE g.status = 'SAVED') AS games_saved,
                           COALESCE(
                               AVG(g.round) FILTER (WHERE g.status = 'COMPLETED'), 0
                           ) AS average_rounds,
                           COUNT(*) FILTER (
                               WHERE g.status = 'COMPLETED' AND g.winner = 'CITIZEN'
                           ) AS citizen_wins,
                           COUNT(*) FILTER (
                               WHERE g.status = 'COMPLETED' AND g.winner = 'MAFIA'
                           ) AS mafia_wins,
                           COUNT(*) FILTER (WHERE g.status = 'COMPLETED') AS completed_for_rate
                    FROM public.games g
                    WHERE (%s::timestamptz IS NULL OR g.created_at >= %s)
                      AND (%s::timestamptz IS NULL OR g.created_at <= %s)
                    """,
                    [from_time, from_time, to_time, to_time],
                )
                row = cursor_obj.fetchone()
                cursor_obj.execute(
                    """
                    SELECT AVG(f.rating) AS feedback_average
                    FROM public.feedback f
                    WHERE (%s::timestamptz IS NULL OR f.created_at >= %s)
                      AND (%s::timestamptz IS NULL OR f.created_at <= %s)
                    """,
                    [from_time, from_time, to_time, to_time],
                )
                feedback_row = cursor_obj.fetchone()
                cursor_obj.execute("SELECT COUNT(*) AS users_total FROM public.users")
                users_total = int(cursor_obj.fetchone()["users_total"])
                cursor_obj.execute(
                    """
                    SELECT COUNT(*) AS total FROM public.action_submissions s
                    JOIN public.games g ON g.id = s.game_id
                    WHERE s.source = 'AUTO'
                      AND (%s::timestamptz IS NULL OR g.created_at >= %s)
                      AND (%s::timestamptz IS NULL OR g.created_at <= %s)
                    """, [from_time, from_time, to_time, to_time],
                )
                auto_actions = int(cursor_obj.fetchone()["total"])
                # 전체 기간 KPI라도 일별 그래프의 응답 크기는 UTC 최근 30일로 제한한다.
                daily_end = to_time or datetime.now(UTC)
                daily_start = from_time or (
                    daily_end.replace(hour=0, minute=0, second=0, microsecond=0)
                    - timedelta(days=29)
                )
                if from_time is not None and to_time is None:
                    daily_end = min(daily_end, from_time + timedelta(days=31))
                cursor_obj.execute(
                    """
                    SELECT (created_at AT TIME ZONE 'UTC')::date AS day, COUNT(*) AS total
                    FROM public.games WHERE created_at >= %s AND created_at <= %s
                    GROUP BY day ORDER BY day
                    """, [daily_start, daily_end],
                )
                counts = {r["day"].isoformat(): int(r["total"]) for r in cursor_obj.fetchall()}
                start_day, end_day = daily_start.astimezone(UTC).date(), daily_end.astimezone(UTC).date()
                daily = [{"date": (start_day + timedelta(days=i)).isoformat(),
                          "games_created": counts.get((start_day + timedelta(days=i)).isoformat(), 0)}
                         for i in range(max(0, (end_day - start_day).days + 1))]
        created = int(row["games_created"])
        return {
            "games_created": created,
            "games_completed": int(row["games_completed"]),
            "games_saved": int(row["games_saved"]),
            "completion_rate": round(int(row["completed_for_rate"]) / created, 4)
            if created
            else 0.0,
            "average_rounds": round(float(row["average_rounds"]), 2),
            "wins_by_faction": {
                "CITIZEN": int(row["citizen_wins"]),
                "MAFIA": int(row["mafia_wins"]),
            },
            "users_total": users_total,
            "daily_games": daily,
            "auto_action_count": auto_actions,
            "feedback_average": (
                round(float(feedback_row["feedback_average"]), 2)
                if feedback_row["feedback_average"] is not None
                else None
            ),
        }

    def role_win_rates(self, *, from_time: datetime | None,
                       to_time: datetime | None) -> list[dict[str, Any]]:
        """종료 게임의 AI 역할을 DB에서 집계하고 개별 좌석 정보는 반환하지 않는다."""

        with self._connection() as connection:
            with connection.cursor() as cursor_obj:
                cursor_obj.execute(
                    """
                    SELECT p.role AS job, COUNT(*) AS participations,
                           COUNT(*) FILTER (WHERE p.faction = g.winner) AS wins
                    FROM public.game_players p JOIN public.games g ON g.id = p.game_id
                    WHERE g.status = 'COMPLETED' AND p.kind = 'AI'
                      AND (%s::timestamptz IS NULL OR g.created_at >= %s)
                      AND (%s::timestamptz IS NULL OR g.created_at <= %s)
                    GROUP BY p.role
                    """, [from_time, from_time, to_time, to_time],
                )
                counts = {row["job"]: row for row in cursor_obj.fetchall()}
        items = []
        for job in ["MAFIA", "DETECTIVE", "DOCTOR", "CITIZEN"]:
            row = counts.get(job, {})
            total, wins = int(row.get("participations", 0)), int(row.get("wins", 0))
            items.append({"job": job, "participations": total, "wins": wins,
                          "win_rate": round(wins / total, 6) if total else 0.0})
        return items

    def persona_win_rates(self, *, from_time: datetime | None,
                          to_time: datetime | None) -> list[dict[str, Any]]:
        """에이전트 페르소나별 AI 참여·승리를 집계하고 내부 파라미터는 반환하지 않는다."""

        with self._connection() as connection:
            with connection.cursor() as cursor_obj:
                cursor_obj.execute(
                    """
                    SELECT ap.id AS persona_id, ap.display_name AS persona_name,
                           ap.speech_style AS personality_summary,
                           COUNT(gp.id) FILTER (WHERE g.id IS NOT NULL) AS participations,
                           COUNT(gp.id) FILTER (
                               WHERE g.id IS NOT NULL AND gp.faction = g.winner
                           ) AS wins
                    FROM public.agent_personas ap
                    LEFT JOIN public.game_players gp
                      ON gp.persona_id = ap.id AND gp.kind = 'AI'
                    LEFT JOIN public.games g
                      ON g.id = gp.game_id
                     AND g.status = 'COMPLETED'
                     AND (%s::timestamptz IS NULL OR g.created_at >= %s)
                     AND (%s::timestamptz IS NULL OR g.created_at <= %s)
                    WHERE ap.active = TRUE
                    GROUP BY ap.id, ap.display_name, ap.speech_style
                    ORDER BY ap.display_name, ap.id
                    """,
                    [from_time, from_time, to_time, to_time],
                )
                rows = list(cursor_obj.fetchall())
        return [
            {
                "persona_id": str(row["persona_id"]),
                "persona_name": row["persona_name"],
                "personality_summary": row["personality_summary"],
                "participations": int(row["participations"]),
                "wins": int(row["wins"]),
                "win_rate": (
                    round(int(row["wins"]) / int(row["participations"]), 6)
                    if int(row["participations"])
                    else 0.0
                ),
            }
            for row in rows
        ]

    def speech_analytics(
        self,
        *,
        from_time: datetime | None,
        to_time: datetime | None,
        game_id: UUID | None,
        persona_id: str | None,
        round_number: int | None,
        analysis_version: str | None,
        topic_limit: int,
    ) -> dict[str, Any]:
        """공개 AI 발언과 파생 분석만 읽어 관리자 집계로 변환한다.

        원본 event와 분석 행을 한 조회 범위로 묶어 분석 행이 아직 만들어지지
        않은 발언도 coverage 분모에 포함한다. 역할·진영·private context 컬럼은
        SQL에서 선택하지 않으며, 임베딩은 집계 직후 응답에서 제거한다.
        """

        if not 1 <= topic_limit <= 20:
            raise ValueError("topic_limit must be between 1 and 20")
        with self._connection() as connection:
            with connection.cursor() as cursor_obj:
                cursor_obj.execute(
                    """
                    SELECT COALESCE(
                        %s::text,
                        (SELECT v.analysis_version
                           FROM public.speech_analysis_versions v
                          ORDER BY v.activated_at DESC, v.analysis_version DESC
                          LIMIT 1)
                    ) AS analysis_version
                    """,
                    (analysis_version,),
                )
                selected_row = cursor_obj.fetchone()
                selected_version = selected_row["analysis_version"] if selected_row else analysis_version
                cursor_obj.execute(
                    """
                    WITH eligible AS (
                        SELECT e.id AS event_id,
                               e.game_id,
                               e.sequence AS source_sequence,
                               e.created_at,
                               e.payload->>'message' AS message,
                               p.persona_id,
                               ap.display_name AS persona_name,
                               w.phase,
                               w.round,
                               a.analysis_version,
                               a.embedding[1:96] AS embedding,
                               a.embedding_status,
                               a.claims,
                               a.claims_status,
                               COUNT(*) OVER () AS eligible_total,
                               COUNT(a.id) OVER () AS analyzed_total,
                               COUNT(*) FILTER (WHERE a.embedding_status = 'READY') OVER () AS embedding_ready_total,
                               COUNT(*) FILTER (WHERE a.claims_status = 'READY') OVER () AS claims_ready_total
                          FROM public.game_events e
                          JOIN public.game_players p
                            ON p.game_id = e.game_id
                           AND p.id::text = e.payload->>'player_id'
                           AND p.kind = 'AI'
                          JOIN public.agent_personas ap
                            ON ap.id = p.persona_id
                          JOIN LATERAL (
                              SELECT aw.phase, aw.round
                                FROM public.game_events se
                                JOIN public.action_windows aw
                                  ON aw.game_id = se.game_id
                                 AND aw.id::text = se.payload->>'window_id'
                                 AND aw.window_kind = 'SPEECH'
                               WHERE se.game_id = e.game_id
                                 AND se.sequence < e.sequence
                                 AND se.audience = 'PUBLIC'
                                 AND se.operation_type = 'SET_ACTION_WINDOW'
                               ORDER BY se.sequence DESC
                               LIMIT 1
                          ) w ON TRUE
                          LEFT JOIN public.speech_analysis a
                            ON a.game_id = e.game_id
                           AND a.event_id = e.id
                           AND a.analysis_version = %s
                         WHERE e.audience = 'PUBLIC'
                           AND e.audience_player_id IS NULL
                           AND e.event_type = 'PLAYER_SPOKE'
                           AND e.schema_version = 1
                           AND e.operation_type = 'APPEND_PUBLIC_EVENT'
                           AND jsonb_typeof(e.payload->'message') = 'string'
                           AND btrim(e.payload->>'message') <> ''
                           AND length(e.payload->>'message') BETWEEN 1 AND 200
                           AND w.phase IN ('DAY_DISCUSSION', 'FINAL_DISCUSSION')
                           AND (%s::timestamptz IS NULL OR e.created_at >= %s)
                           AND (%s::timestamptz IS NULL OR e.created_at <= %s)
                           AND (%s::uuid IS NULL OR e.game_id = %s)
                           AND (%s::text IS NULL OR p.persona_id = %s)
                           AND (%s::smallint IS NULL OR COALESCE(a.round, w.round) = %s)
                    )
                    SELECT *
                      FROM eligible
                     ORDER BY created_at, source_sequence, event_id
                     LIMIT %s
                    """,
                    [
                        selected_version,
                        from_time,
                        from_time,
                        to_time,
                        to_time,
                        game_id,
                        game_id,
                        persona_id,
                        persona_id,
                        round_number,
                        round_number,
                        _SPEECH_SAMPLE_LIMIT,
                    ],
                )
                rows = [dict(row) for row in cursor_obj.fetchall()]
        return _aggregate_speech_rows(
            rows,
            analysis_version=str(selected_version) if selected_version is not None else None,
            topic_limit=topic_limit,
        )

    def list_feedback(self, *, feedback_type: str | None, rating: int | None,
                      cursor: UUID | None, limit: int) -> tuple[list[dict], str | None]:
        """사용자가 작성한 의견만 읽고 UUID 커서로 동일 시각의 기록까지 순서대로 조회한다."""

        with self._connection() as connection:
            with connection.cursor() as cursor_obj:
                cursor_obj.execute(
                    """
                    SELECT f.id, f.user_id, f.feedback_type, f.game_id,
                           f.rating, f.comment, f.tags, f.created_at
                    FROM public.feedback f
                    WHERE (%s::text IS NULL OR f.feedback_type = %s)
                      AND (%s::integer IS NULL OR f.rating = %s)
                      AND (%s::uuid IS NULL OR (f.created_at, f.id) < (
                          SELECT c.created_at, c.id FROM public.feedback c WHERE c.id = %s))
                    ORDER BY f.created_at DESC, f.id DESC LIMIT %s
                    """, [feedback_type, feedback_type, rating, rating, cursor, cursor, limit + 1],
                )
                rows = list(cursor_obj.fetchall())
        items = [{"feedback_id": str(row["id"]), "user_id": str(row["user_id"]),
                  "feedback_type": row["feedback_type"],
                  "game_id": str(row["game_id"]) if row["game_id"] else None,
                  "rating": int(row["rating"]), "comment": row["comment"],
                  "tags": list(row["tags"]), "created_at": _iso(row["created_at"])}
                 for row in rows[:limit]]
        return items, items[-1]["feedback_id"] if len(rows) > limit else None

    def list_audit_logs(self, *, event_type: str | None, cursor: int | None,
                        limit: int) -> tuple[list[dict], str | None]:
        """감사 이벤트의 허용 메타데이터를 PK 커서로 읽고 원문 서버 로그는 읽지 않는다."""

        with self._connection() as connection:
            with connection.cursor() as cursor_obj:
                cursor_obj.execute(
                    """
                    SELECT id, admin_user_id, action, target_game_id, request_id, created_at
                    FROM public.admin_audit_events
                    WHERE (%s::text IS NULL OR action = %s)
                      AND (%s::bigint IS NULL OR id < %s)
                    ORDER BY id DESC LIMIT %s
                    """, [event_type, event_type, cursor, cursor, limit + 1],
                )
                rows = list(cursor_obj.fetchall())
        items = [{"audit_id": str(row["id"]), "admin_user_id": str(row["admin_user_id"]),
                  "event_type": row["action"],
                  "target_game_id": str(row["target_game_id"]) if row["target_game_id"] else None,
                  "request_id": str(row["request_id"]), "created_at": _iso(row["created_at"])}
                 for row in rows[:limit]]
        return items, items[-1]["audit_id"] if len(rows) > limit else None

    def list_agent_jobs(
        self, *, game_id: UUID | None, job_kind: str | None, status: str | None,
        cursor: UUID | None, limit: int,
    ) -> tuple[list[dict], str | None]:
        """작업 메타데이터만 최근 생성순으로 읽고 동률은 UUID로 구분한다.

        제안 JSON과 lease token은 SQL에서 선택하지 않아 비공개 행동·권한이
        응답에 섞일 수 없게 한다. 플레이어 이름도 같은 게임에 속한 행만 읽는다.
        작업 상태는 생성 결과이므로 실제 행동 원장의 반영 상태로 해석하지 않는다.
        """

        with self._connection() as connection:
            with connection.cursor() as cursor_obj:
                cursor_obj.execute(
                    """
                    SELECT j.id, j.game_id, j.player_id, p.display_name AS player_name,
                           j.window_id, j.job_kind, j.status, j.reserved_state_version,
                           j.failure_code, j.created_at, j.completed_at
                    FROM public.agent_jobs j
                    LEFT JOIN public.game_players p
                      ON p.game_id = j.game_id AND p.id = j.player_id
                    WHERE (%s::uuid IS NULL OR j.game_id = %s)
                      AND (%s::text IS NULL OR j.job_kind = %s)
                      AND (%s::text IS NULL OR j.status = %s)
                      AND (%s::uuid IS NULL OR (j.created_at, j.id) < (
                          SELECT c.created_at, c.id FROM public.agent_jobs c WHERE c.id = %s))
                    ORDER BY j.created_at DESC, j.id DESC LIMIT %s
                    """,
                    [game_id, game_id, job_kind, job_kind, status, status,
                     cursor, cursor, limit + 1],
                )
                rows = list(cursor_obj.fetchall())
        items = [{
            "job_id": str(row["id"]), "game_id": str(row["game_id"]),
            "player_id": str(row["player_id"]) if row["player_id"] else None,
            "player_name": row["player_name"], "window_id": str(row["window_id"]),
            "job_kind": row["job_kind"], "status": row["status"],
            "reserved_state_version": int(row["reserved_state_version"]),
            "failure_code": row["failure_code"], "created_at": _iso(row["created_at"]),
            "completed_at": _iso(row["completed_at"]),
        } for row in rows[:limit]]
        return items, items[-1]["job_id"] if len(rows) > limit else None

    def search_knowledge(
        self,
        *,
        question: str,
        source_types: list[str],
        rating_lte: int | None,
        from_time: datetime | None,
        to_time: datetime | None,
        top_k: int,
    ) -> list[dict[str, Any]]:
        """승인된 지식 청크만 키워드·벡터 혼합 점수로 검색한다.

        질문 API는 이 메서드에서 INSERT·UPDATE를 수행하지 않는다. 색인된
        문서의 공개 메타데이터와 정제된 청크만 반환하고, 역할·private context와
        같은 게임 내부 자료 테이블은 조인하지 않는다.
        """

        from backend.app.services.admin_knowledge import local_embedding

        query_embedding = local_embedding(question)
        with self._connection() as connection:
            with connection.cursor() as cursor_obj:
                cursor_obj.execute(
                    """
                    WITH ranked AS (
                        SELECT d.source_type, d.source_id, d.title,
                               c.content AS snippet,
                               ts_rank_cd(c.content_tsv, plainto_tsquery('simple', %s))
                                   AS keyword_score,
                               GREATEST(0.0, 1.0 - (c.embedding <=> %s::vector))
                                   AS vector_score
                        FROM public.admin_knowledge_documents d
                        JOIN public.admin_knowledge_chunks c ON c.document_id = d.id
                        WHERE d.visibility = 'ADMIN_APPROVED'
                          AND (%s::text[] IS NULL OR d.source_type = ANY(%s::text[]))
                          AND (%s::smallint IS NULL OR d.feedback_rating <= %s)
                          AND (%s::timestamptz IS NULL OR d.approved_at >= %s)
                          AND (%s::timestamptz IS NULL OR d.approved_at <= %s)
                    )
                    SELECT source_type, source_id, title, snippet,
                           (keyword_score * 0.55 + vector_score * 0.45) AS score
                    FROM ranked
                    WHERE keyword_score > 0 OR vector_score > 0
                    ORDER BY score DESC, source_type, source_id
                    LIMIT %s
                    """,
                    [
                        question,
                        query_embedding,
                        source_types or None,
                        source_types or None,
                        rating_lte,
                        rating_lte,
                        from_time,
                        from_time,
                        to_time,
                        to_time,
                        top_k,
                    ],
                )
                rows = list(cursor_obj.fetchall())
        return [
            {
                "source_type": row["source_type"],
                "source_id": row["source_id"],
                "title": row["title"],
                "snippet": str(row["snippet"])[:240],
                "score": float(row["score"]),
            }
            for row in rows
        ]

    def append_audit(
        self,
        *,
        admin_user_id: UUID,
        action: str,
        target_game_id: UUID | None,
        request_id: UUID,
    ) -> None:
        """감사 로그에 request metadata만 추가하고 응답 내용을 저장하지 않는다."""

        with self._connection() as connection:
            with connection.cursor() as cursor_obj:
                cursor_obj.execute(
                    """
                    INSERT INTO public.admin_audit_events
                        (admin_user_id, action, target_game_id, request_id)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (admin_user_id, action, target_game_id, request_id),
                )
