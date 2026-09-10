"""비밀정보를 기록하지 않는 Backend 기본 로깅 설정."""

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import RLock


_progress_lock = RLock()


class _ImportantProgressFilter(logging.Filter):
    """터미널에만 주요 결과를 남기고 파일·UI의 상세 진행 기록은 건드리지 않는다."""

    _stages = frozenset({
        "CREATED", "BEGIN_GAME", "SAVE_AND_EXIT", "RESUME", "PHASE_CHANGED",
        "COMPLETED", "FALLBACK", "FAILED", "WORKER_FAILED",
    })

    def filter(self, record: logging.LogRecord) -> bool:
        """이미 정제된 진행 JSON을 선별하며 경고·오류는 형식에 관계없이 보존한다."""

        if record.levelno >= logging.WARNING:
            return True
        try:
            entry = json.loads(record.getMessage())
        except (TypeError, ValueError):
            return False
        if not isinstance(entry, dict) or not isinstance(entry.get("stage"), str):
            return False
        return entry["stage"] in self._stages or (
            entry["stage"] == "APPLIED" and entry.get("action") == "SPEAK"
        )


class _FailedAccessFilter(logging.Filter):
    """주기적인 정상 HTTP 접근 기록을 줄이면서 실패 응답과 서버 경고를 보존한다."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Uvicorn의 구조화 인자에서 상태 코드만 확인하고 URL 문자열은 해석하지 않는다."""

        if record.levelno >= logging.WARNING:
            return True
        args = record.args
        return (isinstance(args, tuple) and len(args) == 5
                and type(args[4]) is int and 400 <= args[4] <= 599)


class _QuietRotatingFileHandler(RotatingFileHandler):
    """디스크·회전 실패 시 원문 record나 예외를 stderr에 재출력하지 않는다."""

    def handleError(self, record: logging.LogRecord) -> None:
        pass


def progress_logger() -> logging.Logger:
    """터미널·5 MiB 순환 파일을 한 번만 구성하고 파일 장애를 격리한다."""

    with _progress_lock:
        logger = logging.getLogger("backend.game_progress")
        if getattr(logger, "_progress_configured", False):
            return logger
        logger.setLevel(logging.INFO)
        logger.propagate = False
        terminal = logging.StreamHandler()
        terminal.setFormatter(logging.Formatter("%(message)s"))
        terminal.addFilter(_ImportantProgressFilter())
        logger.addHandler(terminal)
        try:
            directory = Path(__file__).resolve().parents[2] / "logs"
            directory.mkdir(exist_ok=True)
            handler = _QuietRotatingFileHandler(directory / "game-progress.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(handler)
        except OSError:
            # 로그 디렉터리가 읽기 전용이어도 게임의 저장·진행은 계속 허용한다.
            pass
        logger._progress_configured = True
        return logger


def configure_logging() -> None:
    """기본 포맷과 Backend의 소음 억제를 적용하되 서버 기동·경고·오류는 보존한다."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    for name in ("httpx", "httpcore", "mcp"):
        logging.getLogger(name).setLevel(logging.WARNING)
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, _FailedAccessFilter) for item in access.filters):
        access.addFilter(_FailedAccessFilter())
    progress_logger()
