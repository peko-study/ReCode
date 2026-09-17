"""Goal-controller adapter for deterministic review publication decisions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.review.completion_gate import ReviewCompletionGate
from app.runtime.goal import GoalController, StopDecision


DEFAULT_REVIEW_GOAL = "review report is publishable"


class ReviewGoalController(GoalController):
    """Start and evaluate the fixed completion goal for one review report."""

    def __init__(self, block_cap: int = 8) -> None:
        super().__init__(ReviewCompletionGate(), block_cap=block_cap)
        self.set_goal(DEFAULT_REVIEW_GOAL)

    def evaluate_review(
        self,
        snapshot: Mapping[str, Any],
        background_running: bool = False,
    ) -> StopDecision:
        return self.evaluate(snapshot, background_running=background_running)
