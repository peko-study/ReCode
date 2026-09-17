"""Pure goal lifecycle state for the read-only review runtime."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


MAX_GOAL_LENGTH = 4000


class GoalError(Exception):
    """The requested goal state transition is invalid."""


@dataclass
class GoalState:
    condition: str
    iterations: int
    set_at: float
    tokens_at_start: int
    last_reason: str | None = None


@dataclass(frozen=True)
class GoalEvaluation:
    ok: bool
    reason: str
    impossible: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise GoalError("goal evaluation reason cannot be empty")
        if self.ok and self.impossible:
            raise GoalError("goal evaluation cannot be both ok and impossible")


@dataclass(frozen=True)
class StopDecision:
    action: str
    reason: str = ""


class GoalEvaluator(Protocol):
    def evaluate(
        self, condition: str, snapshot: Mapping[str, Any]
    ) -> GoalEvaluation: ...


class GoalController:
    """Evaluate one session-scoped completion goal without performing I/O."""

    def __init__(
        self,
        evaluator: GoalEvaluator,
        block_cap: int = 8,
        events: list[dict[str, Any]] | None = None,
    ) -> None:
        if block_cap < 1:
            raise GoalError("block_cap must be at least 1")
        self.evaluator = evaluator
        self.block_cap = block_cap
        self.events = events if events is not None else []
        self.active: GoalState | None = None
        self.last_status: dict[str, Any] | None = None
        self.consecutive_blocks = 0

    def set_goal(self, condition: str, tokens_at_start: int = 0) -> GoalState:
        condition = condition.strip()
        if not condition:
            raise GoalError("goal condition cannot be empty")
        if len(condition) > MAX_GOAL_LENGTH:
            raise GoalError(
                f"goal condition cannot exceed {MAX_GOAL_LENGTH} characters"
            )
        if self.active is not None:
            self._record(False, False, False, "replaced by a new goal")

        self.active = GoalState(
            condition=condition,
            iterations=0,
            set_at=time.time(),
            tokens_at_start=tokens_at_start,
        )
        self.consecutive_blocks = 0
        self._record(True, False, False, "goal set")
        return self.active

    def clear(self, reason: str = "cleared") -> str:
        if self.active is None:
            return "No goal set"
        condition = self.active.condition
        self._record(False, False, False, reason)
        self.active = None
        self.consecutive_blocks = 0
        return f"Goal cleared: {condition}"

    def status(self, current_tokens: int = 0) -> str:
        if self.active is None:
            if self.last_status and self.last_status["met"]:
                return (
                    f"Goal achieved: {self.last_status['condition']}\n"
                    f"Reason: {self.last_status['reason']}"
                )
            if self.last_status and self.last_status["failed"]:
                return (
                    f"Goal failed: {self.last_status['condition']}\n"
                    f"Reason: {self.last_status['reason']}"
                )
            return "No goal set"

        elapsed = max(0, int(time.time() - self.active.set_at))
        spent = max(0, current_tokens - self.active.tokens_at_start)
        lines = [
            f"Goal active: {self.active.condition}",
            f"Elapsed: {elapsed}s",
            f"Evaluations: {self.active.iterations}",
            f"Tokens: {spent}",
        ]
        if self.active.last_reason:
            lines.append(f"Last reason: {self.active.last_reason}")
        return "\n".join(lines)

    def evaluate(
        self,
        snapshot: Mapping[str, Any],
        background_running: bool = False,
    ) -> StopDecision:
        if self.active is None:
            return StopDecision("allow")
        if background_running:
            return StopDecision("defer", "background work is still running")

        state = self.active
        try:
            evaluation = self.evaluator.evaluate(state.condition, snapshot)
        except Exception as error:
            reason = f"{type(error).__name__}: {error}"
            state.last_reason = reason
            self._record(True, False, False, reason)
            return StopDecision("error", reason)

        if not isinstance(evaluation, GoalEvaluation):
            raise GoalError("goal evaluator must return GoalEvaluation")

        state.iterations += 1
        state.last_reason = evaluation.reason
        if evaluation.ok:
            self._record(False, True, False, evaluation.reason)
            self.active = None
            self.consecutive_blocks = 0
            return StopDecision("achieved", evaluation.reason)
        if evaluation.impossible:
            self._record(False, False, True, evaluation.reason)
            self.active = None
            self.consecutive_blocks = 0
            return StopDecision("failed", evaluation.reason)

        self.consecutive_blocks += 1
        self._record(True, False, False, evaluation.reason)
        if self.consecutive_blocks > self.block_cap:
            return StopDecision(
                "limit",
                f"goal remains active after {self.block_cap} consecutive blocks",
            )
        return StopDecision("block", evaluation.reason)

    def _record(
        self,
        active: bool,
        met: bool,
        failed: bool,
        reason: str,
    ) -> None:
        state = self.active
        event = {
            "type": "goal_status",
            "condition": state.condition if state else "",
            "active": active,
            "met": met,
            "failed": failed,
            "reason": reason,
            "iterations": state.iterations if state else 0,
            "set_at": state.set_at if state else 0.0,
            "duration": max(0.0, time.time() - state.set_at) if state else 0.0,
        }
        self.events.append(event)
        self.last_status = event

    @classmethod
    def restore(
        cls,
        evaluator: GoalEvaluator,
        events: Sequence[Mapping[str, Any]],
        block_cap: int = 8,
    ) -> GoalController:
        controller = cls(
            evaluator=evaluator,
            block_cap=block_cap,
            events=[dict(event) for event in events],
        )
        for event in reversed(events):
            if event.get("type") != "goal_status":
                continue
            controller.last_status = dict(event)
            if event.get("active"):
                controller.active = GoalState(
                    condition=str(event["condition"]),
                    iterations=int(event.get("iterations", 0)),
                    set_at=float(event.get("set_at", time.time())),
                    tokens_at_start=0,
                    last_reason=str(event.get("reason", "")) or None,
                )
            break
        return controller


def review_status_for(decision: StopDecision) -> str:
    """Map internal controller decisions to the stage-0 review status contract."""
    if decision.action == "achieved":
        return "achieved"
    if decision.action == "failed":
        return "failed"
    return "incomplete"
