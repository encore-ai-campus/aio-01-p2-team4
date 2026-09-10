"""read-only 관리자 API의 접근 제어·조회·감사 흐름."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from uuid import UUID

from backend.app.core.errors import ApiError
from backend.app.repositories.admin_repository import AdminRepository
from backend.app.services.admin_knowledge import compose_insight_result


def parse_admin_allowlist(values: str | Iterable[str] | None) -> frozenset[UUID]:
    """관리자 UUID 목록을 검증한다.

    빈 목록뿐 아니라 한 건이라도 잘못된 값이 있으면 전체를 비운다. 일부만
    허용하면 운영자가 설정을 잘못 입력했을 때 예상하지 못한 계정만 관리자 권한을
    얻을 수 있으므로 정본의 fail-closed 규칙을 따른다.
    """

    if values is None:
        return frozenset()
    if isinstance(values, str):
        candidates = values.split(",")
    else:
        candidates = list(values)
    candidates = [candidate.strip() for candidate in candidates]
    if not candidates or any(not candidate for candidate in candidates):
        return frozenset()
    parsed: set[UUID] = set()
    for candidate in candidates:
        try:
            value = UUID(candidate)
        except (ValueError, AttributeError):
            return frozenset()
        if value.version != 4 or str(value) != candidate.lower():
            return frozenset()
        parsed.add(value)
    return frozenset(parsed)


class AdminService:
    """관리자 allowlist를 통과한 read-only 조회만 실행한다."""

    def __init__(self, repository: AdminRepository, allowlist: str | Iterable[str] | None):
        self.repository = repository
        self.allowlist = parse_admin_allowlist(allowlist)

    def require_admin(self, admin_user_id: UUID) -> None:
        """허용 목록이 비어 있거나 UUID가 없으면 항상 같은 403을 반환한다."""

        if admin_user_id not in self.allowlist:
            raise ApiError(
                status_code=403,
                code="ADMIN_ACCESS_DENIED",
                message="관리자 접근 권한이 없습니다.",
            )

    def list_games(
        self,
        admin_user_id: UUID,
        *,
        status: str | None,
        phase: str | None,
        cursor: str | None,
        limit: int,
        request_id: UUID,
    ) -> dict[str, object]:
        """관리자 목록을 읽고 성공한 조회 흔적만 append한다."""

        self.require_admin(admin_user_id)
        items, next_cursor = self._read(lambda: self.repository.list_games(
            status=status, phase=phase, cursor=cursor, limit=limit
        ))
        self._audit(admin_user_id, "ADMIN_LIST_GAMES", None, request_id)
        return {"items": items, "next_cursor": next_cursor}

    def get_game(
        self,
        admin_user_id: UUID,
        game_id: UUID,
        *,
        request_id: UUID,
    ) -> dict[str, object]:
        """게임 상세에서 공개 진행 정보만 반환한다."""

        self.require_admin(admin_user_id)
        data = self._read(lambda: self.repository.get_game(game_id))
        if data is None:
            raise ApiError(
                status_code=404,
                code="GAME_NOT_FOUND",
                message="게임을 찾을 수 없습니다.",
            )
        self._audit(admin_user_id, "ADMIN_GET_GAME", game_id, request_id)
        return data

    def metrics(
        self,
        admin_user_id: UUID,
        *,
        from_time: datetime | None,
        to_time: datetime | None,
        request_id: UUID,
    ) -> dict[str, object]:
        """문서에 정의된 운영 지표를 읽고 LLM 비용·prompt를 반환하지 않는다."""

        self.require_admin(admin_user_id)
        data = self._read(lambda: self.repository.metrics(from_time=from_time, to_time=to_time))
        self._audit(admin_user_id, "ADMIN_GET_METRICS", None, request_id)
        return data

    def role_win_rates(self, admin_user_id: UUID, *, from_time: datetime | None,
                       to_time: datetime | None, request_id: UUID) -> dict:
        """완료된 게임의 직업 집계만 조회한 뒤 접근 이력을 저장한다."""

        self.require_admin(admin_user_id)
        items = self._read(lambda: self.repository.role_win_rates(
            from_time=from_time, to_time=to_time))
        self._audit(admin_user_id, "ADMIN_GET_ROLE_WIN_RATES", None, request_id)
        return {"items": items}

    def persona_win_rates(self, admin_user_id: UUID, *, from_time: datetime | None,
                          to_time: datetime | None, request_id: UUID) -> dict:
        """완료 게임의 AI 페르소나 집계만 조회한 뒤 접근 이력을 저장한다."""

        self.require_admin(admin_user_id)
        items = self._read(lambda: self.repository.persona_win_rates(
            from_time=from_time, to_time=to_time))
        self._audit(admin_user_id, "ADMIN_GET_PERSONA_WIN_RATES", None, request_id)
        return {"items": items}

    def speech_analytics(
        self,
        admin_user_id: UUID,
        *,
        from_time: datetime | None,
        to_time: datetime | None,
        game_id: UUID | None,
        persona_id: str | None,
        round_number: int | None,
        analysis_version: str | None,
        topic_limit: int,
        request_id: UUID,
    ) -> dict:
        """공개 AI 발언 집계를 조회하고 성공한 요청만 감사 기록에 남긴다."""

        self.require_admin(admin_user_id)
        data = self._read(lambda: self.repository.speech_analytics(
            from_time=from_time,
            to_time=to_time,
            game_id=game_id,
            persona_id=persona_id,
            round_number=round_number,
            analysis_version=analysis_version,
            topic_limit=topic_limit,
        ))
        self._audit(admin_user_id, "ADMIN_GET_SPEECH_ANALYTICS", game_id, request_id)
        return data

    def list_feedback(self, admin_user_id: UUID, *, feedback_type: str | None,
                      rating: int | None, cursor: UUID | None, limit: int,
                      request_id: UUID) -> dict:
        """허용된 관리자만 사용자 피드백을 페이지 단위로 조회한다."""

        self.require_admin(admin_user_id)
        items, next_cursor = self._read(lambda: self.repository.list_feedback(
            feedback_type=feedback_type, rating=rating, cursor=cursor, limit=limit))
        self._audit(admin_user_id, "ADMIN_LIST_FEEDBACK", None, request_id)
        return {"items": items, "next_cursor": next_cursor}

    def list_audit_logs(self, admin_user_id: UUID, *, event_type: str | None,
                        cursor: int | None, limit: int, request_id: UUID) -> dict:
        """조회 결과를 얻은 다음 현재 요청의 감사 이력을 추가한다."""

        self.require_admin(admin_user_id)
        items, next_cursor = self._read(lambda: self.repository.list_audit_logs(
            event_type=event_type, cursor=cursor, limit=limit))
        self._audit(admin_user_id, "ADMIN_LIST_AUDIT_LOGS", None, request_id)
        return {"items": items, "next_cursor": next_cursor}

    def list_agent_jobs(
        self, admin_user_id: UUID, *, game_id: UUID | None, job_kind: str | None,
        status: str | None, cursor: UUID | None, limit: int, request_id: UUID,
    ) -> dict:
        """관리자에게 작업 메타데이터를 제공하고 해당 조회의 감사 기록을 남긴다."""

        self.require_admin(admin_user_id)
        items, next_cursor = self._read(lambda: self.repository.list_agent_jobs(
            game_id=game_id, job_kind=job_kind, status=status, cursor=cursor, limit=limit,
        ))
        self._audit(admin_user_id, "ADMIN_LIST_AGENT_JOBS", game_id, request_id)
        return {"items": items, "next_cursor": next_cursor}

    def query_insights(
        self,
        admin_user_id: UUID,
        *,
        question: str,
        source_types: list[str],
        rating_lte: int | None,
        from_time: datetime | None,
        to_time: datetime | None,
        top_k: int,
        request_id: UUID,
    ) -> dict:
        """승인 자료를 검색해 근거·신뢰도를 반환하고 질문을 감사 기록한다.

        검색은 색인 테이블을 읽기만 하며 게임 command, 문서 변경, 외부 LLM
        호출을 하지 않는다. 저장소가 반환한 정제된 청크만 추출형 요약에 사용해
        private context가 관리자 답변으로 섞이지 않도록 한다.
        """

        self.require_admin(admin_user_id)
        rows = self._read(lambda: self.repository.search_knowledge(
            question=question,
            source_types=source_types,
            rating_lte=rating_lte,
            from_time=from_time,
            to_time=to_time,
            top_k=top_k,
        ))
        result = compose_insight_result(question, rows)
        self._audit(admin_user_id, "ADMIN_QUERY_INSIGHTS", None, request_id)
        return result

    @staticmethod
    def _read(operation: Callable):
        """DB 오류 원문이나 접속 정보를 API 응답으로 전달하지 않는다."""

        try:
            return operation()
        except Exception as exc:
            raise ApiError(status_code=503, code="DEPENDENCY_UNAVAILABLE",
                           message="관리자 정보를 조회할 수 없습니다.", retryable=True) from exc

    def _audit(
        self,
        admin_user_id: UUID,
        action: str,
        target_game_id: UUID | None,
        request_id: UUID,
    ) -> None:
        """감사 저장 실패를 성공 응답으로 숨기지 않는다."""

        try:
            self.repository.append_audit(
                admin_user_id=admin_user_id,
                action=action,
                target_game_id=target_game_id,
                request_id=request_id,
            )
        except Exception as exc:
            raise ApiError(
                status_code=503,
                code="DEPENDENCY_UNAVAILABLE",
                message="관리자 감사 기록을 저장할 수 없습니다.",
                retryable=True,
            ) from exc
