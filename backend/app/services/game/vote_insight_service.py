"""검증된 공개 발언에서 실시간 핵심 요약과 투표 보조 카드를 읽기 전용으로 만든다."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID
from types import SimpleNamespace
import json
import math
import re

from backend.app.core.errors import ApiError
from backend.app.repositories.speech_analysis_repository import PostgresSpeechAnalysisRepository
from backend.app.repositories.vote_insight_repository import validate_game_source


SIMILARITY_THRESHOLD = 0.88


class VoteInsightService:
    """모델이나 쓰기 저장소 없이 주입된 읽기 저장소와 설정만 사용하는 조회 서비스다."""

    def __init__(self, repository, settings, *, clock=None):
        self.repository = repository
        self.settings = settings
        self.clock = clock or (lambda: datetime.now(UTC))

    def get(self, owner_user_id, game_id, *, window_id, scope="current_discussion", analysis_available=True):
        """예외 원문과 추가 필드를 공개 envelope로 전파하지 않는다."""
        if not analysis_available:
            # 앱 시작 실패는 요청별 설정 view로 반영하여 공유 서비스 설정을 변경하지 않는다.
            settings = SimpleNamespace(speech_analysis_enabled=False,
                                       effective_speech_analysis_version=self.settings.effective_speech_analysis_version)
            return VoteInsightService(self.repository, settings, clock=self.clock).get(
                owner_user_id, game_id, window_id=window_id, scope=scope)
        if scope not in {"current_discussion", "game"}:
            raise ApiError(status_code=422, code="INVALID_REQUEST", message="조회 범위가 올바르지 않습니다.")
        try:
            source = self.repository.load(owner_user_id=owner_user_id, game_id=game_id,
                                          window_id=window_id, scope=scope, settings=self.settings)
            now = self.clock()
            candidates = validate_game_source(source, owner_user_id, game_id, window_id, now)
            return self._project(source, game_id, window_id, scope, candidates, now)
        except ApiError as error:
            # 주입 저장소가 만든 임의 ApiError도 안전한 고정 코드 외에는 공개하지 않는다.
            if error.code == "GAME_NOT_FOUND":
                raise ApiError(status_code=404, code="GAME_NOT_FOUND", message="게임을 찾을 수 없습니다.") from None
            if error.code == "VOTE_INSIGHTS_STALE_WINDOW":
                from backend.app.repositories.vote_insight_repository import stale_window
                raise stale_window() from None
            raise self._unavailable() from None
        except Exception:
            raise self._unavailable() from None

    @staticmethod
    def _unavailable():
        """DB·Provider·검증 실패는 비밀값 없는 하나의 의존성 오류로 축약한다."""
        return ApiError(status_code=503, code="VOTE_INSIGHTS_UNAVAILABLE",
                        message="투표 보조 정보를 일시적으로 조회할 수 없습니다.", retryable=True)

    def _project(self, source, game_id, window_id, scope, candidates, now):
        """현재 후보만 출력하되 사망자를 포함한 공개 발언은 기간 집계에 보존한다."""
        cutoff = source["cutoff_sequence"]
        if type(cutoff) is not int or cutoff < 1:
            raise ValueError("공개 발언 cutoff가 올바르지 않습니다.")
        data = {"game_id": str(game_id), "window_id": str(window_id), "scope": scope,
                "cutoff_sequence": cutoff,
                "analysis_version": self.settings.effective_speech_analysis_version,
                "status": "UNAVAILABLE", "coverage": {"total": 0, "embedding_ready": 0,
                                                       "claims_ready": 0, "failed": 0},
                "similar_claims": [], "suspicion_ranking": [], "candidate_evidence": [],
                "conversation_summary": {"items": [], "total": 0, "omitted": 0}}
        if self.settings.speech_analysis_enabled:
            self._cards(data, source, candidates[:8])
        # 조회 시각과 private 필드는 제외하고 실제 표시하는 요약 변경은 revision에 반영한다.
        data["revision"] = sha256(json.dumps(data, ensure_ascii=False, sort_keys=True,
                                            separators=(",", ":")).encode()).hexdigest()
        data["generated_at"] = now.astimezone(UTC).isoformat().replace("+00:00", "Z")
        return data

    def _cards(self, data, source, candidates):
        """집계 전체값과 화면 근거 상한을 분리하여 반복 발언·잘림으로 수가 변하지 않게 한다."""
        players = {str(p["id"]): p for p in source["players"]}
        buckets = {p: {s: {} for s in ("SUSPICION", "DEFENSE", "QUESTION")} for p in candidates}
        similar, seen, complete = [], set(), 0
        coverage = data["coverage"]
        for row in sorted(source["speeches"], key=lambda r: r["sequence"]):
            if not self._public_source(row, data, source, players):
                continue
            event_id = str(row["event_id"])
            if event_id in seen:
                continue
            seen.add(event_id)
            coverage["total"] += 1
            if not self._binding_matches(row):
                continue
            vector = self._vector(row)
            claims = self._claims(row, players)
            coverage["embedding_ready"] += vector is not None
            coverage["claims_ready"] += claims is not None
            coverage["failed"] += row["embedding_status"] == "FAILED" or row["claims_status"] == "FAILED"
            complete += vector is not None and claims is not None
            evidence = {"event_id": event_id, "player_id": str(row["player_id"]),
                        "message": row["message"], "sequence": row["sequence"],
                        "created_at": row["created_at"].astimezone(UTC).isoformat().replace("+00:00", "Z")}
            # 동일 발언의 반복 주장은 한 번만 표시하고 모델의 핵심 요약과 공개 원문을 분리한다.
            points = list(dict.fromkeys(claim["proposition"].strip() for claim in claims or []))[:3]
            if points:
                summary = data["conversation_summary"]
                summary["total"] += 1
                summary["items"].append({"summary": " · ".join(points), "evidence": [evidence]})
                if len(summary["items"]) > 20:
                    summary["items"].pop(0)
                    summary["omitted"] += 1
            for claim in claims or []:
                target, stance = claim["target_player_id"], claim["stance"]
                if target not in buckets or not self._explicit_claim(claim, row["message"], players):
                    continue
                buckets[target][stance][event_id] = evidence
                topic = self._topic(claim, players)
                if vector is not None and stance != "QUESTION" and topic is not None:
                    similar.append((target, stance, topic, vector, evidence))
        total = coverage["total"]
        data["status"] = ("READY" if complete == total else
                          "PARTIAL" if coverage["embedding_ready"] or coverage["claims_ready"] else
                          "UNAVAILABLE" if total and coverage["failed"] == total else "PENDING")
        if total == 0:
            return
        ranking = []
        for target in candidates:
            groups = buckets[target]
            suspicion = list(groups["SUSPICION"].values())
            data["candidate_evidence"].append({"target_player_id": target,
                "suspicion": suspicion[:5], "defense": list(groups["DEFENSE"].values())[:5],
                "questions": list(groups["QUESTION"].values())[:5]})
            if suspicion:
                ranking.append({"target_player_id": target,
                                "accuser_count": len({e["player_id"] for e in suspicion}),
                                "speech_count": len(suspicion), "evidence": suspicion[:5]})
        ranking.sort(key=lambda r: (-r["accuser_count"], players[r["target_player_id"]]["seat"]))
        previous, rank = None, 0
        for index, row in enumerate(ranking, 1):
            if row["accuser_count"] != previous:
                rank = index
            row["rank"] = rank
            previous = row["accuser_count"]
        data["suspicion_ranking"] = ranking
        data["similar_claims"] = self._similar(similar, players)

    @staticmethod
    def _public_source(row, data, source, players):
        """모든 공개 원문 참조를 다시 확인하고 비공개·타 게임·상한 밖 발언은 버린다."""
        try:
            UUID(str(row["event_id"]))
            UUID(str(row["player_id"]))
        except (ValueError, TypeError, KeyError):
            return False
        player = players.get(str(row.get("player_id")))
        segment = row.get("discussion_segment")
        return (str(row.get("game_id")) == data["game_id"] and player is not None
                and player["kind"] in {"HUMAN", "AI"} and row.get("audience") == "PUBLIC"
                and row.get("audience_player_id") is None
                and row.get("event_type") == "PLAYER_SPOKE"
                and row.get("operation_type") == "APPEND_PUBLIC_EVENT"
                and type(row.get("schema_version")) is int and row["schema_version"] == 1
                and type(row.get("sequence")) is int and 0 < row["sequence"] < data["cutoff_sequence"]
                and isinstance(row.get("message"), str) and bool(row["message"].strip())
                and isinstance(row.get("created_at"), datetime) and row["created_at"].utcoffset() is not None
                and isinstance(segment, str) and re.fullmatch(r"(?:DAY|FINAL)_DISCUSSION:[0-5]", segment) is not None
                and segment.rsplit(":", 1)[1] == str(row.get("source_round"))
                and (data["scope"] == "game" or segment == source["discussion_segment"]))

    def _binding_matches(self, row):
        """분석 준비 상태를 인정하기 전에 원문·모델·버전과 모든 source 참조를 결합한다."""
        settings = self.settings
        return (str(row.get("analysis_event_id")) == str(row["event_id"])
                and str(row.get("analysis_game_id")) == str(row["game_id"])
                and str(row.get("analysis_player_id")) == str(row["player_id"])
                and row.get("source_sequence") == row["sequence"]
                and row.get("analysis_segment") == row["discussion_segment"]
                and row.get("analysis_round") == row["source_round"]
                and row.get("content_hash") == sha256(row["message"].encode()).hexdigest()
                and row.get("analysis_version") == settings.effective_speech_analysis_version
                and row.get("embedding_model") == settings.speech_analysis_embedding_model
                and row.get("dimensions") == settings.speech_analysis_dimensions
                and row.get("claims_model") == settings.speech_analysis_claims_model)

    def _vector(self, row):
        """overflow·NaN·영벡터를 배제하고 안정적인 단위벡터로 cosine을 계산한다."""
        if row.get("embedding_status") != "READY":
            return None
        try:
            values = PostgresSpeechAnalysisRepository._vector(row.get("embedding"), self.settings.speech_analysis_dimensions)
            scale = max(abs(v) for v in values)
            scaled = [v / scale for v in values]
            norm = math.sqrt(math.fsum(v * v for v in scaled))
            return [v / norm for v in scaled]
        except (ValueError, TypeError, OverflowError):
            return None

    @staticmethod
    def _claims(row, players):
        """저장된 claims에도 폐쇄형 구조·같은 게임·정확한 substring 검증을 적용한다."""
        if row.get("claims_status") != "READY":
            return None
        try:
            return PostgresSpeechAnalysisRepository._claims(row.get("claims"), row["message"], set(players))
        except (ValueError, TypeError, KeyError):
            return None

    @staticmethod
    def _explicit_claim(claim, message, players):
        """원문 전체에서 단일 대상과 명시 입장을 확인하고 인용·철회·부정을 보류한다.

        모델 분류만으로 의심을 만들지 않으며 substring 바깥의 반대 문맥도 검사한다.
        보수적인 한국어 표지는 품질 평가 후 확장할 수 있고 지원 밖 표현은 보류한다.
        """
        target = claim["target_player_id"]
        name = players[target]["display_name"]
        if (not isinstance(name, str) or not name
                or sum(p["display_name"] == name for p in players.values()) != 1):
            return False
        if VoteInsightService._mentioned(claim["quote"], players) != {target}:
            return False
        if VoteInsightService._mentioned(message, players) != {target}:
            return False
        if VoteInsightService._ambiguous(message):
            return False
        stance = claim["stance"]
        signals = VoteInsightService._signals(message)
        if stance == "QUESTION":
            return "?" in message and not signals
        return ("?" not in message and signals == {stance}
                and VoteInsightService._signals(claim["quote"]) == {stance})

    @staticmethod
    def _mentioned(text, players):
        """이름과 좌석 참조를 같은 UUID로 해소하고 알 수 없는 좌석은 별도 표지로 남긴다."""
        found = set()
        for identifier, player in players.items():
            name = player["display_name"]
            if name and re.search(r"(?<![가-힣A-Za-z0-9])" + re.escape(name)
                                  + r"(?=은|는|이|가|을|를|의|와|과|도|만|에게|씨|님|\s|[,.!?]|$)", text):
                found.add(identifier)
        seats = {str(p["seat"]): identifier for identifier, p in players.items()}
        for seat in re.findall(r"(?<![0-9])([0-9]+)번(?=\s|플레이어|은|는|이|가|을|를|의|와|과|도|만|에게|[,.!?]|$)", text):
            found.add(seats.get(seat, "UNKNOWN_SEAT"))
        return found

    @staticmethod
    def _defense_normalized(text):
        """마피아라는 역할을 명시적으로 부정하는 옹호만 안전 표지로 정규화한다.

        부정문 일반을 긍정으로 바꾸지 않고 원문은 출력용으로 그대로 보존한다.
        뒤따르는 추가 부정·인용은 이후 전체 문맥 검사에서 계속 거부한다.
        """
        return re.sub(r"마피아(?:가|는)?\s*(?:아니(?:야|다|에요)?|아닙니다|아님)(?=\s|[.!?,]|$)", "무고", text)

    @staticmethod
    def _ambiguous(text):
        """인용·전언·철회·부정 문맥은 긍정 표지와 함께 있어도 자동 집계하지 않는다."""
        text = VoteInsightService._defense_normalized(text)
        text = re.sub(r"앞뒤가? ?맞지 않", "모순", text)
        return re.search(r"[\"'‘’“”「」『』]|라고|다는 말|다던|대요|인용|철회|취소|"
                         r"아니|않|못 믿|안 믿|의심하지|수상하지|무고하지|"
                         r"그러나|하지만|반면|오히려", text) is not None

    @staticmethod
    def _signals(text):
        """반대 입장의 표지가 함께 나타나면 단일 stance 확인에 실패하게 한다."""
        text = VoteInsightService._defense_normalized(text)
        result = set()
        if re.search(r"의심|수상|앞뒤가? ?맞지|모순|일관.*없|거짓|말.*바뀌|진술.*바뀌", text):
            result.add("SUSPICION")
        if re.search(r"무고|옹호|믿습니다|믿어|일치|일관.*있|타당|신뢰", text):
            result.add("DEFENSE")
        return result

    @staticmethod
    def _topic(claim, players):
        """원문과 모델 주장에서 논점·입장·숫자 근거가 모두 확인된 경우만 묶음 후보로 쓴다."""
        quote, proposition = claim["quote"], claim["proposition"]
        projected = {**claim, "quote": proposition}
        if not VoteInsightService._explicit_claim(projected, proposition, players):
            return None
        if VoteInsightService._signals(proposition) != {claim["stance"]}:
            return None
        patterns = {"알리바이": r"알리바이", "역할 주장": r"역할|직업|경찰|의사|탐정|시민|마피아",
                    "진술 변화": r"진술|말.*바뀌|말.*바꿔|말.*달라|설명.*바뀌"}
        topics = [{name for name, pattern in patterns.items() if re.search(pattern, text)}
                  for text in (quote, proposition)]
        if len(topics[0]) != 1 or topics[0] != topics[1]:
            return None
        # 시각·횟수 등 수치가 다르면 같은 논점이어도 같은 구체 주장이라고 추정하지 않는다.
        numbers = [tuple(re.findall(r"\d+(?:[.:]\d+)*", re.sub(r"(?<![0-9])[0-9]+번", "", text)))
                   for text in (quote, proposition)]
        if numbers[0] != numbers[1]:
            return None
        anchors = [tuple(sorted(set(re.findall(r"경찰|의사|탐정|시민|마피아|시간|시각|장소|현장|위치", text))))
                   for text in (quote, proposition)]
        if anchors[0] != anchors[1]:
            return None
        return (next(iter(topics[0])), numbers[0], anchors[0])

    @staticmethod
    def _similar(items, players):
        """동일 논점·입장을 확인한 다른 AI의 전문 임베딩 후보를 정확 cosine으로 묶는다."""
        groups = {}
        for target, stance, topic, vector, evidence in items:
            groups.setdefault((target, stance, topic), {})[evidence["event_id"]] = (vector, evidence)
        result = []
        for (target, stance, topic), group in groups.items():
            clusters = []
            for vector, evidence in group.values():
                for cluster in clusters:
                    # 연결 성분만 합치면 A-B, B-C를 통해 서로 다른 A-C까지 묶인다.
                    # 한 카드의 모든 발언 쌍이 threshold를 만족하는 complete-link를 사용한다.
                    if all(math.fsum(a * b for a, b in zip(vector, other)) >= SIMILARITY_THRESHOLD
                           for other, _ in cluster):
                        cluster.append((vector, evidence))
                        break
                else:
                    clusters.append([(vector, evidence)])
            for cluster in clusters:
                evidence = sorted((e for _, e in cluster), key=lambda e: e["sequence"])
                if len({e["player_id"] for e in evidence}) < 2:
                    continue
                # 표시 상한에 동일 화자의 반복만 남지 않도록 먼저 화자별 첫 근거를 고른다.
                representatives = {}
                for item in evidence:
                    representatives.setdefault(item["player_id"], item)
                shown = list(representatives.values())[:5]
                shown_ids = {e["event_id"] for e in shown}
                shown.extend(e for e in evidence if e["event_id"] not in shown_ids)
                shown = sorted(shown[:5], key=lambda e: e["sequence"])
                result.append({"player_ids": sorted({e["player_id"] for e in shown}, key=lambda p: players[p]["seat"]),
                               "target_player_id": target,
                               "claim": f"{topic[0]}에 관한 유사한 {'의심' if stance == 'SUSPICION' else '옹호'} 발언",
                               "evidence": shown})
        return result[:8]
