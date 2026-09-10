"""관리자 운영 자료를 안전하게 색인하고 검색하기 위한 공통 도구."""

from __future__ import annotations

from hashlib import blake2b
import math
import re
from typing import Any


# 외부 임베딩 Provider 없이도 개발·테스트에서 같은 결과를 재현할 수 있도록
# 고정 차원의 feature-hashing을 사용한다. 실제 Provider를 붙이는 후속 작업에서도
# 이 차원과 저장 컬럼을 함께 바꿔야 하며, 관리자 질문 API는 현재 이 로컬 방식을 쓴다.
EMBEDDING_DIMENSIONS = 64
_TOKEN_PATTERN = re.compile(r"[0-9A-Za-z가-힣]{2,}")
_UUID_PATTERN = re.compile(
    r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b"
)
_EMAIL_PATTERN = re.compile(r"(?i)\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?\d[\d .()-]{7,}\d)(?!\d)")
_SECRET_PATTERN = re.compile(
    r"(?i)\b(?:api[_ -]?key|password|passwd|secret|token|database[_ -]?url)\s*[:=]\s*[^\s,;]+"
)


def sanitize_knowledge_text(value: Any, *, max_length: int = 2000) -> str:
    """색인 전에 개인 식별자·비밀값·제어 문자를 제거한 텍스트를 만든다.

    원문 피드백은 사용자가 임의의 이메일, 전화번호, UUID 또는 비밀값을 입력할
    수 있으므로 DB에 넣기 전에 같은 정제 경계를 반드시 통과시킨다. 원문을
    복원할 수 있는 마스킹을 사용하지 않고 고정 토큰으로 치환해 검색 결과에도
    민감한 문자열이 되살아나지 않게 한다.
    """

    text = " ".join(str(value or "").replace("\x00", " ").split())
    text = _SECRET_PATTERN.sub("[민감정보 제거]", text)
    text = _EMAIL_PATTERN.sub("[이메일 제거]", text)
    text = _PHONE_PATTERN.sub("[전화번호 제거]", text)
    text = _UUID_PATTERN.sub("[식별자 제거]", text)
    return text[:max_length].strip()


def split_knowledge_chunks(value: Any, *, max_length: int = 500) -> list[str]:
    """정제된 승인 자료를 짧은 문장 묶음으로 분할한다."""

    text = sanitize_knowledge_text(value)
    if not text:
        return []
    sentences = [part.strip() for part in re.split(r"(?<=[.!?。！？])\s+", text) if part.strip()]
    chunks: list[str] = []
    current = ""
    for sentence in sentences or [text]:
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > max_length:
            chunks.append(current)
            current = sentence[:max_length]
        else:
            current = candidate[:max_length]
    if current:
        chunks.append(current)
    return chunks


def local_embedding(value: Any) -> str:
    """텍스트를 PostgreSQL vector literal로 변환한다.

    이 임베딩은 의미를 학습한 모델이 아니라 고정 토큰 해싱 기반의 개발용
    검색 표현이다. 따라서 결과의 신뢰도는 답변의 사실성을 보증하지 않으며,
    운영 도입 전에 검증된 임베딩 Provider로 교체할 수 있도록 별도 함수로
    격리한다. 반환값은 psycopg가 `vector(64)`로 캐스팅할 문자열이다.
    """

    tokens = _TOKEN_PATTERN.findall(sanitize_knowledge_text(value).lower())
    vector = [0.0] * EMBEDDING_DIMENSIONS
    for token in tokens or ["empty"]:
        digest = blake2b(token.encode("utf-8"), digest_size=16).digest()
        first = int.from_bytes(digest[:4], "big") % EMBEDDING_DIMENSIONS
        second = int.from_bytes(digest[4:8], "big") % EMBEDDING_DIMENSIONS
        sign = 1.0 if digest[8] & 1 else -1.0
        vector[first] += sign
        vector[second] += sign * 0.5
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return "[" + ",".join(f"{value / norm:.8f}" for value in vector) + "]"


def compose_insight_result(question: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """검색된 승인 자료만 이용해 추측을 줄인 추출형 관리자 답변을 만든다.

    외부 LLM을 호출하지 않으므로 답변은 상위 근거 문장의 연결로 제한한다.
    점수가 낮거나 근거가 없으면 답변을 만들지 않고 추가 확인 상태를 반환해
    관리자가 검색 결과를 사실로 오해하지 않도록 한다.
    """

    del question  # 현재 추출형 요약은 이미 검색된 행과 그 점수만 사용한다.
    sources = [
        {
            "source_type": row["source_type"],
            "source_id": row["source_id"],
            "title": row["title"],
            "snippet": row["snippet"],
            "score": round(float(row["score"]), 4),
        }
        for row in rows
    ]
    top_score = float(rows[0]["score"]) if rows else 0.0
    sufficient = bool(rows) and top_score >= 0.35
    if not sufficient:
        return {
            "answer": "승인된 자료에서 충분한 근거를 찾지 못했습니다. 검색 조건을 넓히거나 원본 자료를 직접 확인해 주세요.",
            "confidence": "LOW",
            "has_sufficient_evidence": False,
            "sources": sources,
        }
    confidence = "HIGH" if top_score >= 0.72 and len(rows) >= 2 else "MEDIUM"
    snippets = []
    for row in rows[:2]:
        snippet = str(row["snippet"]).strip()
        if snippet and snippet not in snippets:
            snippets.append(snippet)
    return {
        "answer": "승인된 자료에서 확인된 내용입니다: " + " ".join(snippets),
        "confidence": confidence,
        "has_sufficient_evidence": True,
        "sources": sources,
    }
