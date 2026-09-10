"""검증된 엔진 operation을 GameEngine facade로 재생하는 규칙."""

from __future__ import annotations

from backend.app.game_engine.errors import RuleViolation
from backend.app.game_engine.rules.night_rules import ability_action
from backend.app.models.game_state import EngineOperation, GameState


def apply_operation(engine, state: GameState, operation: EngineOperation) -> None:
    """내부 operation 하나를 기존 엔진 public 명령으로 적용한다."""

    command = operation.command
    if command == "BEGIN_GAME":
        engine.begin_game(state)
    elif command == "SPEAK":
        engine.speak(state, operation.actor_id, operation.text or "")
    elif command == "PASS":
        engine.pass_turn(state, operation.actor_id)
    elif command == "SUBMIT_NIGHT_ACTION":
        if operation.target_id is None:
            raise RuleViolation("TARGET_REQUIRED")
        # 구형 NULL 기록은 역할 기반 복원을 유지하고 새 능력 기록은 보유 여부까지 검증한다.
        action = (
            ability_action(state, operation.actor_id, operation.ability_id)
            if operation.ability_id is not None
            else engine._role_action(state, operation.actor_id)
        )
        engine.submit_night_action(state, operation.actor_id, action, operation.target_id)
    elif command == "SUBMIT_VOTE":
        if operation.target_id is None:
            raise RuleViolation("TARGET_REQUIRED")
        engine.submit_vote(state, operation.actor_id, operation.target_id, ability_id=operation.ability_id)
    elif command == "RESOLVE_NIGHT":
        engine.resolve_night(state, force=True)
    elif command in {"RESOLVE_VOTE", "RESOLVE_REVOTE"}:
        engine.resolve_vote(state, force=True)
    elif command == "SAVE_AND_EXIT":
        engine.save(state, state.remaining_ms_on_save or 0)
    elif command == "RESUME":
        engine.resume(state)
    elif command == "FINAL_DISCUSSION":
        engine.advance_final_discussion(state)
    elif command == "FINAL_ACCUSATION":
        if operation.target_id is None:
            raise RuleViolation("TARGET_REQUIRED")
        engine.submit_final_accusation(state, operation.actor_id, operation.target_id)
    elif command == "RESOLVE_FINAL_ACCUSATION":
        engine.resolve_final_accusation(state, force=True)
    else:
        raise RuleViolation("REPLAY_COMMAND_INVALID")
