from app.review.completion_gate import ReviewCompletionGate


def finding(**changes):
    payload = {
        "category": "security",
        "severity": "high",
        "file_path": "app/users.py",
        "line_start": 12,
        "evidence": "query uses f-string",
        "rule_id": "SEC-001",
        "recommendation": "use parameters",
        "confidence": 0.9,
        "source_agents": ["security"],
    }
    payload.update(changes)
    return payload


def snapshot(**changes):
    report = {
        "prefilter_completed": True,
        "agent_reports": [
            {"agent": "security", "completed": True},
            {"agent": "consistency", "completed": True},
            {"agent": "test_impact", "completed": True},
        ],
        "findings": [finding()],
        "warnings": [],
        "aggregation_completed": True,
    }
    report.update(changes)
    return {"report": report, "added_lines": {"app/users.py": {12}}}


def action(value):
    evaluation = ReviewCompletionGate().evaluate("review report is publishable", value)
    if evaluation.ok:
        return "achieved"
    if evaluation.impossible:
        return "failed"
    return "block"


def test_complete_high_risk_report_is_achieved():
    assert action(snapshot()) == "achieved"


def test_missing_agent_prefilter_evidence_and_line_block():
    reports = snapshot()["report"]["agent_reports"][:2]

    assert action(snapshot(agent_reports=reports)) == "block"
    assert action(snapshot(prefilter_completed=False)) == "block"
    assert action(snapshot(findings=[finding(evidence="")])) == "block"
    assert action(snapshot(findings=[finding(line_start=13)])) == "block"


def test_warning_allows_one_failure_but_not_unexplained_or_all_failures():
    reports = snapshot()["report"]["agent_reports"]
    reports[2] = {"agent": "test_impact", "completed": False, "warning": "timeout"}
    assert action(snapshot(agent_reports=reports)) == "achieved"

    reports[2] = {"agent": "test_impact", "completed": False}
    assert action(snapshot(agent_reports=reports)) == "block"

    all_failed = [
        {"agent": name, "completed": False, "warning": "timeout"}
        for name in ("security", "consistency", "test_impact")
    ]
    assert action(snapshot(agent_reports=all_failed)) == "failed"


def test_invalid_snapshot_fails():
    assert action({"report": {}, "added_lines": {}}) == "failed"
