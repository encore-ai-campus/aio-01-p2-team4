"""지침 생성 모듈을 FastMCP Prompt에 연결하는 등록 경계."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mafia_game.api.prompts.instructions import role_instruction
from mafia_game.integrations.engine_http import BackendContextClient


def register_prompts(mcp: FastMCP, backend: BackendContextClient) -> None:
    """Prompt 본문은 MCP에서 생성하며 Backend에는 게임 데이터만 위임한다."""

    del backend

    @mcp.prompt(name="agent_instruction", description="역할·현재 단계별 마피아 행동 지침")
    async def agent_instruction(
        game_id: str = "", user_id: str = "",
        role: str = "CITIZEN", phase: str = "DAY_DISCUSSION",
    ) -> str:
        """호환 식별자는 조회에 쓰지 않고 공개 가능한 고정 전략만 제공한다."""

        del game_id, user_id
        return role_instruction(role, phase)
