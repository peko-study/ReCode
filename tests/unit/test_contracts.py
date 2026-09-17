import pytest
from pydantic import ValidationError

from app.domain.contracts import Finding, ReviewAgent, Severity


def finding_payload(**changes):
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


def test_finding_parses_required_review_fields():
    result = Finding.model_validate(finding_payload())

    assert result.severity is Severity.HIGH
    assert result.source_agents == [ReviewAgent.SECURITY]


@pytest.mark.parametrize(
    "changes",
    [
        {"severity": "critical"},
        {"line_start": 0},
        {"confidence": 1.1},
        {"source_agents": []},
        {"evidence": None},
    ],
)
def test_finding_rejects_invalid_schema_values(changes):
    with pytest.raises(ValidationError):
        Finding.model_validate(finding_payload(**changes))
