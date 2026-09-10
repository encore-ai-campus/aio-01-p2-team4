"""기존 snapshot 모듈 이름을 위한 호환 re-export."""

from backend.app.services.game.game_read_service import (
    PostgresGameReadService,
    attach_human_facts,
    initial_record_from_rows,
    list_games,
    list_item,
    read_snapshot,
)

__all__ = [
    "PostgresGameReadService",
    "attach_human_facts",
    "initial_record_from_rows",
    "list_games",
    "list_item",
    "read_snapshot",
]
