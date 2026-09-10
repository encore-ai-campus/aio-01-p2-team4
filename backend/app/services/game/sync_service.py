"""기존 sync 모듈 이름을 위한 호환 re-export."""

from backend.app.services.game.event_sync_service import build_operation_batches, read_sync

__all__ = ["build_operation_batches", "read_sync"]
