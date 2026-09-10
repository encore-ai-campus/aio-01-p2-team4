"""관리자 read-only Backend API client."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

HttpTransport = Callable[[Request, float], tuple[int, bytes]]

# 공개 합성 키는 로컬 데모 연결 시험에만 사용하며 실제 API에 전송하지 않는다.
DEMO_API_KEY = "demo_ai_mafia_admin_v1"
# 현재 관리자 화면에서 실제로 조회하는 감사 유형만 필터에 노출한다.
# 게임 목록·상세·직업별 승률·운영 에이전트 질문은 이 화면에서 조회하지 않으므로
# 선택지에서 제외하고, Backend의 전체 감사 이벤트 계약은 별도로 유지한다.
AUDIT_EVENT_LABELS = {
    "전체": None,
    "운영 지표 조회": "ADMIN_GET_METRICS",
    "페르소나 승률 조회": "ADMIN_GET_PERSONA_WIN_RATES",
    "AI 발언 분석 조회": "ADMIN_GET_SPEECH_ANALYTICS",
    "피드백 목록 조회": "ADMIN_LIST_FEEDBACK",
    "감사 로그 조회": "ADMIN_LIST_AUDIT_LOGS",
    "AI Agent 행동 조회": "ADMIN_LIST_AGENT_JOBS",
}
AGENT_JOB_KIND_LABELS = {
    "전체": None, "발언": "SPEECH", "밤 행동": "NIGHT_ACTION",
    "투표": "VOTE", "GM 해설": "GM_NARRATION",
}
AGENT_JOB_STATUS_LABELS = {
    "전체": None, "예약됨": "RESERVED", "결과 생성 성공": "SUCCEEDED",
    "대체 결과 생성": "FALLBACK", "만료·폐기": "STALE", "실패": "FAILED",
}
JOB_LABELS = {"MAFIA": "마피아", "DETECTIVE": "탐정", "DOCTOR": "의사", "CITIZEN": "시민"}


def _agent_job_params(*, game_id, job_kind, status, cursor, limit) -> dict[str, Any]:
    """실제·데모 조회가 동일한 분류·UUID·페이지 크기를 사용하도록 제한한다."""

    if not 1 <= limit <= 100:
        raise ValueError("Agent 행동 로그는 1부터 100건까지 조회할 수 있습니다.")
    if job_kind not in AGENT_JOB_KIND_LABELS.values() or status not in AGENT_JOB_STATUS_LABELS.values():
        raise ValueError("Agent 작업 종류 또는 처리 상태가 올바르지 않습니다.")
    return {key: value for key, value in {
        "game_id": str(UUID(str(game_id))) if game_id is not None else None,
        "job_kind": job_kind, "status": status,
        "cursor": str(UUID(str(cursor))) if cursor is not None else None,
        "limit": limit,
    }.items() if value is not None}


class AdminApiError(RuntimeError):
    """관리자 API의 고정 오류만 전달하는 예외."""

    def __init__(self, status_code: int, code: str):
        super().__init__(code)
        self.status_code = status_code
        self.code = code


def is_demo_mode() -> bool:
    """로컬 화면 확인용 가상 데이터 모드가 명시적으로 켜졌는지 확인한다."""

    return os.getenv("ADMIN_DEMO_MODE", "").strip().lower() in {"1", "true", "yes", "on"}


class AdminApiClient:
    """조회 endpoint만 노출해 관리자 Front의 변경 요청을 구조적으로 막는다."""

    # 팀 전달 사항: Backend는 ADMIN_USER_IDS에 정확히 등록된 UUID만 관리자 GET에
    # 접근시키고, 관리자 endpoint에는 mutation·강제 종료 기능을 추가하지 않는다.

    def __init__(self, *, user_id: str | UUID, api_url: str | None = None, transport: HttpTransport | None = None):
        self.user_id = UUID(str(user_id))
        self.api_url = (api_url or os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000")).strip().rstrip("/")
        self._transport = transport or _send

    def metrics(self, *, from_date: str | None = None,
                to_date: str | None = None) -> dict[str, Any]:
        """명세서의 선택적 최대 31일 기간으로 관리자 지표를 조회한다."""

        query = []
        if from_date:
            query.append(f"from={quote(from_date.strip(), safe='-:')}")
        if to_date:
            query.append(f"to={quote(to_date.strip(), safe='-:')}")
        suffix = "?" + "&".join(query) if query else ""
        return self._request("/api/v1/admin/metrics" + suffix)

    def games(self, *, status: str | None = None, phase: str | None = None,
              cursor: str | None = None, limit: int = 20) -> dict[str, Any]:
        """명세서의 관리자 게임 목록 필터와 페이지 cursor를 사용해 조회한다."""

        if not 1 <= limit <= 100:
            raise ValueError("관리자 게임 목록 limit은 1부터 100까지여야 합니다.")
        query = [f"limit={limit}"]
        if status:
            query.append(f"status={status}")
        if phase:
            query.append(f"phase={phase}")
        if cursor:
            normalized_cursor = cursor.strip()
            if not normalized_cursor:
                raise ValueError("관리자 게임 목록 cursor는 비어 있을 수 없습니다.")
            query.append(f"cursor={quote(normalized_cursor, safe='')}")
        suffix = "?" + "&".join(query) if query else ""
        return self._request("/api/v1/admin/games" + suffix)

    def game_detail(self, game_id: str | UUID) -> dict[str, Any]:
        """관리자용 비밀정보 없는 게임 상세를 조회한다."""

        return self._request(f"/api/v1/admin/games/{UUID(str(game_id))}")

    def role_win_rates(self, *, from_date: str | None = None,
                       to_date: str | None = None) -> dict:
        """API 7.5의 완료 게임 AI 집계를 조회한다."""

        query = urlencode({k: v for k, v in {"from": from_date, "to": to_date}.items() if v})
        return self._request("/api/v1/admin/role-win-rates" + (f"?{query}" if query else ""))

    def persona_win_rates(self, *, from_date: str | None = None,
                          to_date: str | None = None) -> dict:
        """API 7.6의 에이전트 페르소나별 승률 집계를 조회한다."""

        query = urlencode({k: v for k, v in {"from": from_date, "to": to_date}.items() if v})
        return self._request("/api/v1/admin/persona-win-rates" + (f"?{query}" if query else ""))

    def speech_analytics(
        self,
        *,
        from_date: str | None = None,
        to_date: str | None = None,
        game_id: str | UUID | None = None,
        persona_id: str | None = None,
        round_number: int | None = None,
        analysis_version: str | None = None,
        limit: int = 12,
    ) -> dict[str, Any]:
        """공개 AI 발언 분석 집계를 조회하며 벡터는 관리자 화면에 전달하지 않는다."""

        if not 1 <= limit <= 20:
            raise ValueError("발언 분석 주제 수는 1부터 20까지여야 합니다.")
        if round_number is not None and not 0 <= int(round_number) <= 5:
            raise ValueError("발언 분석 round는 0부터 5까지여야 합니다.")
        params: dict[str, Any] = {"limit": limit}
        for key, value in {
            "from": from_date,
            "to": to_date,
            "game_id": str(UUID(str(game_id))) if game_id is not None else None,
            "persona_id": persona_id,
            "round": round_number,
            "analysis_version": analysis_version,
        }.items():
            if value is not None and value != "":
                params[key] = value
        query = urlencode(params)
        # 전체 기간 발언 집계의 지연만 허용하고 다른 관리자 요청의 대기 제한은 유지한다.
        return self._request("/api/v1/admin/speech-analytics?" + query, timeout=30.0)

    def feedback(self, *, feedback_type: str | None = None, rating: int | None = None,
                 cursor: str | None = None, limit: int = 20) -> dict:
        """사용자 의견을 페이지 단위로 읽으며 필터는 URL 인코딩한다."""

        query = urlencode({k: v for k, v in {"feedback_type": feedback_type, "rating": rating,
                                           "cursor": cursor, "limit": limit}.items() if v is not None})
        return self._request("/api/v1/admin/feedback?" + query)

    def audit_logs(self, *, event_type: str | None = None,
                   cursor: str | None = None, limit: int = 20) -> dict:
        """서버 원문 로그 대신 관리자 감사 메타데이터를 조회한다."""

        query = urlencode({k: v for k, v in {"event_type": event_type, "cursor": cursor,
                                           "limit": limit}.items() if v is not None})
        return self._request("/api/v1/admin/audit-logs?" + query)

    def agent_jobs(
        self, *, game_id: str | UUID | None = None, job_kind: str | None = None,
        status: str | None = None, cursor: str | None = None, limit: int = 20,
    ) -> dict:
        """Backend를 통해 팀 DB의 Agent 작업 메타데이터만 페이지 단위로 읽는다."""

        params = _agent_job_params(
            game_id=game_id, job_kind=job_kind, status=status, cursor=cursor, limit=limit,
        )
        return self._request("/api/v1/admin/agent-jobs?" + urlencode(params))

    def insights_query(self, question: str, *, source_types: list[str] | None = None,
                       rating_lte: int | None = None, from_date: str | None = None,
                       to_date: str | None = None, top_k: int = 5) -> dict[str, Any]:
        """승인 자료 검색 API에 질문을 보내고 근거 중심 응답을 받는다."""

        normalized_question = " ".join(str(question).split())
        if not 3 <= len(normalized_question) <= 500:
            raise ValueError("관리자 질문은 3자부터 500자까지 입력해야 합니다.")
        if not 1 <= top_k <= 10:
            raise ValueError("관리자 검색 결과 수는 1부터 10까지여야 합니다.")
        filters: dict[str, Any] = {}
        if source_types:
            filters["source_types"] = list(source_types)
        if rating_lte is not None:
            filters["rating_lte"] = rating_lte
        if from_date:
            filters["from"] = from_date
        if to_date:
            filters["to"] = to_date
        return self._request_json(
            "/api/v1/admin/insights/query",
            {"question": normalized_question, "filters": filters, "top_k": top_k},
        )

    def _request(self, path: str, *, timeout: float = 5.0) -> dict[str, Any]:
        request = Request(
            f"{self.api_url}{path}",
            headers={"Accept": "application/json", "X-User-Id": str(self.user_id),
                     "X-Request-Id": str(uuid4())},
        )
        return self._send_request(request, timeout=timeout)

    def _request_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """관리자 질문 body를 JSON으로 보내되 인증 header 규칙은 GET과 공유한다."""

        request = Request(
            f"{self.api_url}{path}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"Accept": "application/json", "Content-Type": "application/json",
                     "X-User-Id": str(self.user_id), "X-Request-Id": str(uuid4())},
        )
        return self._send_request(request)

    def _send_request(self, request: Request, *, timeout: float = 5.0) -> dict[str, Any]:
        """HTTP 오류와 JSON 응답을 기존 관리자 오류 경계로 통일한다."""

        try:
            status, body = self._transport(request, timeout)
        except (OSError, URLError, TimeoutError) as exc:
            raise AdminApiError(503, "DEPENDENCY_UNAVAILABLE") from exc
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise AdminApiError(503, "INVALID_RESPONSE") from exc
        if not isinstance(payload, dict):
            raise AdminApiError(503, "INVALID_RESPONSE")
        if status >= 400:
            error = payload.get("error")
            code = error.get("code") if isinstance(error, dict) else payload.get("code")
            raise AdminApiError(status, code if isinstance(code, str) else "ADMIN_ACCESS_DENIED")
        return payload


class DemoAdminApiClient:
    """외부 Backend 없이 관리자 화면을 확인하기 위한 읽기 전용 가상 API다.

    가상 응답은 Backend 관리자 API의 공개 응답 모양만 재현한다. 실제 게임의
    역할·행동·투표·시드 같은 비공개 필드는 포함하지 않아 화면 개발 중에도
    관리자 정보 경계를 동일하게 점검할 수 있다.
    """

    def __init__(self, *, api_key: str = DEMO_API_KEY) -> None:
        """비밀 인증 대신 공개 데모 키의 일치 여부만 시험한다."""

        if not isinstance(api_key, str) or api_key.strip() != DEMO_API_KEY:
            raise AdminApiError(401, "DEMO_KEY_INVALID")

    def preview(self) -> dict[str, Any]:
        """운영 API 계약에 없는 화면 예시를 데모 전용으로 분리한다."""

        return deepcopy(DEMO_PREVIEW)

    def metrics(self, **_: Any) -> dict[str, Any]:
        """통합 운영 분석 화면에서 사용하는 가상 지표를 반환한다."""

        return {"data": {**deepcopy(DEMO_METRICS), "users_total": DEMO_PREVIEW["users_total"],
                         "daily_games": [{"date": row["날짜"], "games_created": row["생성 게임"]}
                                         for row in DEMO_PREVIEW["daily"]]}}

    def role_win_rates(self) -> dict:
        """운영 API와 같은 집계 필드로 고정된 합성 기록의 AI 승률을 반환한다."""

        jobs = {label: key for key, label in JOB_LABELS.items()}
        return {"data": {"items": [{"job": jobs[row["직업"]], "participations": row["참여 수"],
                                    "wins": row["승리 수"],
                                    "win_rate": round(row["승리 수"] / row["참여 수"], 6)}
                                   for row in DEMO_PREVIEW["jobs"]]}}

    def persona_win_rates(self) -> dict:
        """운영 API와 같은 집계 필드로 합성 페르소나 승률을 반환한다."""

        return {"data": {"items": deepcopy(DEMO_PREVIEW["personas"])} }

    def speech_analytics(self, **kwargs: Any) -> dict[str, Any]:
        """화면 확인용 합성 발언 분석을 실제 응답과 같은 구조로 반환한다."""

        limit = int(kwargs.get("limit", 12))
        if not 1 <= limit <= 20:
            raise ValueError("가상 발언 분석 주제 수는 1부터 20까지여야 합니다.")
        payload = deepcopy(DEMO_SPEECH_ANALYTICS)
        payload["topics"] = payload["topics"][:limit]
        visible_topic_ids = {topic["topic_id"] for topic in payload["topics"]}
        for agent in payload["agents"]:
            agent["top_topics"] = [
                topic for topic in agent.get("top_topics", [])
                if topic.get("topic_id") in visible_topic_ids
            ]
        payload["topic_count"] = len(DEMO_SPEECH_ANALYTICS["topics"])
        return {"data": payload}

    def feedback(self, *, feedback_type: str | None = None, rating: int | None = None,
                 cursor: str | None = None, limit: int = 20) -> dict:
        """가상 의견도 실제 API 필드와 커서 규칙으로 조회한다."""

        rows = [{"feedback_id": f"20000000-0000-4000-8000-{i + 1:012d}",
                 "user_id": f"10000000-0000-4000-8000-{i % 300 + 1:012d}",
                 "feedback_type": "GAME" if i % 2 else "GENERAL",
                 "game_id": DEMO_GAMES[i]["game_id"] if i % 2 else None,
                 "rating": row["평점"], "comment": row["의견"], "tags": [],
                 "created_at": "2026-09-07T01:00:00Z"}
                for i, row in enumerate(DEMO_PREVIEW["feedback"])]
        if cursor is not None:
            try:
                cursor = str(UUID(cursor))
            except ValueError as exc:
                raise AdminApiError(422, "INVALID_REQUEST") from exc
            if not any(row["feedback_id"] == cursor for row in rows):
                return {"data": {"items": [], "next_cursor": None}}
        rows = [row for row in reversed(rows)
                if (feedback_type is None or row["feedback_type"] == feedback_type)
                and (rating is None or row["rating"] == rating)
                and (cursor is None or row["feedback_id"] < cursor)]
        return self._page(rows, "feedback_id", limit)

    def audit_logs(self, *, event_type: str | None = None,
                   cursor: str | None = None, limit: int = 20) -> dict:
        """가상 감사 이력은 운영 계약의 이벤트 분류와 ID를 사용한다."""

        events = [event for event in AUDIT_EVENT_LABELS.values() if event is not None]
        rows = [{"audit_id": str(i + 1),
                 "admin_user_id": "00000000-0000-4000-8000-000000000201",
                 "event_type": events[i % len(events)], "target_game_id": None,
                 "request_id": f"30000000-0000-4000-8000-{i + 1:012d}",
                 "created_at": row["시각"].replace(" ", "T") + ":00Z"}
                for i, row in enumerate(DEMO_PREVIEW["logs"])]
        rows = [row for row in reversed(rows)
                if (event_type is None or row["event_type"] == event_type)
                and (cursor is None or int(row["audit_id"]) < int(cursor))]
        return self._page(rows, "audit_id", limit)

    def agent_jobs(
        self, *, game_id: str | UUID | None = None, job_kind: str | None = None,
        status: str | None = None, cursor: str | None = None, limit: int = 20,
    ) -> dict:
        """팀 DB를 변경하지 않고 모든 작업 종류·상태와 페이지 이동을 미리본다."""

        params = _agent_job_params(
            game_id=game_id, job_kind=job_kind, status=status, cursor=cursor, limit=limit,
        )
        kinds = [value for value in AGENT_JOB_KIND_LABELS.values() if value is not None]
        statuses = [value for value in AGENT_JOB_STATUS_LABELS.values() if value is not None]
        rows = []
        for i in range(120):
            kind = kinds[(i // len(statuses)) % len(kinds)]
            job_status = statuses[i % len(statuses)]
            created = datetime(2026, 9, 9, tzinfo=UTC) + timedelta(minutes=i)
            rows.append({
                "job_id": f"50000000-0000-4000-8000-{i + 1:012d}",
                "game_id": DEMO_GAMES[i % 6]["game_id"],
                "player_id": None if kind == "GM_NARRATION"
                else f"60000000-0000-4000-8000-{i % 8 + 1:012d}",
                "player_name": None if kind == "GM_NARRATION" else f"AI {i % 8 + 1}",
                "window_id": f"70000000-0000-4000-8000-{i + 1:012d}",
                "job_kind": kind, "status": job_status, "reserved_state_version": i + 1,
                "failure_code": {"FALLBACK": "PROVIDER_UNAVAILABLE", "STALE": "LEASE_EXPIRED",
                                 "FAILED": "AGENT_DEPENDENCY_ERROR"}.get(job_status),
                "created_at": created.isoformat().replace("+00:00", "Z"),
                "completed_at": None if job_status == "RESERVED"
                else (created + timedelta(seconds=3)).isoformat().replace("+00:00", "Z"),
            })
        cursor_id = params.get("cursor")
        if cursor_id is not None and not any(row["job_id"] == cursor_id for row in rows):
            return {"data": {"items": [], "next_cursor": None}}
        rows = [row for row in reversed(rows)
                if ("game_id" not in params or row["game_id"] == params["game_id"])
                and (job_kind is None or row["job_kind"] == job_kind)
                and (status is None or row["status"] == status)
                and (cursor_id is None or row["job_id"] < cursor_id)]
        return self._page(rows, "job_id", limit)

    def insights_query(self, question: str, *, source_types: list[str] | None = None,
                       rating_lte: int | None = None, from_date: str | None = None,
                       to_date: str | None = None, top_k: int = 5) -> dict[str, Any]:
        """실제 색인 없이도 계획 화면의 근거 답변 흐름을 확인한다."""

        del source_types, rating_lte, from_date, to_date
        normalized_question = " ".join(str(question).split())
        if not 3 <= len(normalized_question) <= 500 or not 1 <= top_k <= 10:
            raise ValueError("가상 관리자 질문 조건이 올바르지 않습니다.")
        rows = [
            {
                "source_type": "FEEDBACK",
                "source_id": "feedback:demo-001",
                "title": "합성 사용자 피드백",
                "snippet": "투표 전 남은 시간과 사건 설명을 더 크게 보여 주면 좋겠습니다.",
                "score": 0.86,
            },
            {
                "source_type": "OPERATIONS_DOC",
                "source_id": "screen-flow:demo-15.2",
                "title": "관리자 화면 흐름도",
                "snippet": "운영 분석 화면은 핵심 KPI와 진영별 결과를 한눈에 표시합니다.",
                "score": 0.74,
            },
        ][:top_k]
        return {"data": {
            "answer": "승인된 자료에서 확인된 내용입니다: "
                      + " ".join(row["snippet"] for row in rows),
            "confidence": "HIGH",
            "has_sufficient_evidence": True,
            "sources": rows,
        }}

    @staticmethod
    def _page(rows: list, id_field: str, limit: int) -> dict:
        """가상 목록도 페이지 한도를 지키며 복사본만 돌려준다."""

        if not 1 <= limit <= 100:
            raise AdminApiError(422, "INVALID_REQUEST")
        return {"data": {"items": deepcopy(rows[:limit]),
                         "next_cursor": rows[limit - 1][id_field] if len(rows) > limit else None}}

    def games(self, *, status: str | None = None, phase: str | None = None,
              cursor: str | None = None, limit: int = 20) -> dict[str, Any]:
        """필터에 묶인 데모 전용 커서로 가상 기록을 빠짐없이 나눠 반환한다."""

        if not 1 <= limit <= 100:
            raise ValueError("게임 목록 한도는 1부터 100까지입니다.")
        items = [game for game in DEMO_GAMES
                 if (status is None or game["status"] == status)
                 and (phase is None or game["phase"] == phase)]
        prefix = f"{status or 'ALL'}:{phase or 'ALL'}:"
        offset = 0
        if cursor is not None:
            if not isinstance(cursor, str) or not cursor.startswith(prefix):
                raise ValueError("가상 목록 커서의 필터가 일치하지 않습니다.")
            position = cursor[len(prefix):]
            if not position.isascii() or not position.isdigit() or len(position) > 8:
                raise ValueError("가상 목록 커서가 올바르지 않습니다.")
            offset = int(position)
            if offset >= len(items):
                raise ValueError("가상 목록 커서가 범위를 벗어났습니다.")
        end = offset + limit
        return {"data": {"items": deepcopy(items[offset:end]),
                         "next_cursor": f"{prefix}{end}" if end < len(items) else None,
                         "total": len(items)}}

    def game_detail(self, game_id: str | UUID) -> dict[str, Any]:
        """선택한 가상 게임의 공개 상세를 반환한다."""

        normalized_id = str(UUID(str(game_id)))
        detail = next(
            (item for item in DEMO_GAME_DETAILS if item["game_id"] == normalized_id),
            None,
        )
        if detail is None:
            raise AdminApiError(404, "GAME_NOT_FOUND")
        return {"data": deepcopy(detail)}


def _build_demo_data() -> tuple[list[dict], list[dict], dict, dict]:
    """고정된 합성 기록에서 KPI를 계산해 목록과 수치가 어긋나지 않게 한다."""

    games, details = [], []
    jobs = {name: {"직업": name, "참여 수": 0, "승리 수": 0}
            for name in ["마피아", "탐정", "의사", "시민"]}
    daily = {}
    for index in range(1200):
        status = (
            "COMPLETED" if index < 900 else "SAVED" if index < 1080
            else "IN_PROGRESS" if index < 1176 else "FAILED"
        )
        day = (date(2026, 8, 9) + timedelta(days=index % 30)).isoformat()
        daily[day] = daily.get(day, 0) + 1
        phase = "RESULT" if status in {"COMPLETED", "FAILED"} else "DAY_DISCUSSION"
        game = {
            "game_id": f"00000000-0000-4000-8000-{index + 1:012d}",
            "status": status, "phase": phase, "player_count": 6 + index % 4,
            "round": 2 + index % 4,
            "owner_user_id": f"10000000-0000-4000-8000-{index % 300 + 1:012d}",
            "updated_at": f"{day}T{index % 24:02d}:00:00Z",
        }
        games.append(game)
        winner = ("CITIZEN" if index % 5 < 3 else "MAFIA") if status == "COMPLETED" else None
        details.append({
            **game,
            "winner": winner,
            "failure_code": "DEPENDENCY_UNAVAILABLE" if status == "FAILED" else None,
        })
        if winner is not None:
            # 합성 좌석에서 사람 한 명을 제외해 AI만 집계한다. 개별 역할은 응답에 남기지 않는다.
            mafia_count = 1 if game["player_count"] < 8 else 2
            seats = (["마피아"] * mafia_count + ["탐정", "의사"]
                     + ["시민"] * (game["player_count"] - mafia_count - 2))
            human_seat = (index // 4) % len(seats)
            for seat, job in enumerate(seats):
                if seat != human_seat:
                    jobs[job]["참여 수"] += 1
                    faction = "MAFIA" if job == "마피아" else "CITIZEN"
                    jobs[job]["승리 수"] += int(faction == winner)
    feedback = [
        {"번호": f"FB-{i + 1:03}", "작성자": f"데모 사용자 {i + 1:02}",
         "평점": rating, "의견": message}
        for i, (rating, message) in enumerate([
            (5, "야간 열차 분위기가 추리와 잘 어울려요."),
            (4, "투표 전 남은 시간을 더 크게 보고 싶어요."),
            (5, "AI마다 말투가 달라 재미있었어요."),
            (3, "게임 규칙을 처음에 더 자세히 알려 주세요."),
            (4, "저장한 게임을 이어 할 수 있어 편해요."),
            (5, "산장 시나리오를 다시 플레이하고 싶어요."),
            (4, "모바일에서 플레이어 목록이 더 짧으면 좋겠어요."),
            (4, "결과 화면의 사건 기록이 도움이 됐어요."),
        ] * 30)
    ]
    logs = [
        {"시각": f"{date(2026, 8, 9) + timedelta(days=i // 6)} {9 + i % 6:02}:00",
         "등급": "WARN" if i % 6 == 4 else "INFO",
         "내용": ["운영 지표 조회 완료", "게임 목록 조회 완료", "공개 게임 상세 조회 완료",
                   "통계 화면 조회 완료", "목록 조회 지연 후 재시도 완료", "피드백 예시 조회 완료"][i % 6]}
        for i in range(180)
    ]
    personas = [
        {"persona_id": persona_id, "persona_name": persona_name,
         "personality_summary": summary, "participations": 0, "wins": 0}
        for persona_id, persona_name, summary in [
            ("CAUTIOUS_ANALYST", "신중한 분석가", "근거를 차분히 쌓고 성급한 결론을 피하는 성격"),
            ("ACTIVE_DEBATER", "적극적인 토론가", "질문과 반론으로 논의를 빠르게 이끄는 성격"),
            ("OBSERVANT_NOTEKEEPER", "관찰형 기록자", "작은 발언과 행동의 변화를 꼼꼼히 기억하는 성격"),
            ("EMOTIONAL_REACTOR", "감정적인 반응가", "놀람과 의심을 솔직하게 표현하는 성격"),
            ("COOPERATIVE_MEDIATOR", "협력형 조정자", "서로 다른 의견을 요약하고 부드럽게 연결하는 성격"),
        ]
    ]
    for index, game in enumerate(games):
        if game["status"] != "COMPLETED":
            continue
        ai_count = game["player_count"] - 1
        for offset in range(ai_count):
            persona = personas[(index + offset) % len(personas)]
            persona["participations"] += 1
            persona["wins"] += int(details[index]["winner"] == ("MAFIA" if offset == 0 and index % 3 else "CITIZEN"))
    for persona in personas:
        persona["win_rate"] = round(persona["wins"] / persona["participations"], 6) if persona["participations"] else 0.0
    preview = {
        "users_total": len({game["owner_user_id"] for game in games}),
        "feedback": feedback,
        "logs": logs,
        "personas": personas,
        "jobs": [
            {**row, "승률 (%)": round(row["승리 수"] / row["참여 수"] * 100, 1)}
            for row in jobs.values()
        ],
        "daily": [
            {"날짜": day, "생성 게임": count} for day, count in sorted(daily.items())
        ],
    }
    completed = [item for item in details if item["status"] == "COMPLETED"]
    metrics = {
        "games_created": len(games), "games_completed": len(completed),
        "games_saved": sum(game["status"] == "SAVED" for game in games),
        "completion_rate": len(completed) / len(games),
        "average_rounds": sum(g["round"] for g in completed) / len(completed),
        "wins_by_faction": {faction: sum(g["winner"] == faction for g in completed)
                            for faction in ["CITIZEN", "MAFIA"]}, "auto_action_count": 120,
        "feedback_average": sum(row["평점"] for row in feedback) / len(feedback),
    }
    return games, details, metrics, preview


DEMO_GAMES, DEMO_GAME_DETAILS, DEMO_METRICS, DEMO_PREVIEW = _build_demo_data()

# 관리자 화면에서 임베딩 기반 도식화 흐름을 확인하기 위한 합성 응답이다.
# 실제 분석 결과·원문·사용자 식별자를 포함하지 않으며 운영 API와 같은 shape만 유지한다.
DEMO_SPEECH_ANALYTICS = {
    "analysis_version": "demo-v1",
    "generated_at": "2026-09-08T02:00:00Z",
    "coverage": {
        "eligible_speeches": 248,
        "analyzed_speeches": 242,
        "embedding_ready": 238,
        "claims_ready": 231,
        "embedding_coverage": 0.9597,
        "claims_coverage": 0.9315,
        "sampled_speeches": 238,
        "sample_limited": False,
    },
    "topics": [
        {
            "topic_id": "topic-001",
            "label": "근거 · 투표 · 수상",
            "speech_count": 86,
            "agent_count": 5,
            "agent_breakdown": [
                {"persona_id": "ACTIVE_DEBATER", "persona_name": "적극적인 토론가", "speech_count": 25, "share": 0.2907},
                {"persona_id": "CAUTIOUS_ANALYST", "persona_name": "신중한 분석가", "speech_count": 22, "share": 0.2558},
                {"persona_id": "OBSERVANT_NOTEKEEPER", "persona_name": "관찰형 기록자", "speech_count": 18, "share": 0.2093},
            ],
            "stance_breakdown": [
                {"stance": "SUSPICION", "count": 47, "share": 0.5109},
                {"stance": "QUESTION", "count": 28, "share": 0.3043},
                {"stance": "DEFENSE", "count": 17, "share": 0.1848},
            ],
            "keywords": [
                {"term": "근거", "speech_count": 54, "occurrence_count": 69, "agent_count": 5},
                {"term": "투표", "speech_count": 43, "occurrence_count": 51, "agent_count": 5},
                {"term": "수상", "speech_count": 37, "occurrence_count": 42, "agent_count": 4},
                {"term": "행동", "speech_count": 31, "occurrence_count": 36, "agent_count": 5},
            ],
            "related_terms": ["근거", "투표", "수상", "행동"],
            "representative": {
                "event_id": "40000000-0000-4000-8000-000000000001",
                "game_id": "00000000-0000-4000-8000-000000000001",
                "persona_id": "CAUTIOUS_ANALYST",
                "persona_name": "신중한 분석가",
                "round": 2,
                "phase": "DAY_DISCUSSION",
                "message": "지금까지 나온 근거와 투표 흐름을 함께 보면 이 선택이 가장 수상합니다.",
                "created_at": "2026-09-08T01:59:00Z",
            },
            "evidence": [
                {
                    "event_id": "40000000-0000-4000-8000-000000000001",
                    "game_id": "00000000-0000-4000-8000-000000000001",
                    "persona_id": "CAUTIOUS_ANALYST",
                    "persona_name": "신중한 분석가",
                    "round": 2,
                    "phase": "DAY_DISCUSSION",
                    "message": "지금까지 나온 근거와 투표 흐름을 함께 보면 이 선택이 가장 수상합니다.",
                    "created_at": "2026-09-08T01:59:00Z",
                },
                {
                    "event_id": "40000000-0000-4000-8000-000000000002",
                    "game_id": "00000000-0000-4000-8000-000000000001",
                    "persona_id": "ACTIVE_DEBATER",
                    "persona_name": "적극적인 토론가",
                    "round": 2,
                    "phase": "DAY_DISCUSSION",
                    "message": "투표 전에 행동 근거를 먼저 설명해 주세요. 설명이 없으면 의심할 수밖에 없습니다.",
                    "created_at": "2026-09-08T02:00:00Z",
                },
            ],
        },
        {
            "topic_id": "topic-002",
            "label": "방어 · 협력",
            "speech_count": 71,
            "agent_count": 4,
            "agent_breakdown": [
                {"persona_id": "COOPERATIVE_MEDIATOR", "persona_name": "협력형 조정자", "speech_count": 26, "share": 0.3662},
                {"persona_id": "EMOTIONAL_REACTOR", "persona_name": "감정적인 반응가", "speech_count": 19, "share": 0.2676},
                {"persona_id": "OBSERVANT_NOTEKEEPER", "persona_name": "관찰형 기록자", "speech_count": 14, "share": 0.1972},
            ],
            "stance_breakdown": [
                {"stance": "DEFENSE", "count": 39, "share": 0.4333},
                {"stance": "QUESTION", "count": 23, "share": 0.2556},
                {"stance": "NEUTRAL", "count": 28, "share": 0.3111},
            ],
            "keywords": [
                {"term": "방어", "speech_count": 41, "occurrence_count": 48, "agent_count": 4},
                {"term": "협력", "speech_count": 34, "occurrence_count": 38, "agent_count": 4},
                {"term": "설명", "speech_count": 29, "occurrence_count": 35, "agent_count": 4},
            ],
            "related_terms": ["방어", "협력", "설명"],
            "representative": {
                "event_id": "40000000-0000-4000-8000-000000000003",
                "game_id": "00000000-0000-4000-8000-000000000002",
                "persona_id": "COOPERATIVE_MEDIATOR",
                "persona_name": "협력형 조정자",
                "round": 1,
                "phase": "DAY_DISCUSSION",
                "message": "서로의 설명을 먼저 맞춰 보면 불필요한 오해를 줄일 수 있습니다.",
                "created_at": "2026-09-08T01:40:00Z",
            },
            "evidence": [],
        },
        {
            "topic_id": "topic-003",
            "label": "조사 · 밤",
            "speech_count": 43,
            "agent_count": 3,
            "agent_breakdown": [
                {"persona_id": "OBSERVANT_NOTEKEEPER", "persona_name": "관찰형 기록자", "speech_count": 19, "share": 0.4419},
                {"persona_id": "CAUTIOUS_ANALYST", "persona_name": "신중한 분석가", "speech_count": 13, "share": 0.3023},
            ],
            "stance_breakdown": [
                {"stance": "QUESTION", "count": 31, "share": 0.5741},
                {"stance": "NEUTRAL", "count": 23, "share": 0.4259},
            ],
            "keywords": [
                {"term": "조사", "speech_count": 25, "occurrence_count": 29, "agent_count": 3},
                {"term": "밤", "speech_count": 22, "occurrence_count": 25, "agent_count": 3},
                {"term": "기록", "speech_count": 18, "occurrence_count": 22, "agent_count": 2},
            ],
            "related_terms": ["조사", "밤", "기록"],
            "representative": {
                "event_id": "40000000-0000-4000-8000-000000000004",
                "game_id": "00000000-0000-4000-8000-000000000003",
                "persona_id": "OBSERVANT_NOTEKEEPER",
                "persona_name": "관찰형 기록자",
                "round": 3,
                "phase": "FINAL_DISCUSSION",
                "message": "지난 밤의 기록과 오늘의 답변이 서로 맞는지 확인하고 싶습니다.",
                "created_at": "2026-09-08T01:20:00Z",
            },
            "evidence": [],
        },
    ],
    "topic_count": 3,
    "agents": [
        {
            "persona_id": "ACTIVE_DEBATER",
            "persona_name": "적극적인 토론가",
            "speech_count": 58,
            "share": 0.2437,
            "top_topics": [{"topic_id": "topic-001", "label": "근거 · 투표 · 수상", "speech_count": 25}],
            "top_keywords": [{"term": "투표", "speech_count": 30, "occurrence_count": 37, "agent_count": 1}, {"term": "근거", "speech_count": 26, "occurrence_count": 31, "agent_count": 1}],
            "stance_breakdown": [{"stance": "SUSPICION", "count": 34, "share": 0.5484}, {"stance": "QUESTION", "count": 28, "share": 0.4516}],
        },
        {
            "persona_id": "CAUTIOUS_ANALYST",
            "persona_name": "신중한 분석가",
            "speech_count": 52,
            "share": 0.2185,
            "top_topics": [{"topic_id": "topic-001", "label": "근거 · 투표 · 수상", "speech_count": 22}, {"topic_id": "topic-003", "label": "조사 · 밤", "speech_count": 13}],
            "top_keywords": [{"term": "근거", "speech_count": 34, "occurrence_count": 41, "agent_count": 1}, {"term": "조사", "speech_count": 16, "occurrence_count": 19, "agent_count": 1}],
            "stance_breakdown": [{"stance": "SUSPICION", "count": 29, "share": 0.5273}, {"stance": "QUESTION", "count": 18, "share": 0.3273}, {"stance": "DEFENSE", "count": 8, "share": 0.1455}],
        },
        {
            "persona_id": "OBSERVANT_NOTEKEEPER",
            "persona_name": "관찰형 기록자",
            "speech_count": 49,
            "share": 0.2059,
            "top_topics": [{"topic_id": "topic-003", "label": "조사 · 밤", "speech_count": 19}, {"topic_id": "topic-001", "label": "근거 · 투표 · 수상", "speech_count": 18}],
            "top_keywords": [{"term": "기록", "speech_count": 24, "occurrence_count": 29, "agent_count": 1}, {"term": "조사", "speech_count": 23, "occurrence_count": 27, "agent_count": 1}],
            "stance_breakdown": [{"stance": "QUESTION", "count": 33, "share": 0.55}, {"stance": "NEUTRAL", "count": 27, "share": 0.45}],
        },
    ],
    "keywords": [
        {"term": "근거", "speech_count": 134, "occurrence_count": 168, "agent_count": 5},
        {"term": "투표", "speech_count": 118, "occurrence_count": 139, "agent_count": 5},
        {"term": "의심", "speech_count": 105, "occurrence_count": 121, "agent_count": 5},
        {"term": "설명", "speech_count": 98, "occurrence_count": 116, "agent_count": 5},
        {"term": "조사", "speech_count": 77, "occurrence_count": 89, "agent_count": 4},
        {"term": "협력", "speech_count": 65, "occurrence_count": 72, "agent_count": 4},
    ],
    "method": {"similarity": "cosine", "threshold": 0.78, "projection_dimensions": 96,
               "sample_limit": 500, "keyword_note": "원문 토큰과 같은 주제의 동시 출현 표현을 표시합니다."},
}


def _send(request: Request, timeout: float) -> tuple[int, bytes]:
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - 관리자 Backend 설정을 사용한다.
            return int(response.status), response.read(256 * 1024)
    except HTTPError as exc:
        return exc.code, exc.read(256 * 1024)
