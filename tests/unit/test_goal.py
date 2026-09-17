from collections import deque

import pytest

from app.runtime.goal import GoalController, GoalEvaluation, GoalError, review_status_for


class QueueEvaluator:
    def __init__(self, results):
        self.results = deque(results)
        self.calls = []

    def evaluate(self, condition, snapshot):
        self.calls.append((condition, snapshot))
        result = self.results.popleft()
        if isinstance(result, Exception):
            raise result
        return result


def controller_for(*results, block_cap=2):
    controller = GoalController(QueueEvaluator(results), block_cap=block_cap)
    controller.set_goal("report is complete", tokens_at_start=17)
    return controller


def test_goal_state_records_event_and_rejects_blank_condition():
    controller = GoalController(QueueEvaluator([]))
    state = controller.set_goal("report is complete", tokens_at_start=17)
    event = controller.events[-1]
    assert {key: event[key] for key in event if key != "duration"} == {
        "type": "goal_status",
        "condition": "report is complete",
        "active": True,
        "met": False,
        "failed": False,
        "reason": "goal set",
        "iterations": 0,
        "set_at": state.set_at,
    }
    assert event["duration"] >= 0
    with pytest.raises(GoalError, match="cannot be empty"):
        controller.set_goal("  ")


def test_clear_records_a_final_non_failure_event():
    controller = controller_for()
    assert controller.clear("cancelled by caller") == "Goal cleared: report is complete"
    assert controller.active is None
    assert controller.events[-1]["active"] is False
    assert controller.events[-1]["failed"] is False
    assert controller.events[-1]["reason"] == "cancelled by caller"


@pytest.mark.parametrize(
    ("evaluation", "expected_action", "expected_status"),
    [
        (GoalEvaluation(True, "all evidence is valid"), "achieved", "achieved"),
        (GoalEvaluation(False, "diff is invalid", True), "failed", "failed"),
        (GoalEvaluation(False, "test report is missing"), "block", "incomplete"),
    ],
)
def test_evaluation_maps_to_publishable_review_status(
    evaluation, expected_action, expected_status
):
    controller = controller_for(evaluation)
    decision = controller.evaluate({"aggregate_complete": evaluation.ok})
    assert decision.action == expected_action
    assert review_status_for(decision) == expected_status
    assert (controller.active is None) is (expected_action in {"achieved", "failed"})


def test_limit_defer_and_error_are_incomplete_and_keep_goal_active():
    controller = controller_for(
        GoalEvaluation(False, "missing"),
        GoalEvaluation(False, "missing"),
        GoalEvaluation(False, "missing"),
        block_cap=2,
    )
    assert controller.evaluate({}).action == "block"
    assert controller.evaluate({}).action == "block"
    limited = controller.evaluate({})
    assert limited.action == "limit"
    assert review_status_for(limited) == "incomplete"
    assert controller.active is not None

    evaluator = QueueEvaluator([GoalEvaluation(True, "unused")])
    deferred = GoalController(evaluator)
    deferred.set_goal("report is complete")
    assert deferred.evaluate({}, background_running=True).action == "defer"
    assert evaluator.calls == []

    failed_evaluator = controller_for(RuntimeError("runner unavailable"))
    errored = failed_evaluator.evaluate({})
    assert errored == type(errored)("error", "RuntimeError: runner unavailable")
    assert review_status_for(errored) == "incomplete"
    assert failed_evaluator.active is not None


def test_restore_continues_active_goal_but_not_a_completed_goal():
    active_event = {
        "type": "goal_status",
        "condition": "report is complete",
        "active": True,
        "met": False,
        "failed": False,
        "reason": "missing test report",
        "iterations": 3,
        "set_at": 100.0,
    }
    restored = GoalController.restore(
        QueueEvaluator([GoalEvaluation(True, "complete after resume")]), [active_event]
    )
    assert restored.active is not None
    assert restored.active.iterations == 3
    assert restored.evaluate({}).action == "achieved"

    completed = GoalController.restore(
        QueueEvaluator([]),
        [{**active_event, "active": False, "met": True, "reason": "complete"}],
    )
    assert completed.active is None
    assert completed.status() == "Goal achieved: report is complete\nReason: complete"
