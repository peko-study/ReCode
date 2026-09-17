"""Deterministic publication checks for structured review reports."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from app.domain.contracts import ReviewAgent, ReviewCompletionSnapshot
from app.runtime.goal import GoalEvaluation


REQUIRED_AGENTS = frozenset(ReviewAgent)


class ReviewCompletionGate:
    """Evaluate review completeness without invoking a model or performing I/O."""

    def evaluate(
        self,
        _condition: str,
        snapshot: Mapping[str, Any],
    ) -> GoalEvaluation:
        try:
            parsed = ReviewCompletionSnapshot.model_validate(snapshot)
        except ValidationError:
            return GoalEvaluation(False, "invalid review completion snapshot", True)

        report = parsed.report
        if not report.prefilter_completed:
            return GoalEvaluation(False, "prefilter has not completed")

        agents = [item.agent for item in report.agent_reports]
        if len(agents) != len(REQUIRED_AGENTS) or set(agents) != REQUIRED_AGENTS:
            return GoalEvaluation(
                False,
                "specialist agent reports are incomplete or duplicated",
            )

        for item in report.agent_reports:
            if not item.completed and not (item.warning and item.warning.strip()):
                return GoalEvaluation(False, f"{item.agent} failed without a warning")

        if not any(item.completed for item in report.agent_reports):
            return GoalEvaluation(False, "all specialist agents failed", True)

        if not report.aggregation_completed:
            return GoalEvaluation(False, "aggregation has not completed")

        for item in report.findings:
            if not all(
                (
                    item.category.strip(),
                    item.file_path.strip(),
                    item.evidence.strip(),
                    item.rule_id.strip(),
                    item.recommendation.strip(),
                    item.source_agents,
                )
            ):
                return GoalEvaluation(False, "finding is missing required evidence")
            if item.line_start not in parsed.added_lines.get(item.file_path, set()):
                return GoalEvaluation(False, "finding line is not an added diff line")

        return GoalEvaluation(True, "review report is publishable")
