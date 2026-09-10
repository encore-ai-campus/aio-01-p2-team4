"""Backend 행동 요청을 FastMCP Tool에 연결하는 등록 모듈."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mafia_game.integrations.engine_http import BackendContextClient


def register_tools(mcp: FastMCP, backend: BackendContextClient) -> None:
    """기존 행동과 HUMAN 전용 능력 Tool을 등록하고 권한·게임 판정은 Backend에 위임한다."""

    @mcp.tool(name="submit_action", description="행동 payload를 Backend에 전달합니다.")
    async def submit_action(
        action: str,
        user_id: str,
        game_id: str,
        expected_state_version: int,
        window_id: str,
        idempotency_key: str,
        player_id: str | None = None,
        target_player_id: str | None = None,
        message: str | None = None,
    ) -> dict[str, object]:
        """행동의 유효성·권한·상태 변경을 직접 판단하지 않고 Backend에 전달한다."""

        return await backend.submit_action(
            action=action,
            user_id=user_id,
            game_id=game_id,
            player_id=player_id,
            expected_state_version=str(expected_state_version),
            window_id=window_id,
            idempotency_key=idempotency_key,
            target_player_id=target_player_id,
            message=message,
        )

    @mcp.tool(
        name="manipulate_vote",
        description="사용자 전용 커스텀 능력으로 본인의 처형 투표 한 장을 3표로 제출합니다.",
    )
    async def manipulate_vote(
        user_id: str,
        game_id: str,
        expected_state_version: int,
        window_id: str,
        idempotency_key: str,
        target_player_id: str,
    ) -> dict[str, object]:
        """능력 ID를 고정하고 actor·가중치를 입력받지 않아 소유 HUMAN의 표만 위임한다."""

        return await backend.submit_action(
            action="VOTE",
            ability_id="vote.triple.v1",
            user_id=user_id,
            game_id=game_id,
            expected_state_version=str(expected_state_version),
            window_id=window_id,
            idempotency_key=idempotency_key,
            target_player_id=target_player_id,
        )

    @mcp.tool(
        name="inspect_special_roles",
        description="첫 밤 이후 사용자 전용 커스텀 능력으로 다른 플레이어의 특수 직업을 읽습니다.",
    )
    async def inspect_special_roles(user_id: str, game_id: str) -> dict[str, object]:
        """조회 권한·첫 밤 해금은 Backend에 맡기며 공개 Resource나 AI 문맥에 섞지 않는다."""

        return await backend.inspect_special_roles(user_id=user_id, game_id=game_id)
