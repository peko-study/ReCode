"""Typed, side-effect-free contracts for code-change review data."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Severity(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ReviewAgent(StrEnum):
    SECURITY = "security"
    CONSISTENCY = "consistency"
    TEST_IMPACT = "test_impact"


class Finding(BaseModel):
    category: str
    severity: Severity
    file_path: str
    line_start: int = Field(ge=1)
    evidence: str
    rule_id: str
    recommendation: str
    confidence: float = Field(ge=0, le=1)
    source_agents: list[ReviewAgent] = Field(min_length=1)


class AgentReport(BaseModel):
    agent: ReviewAgent
    completed: bool
    findings: list[Finding] = Field(default_factory=list)
    warning: str | None = None


class ReviewReport(BaseModel):
    prefilter_completed: bool
    agent_reports: list[AgentReport]
    findings: list[Finding] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    aggregation_completed: bool


class ReviewCompletionSnapshot(BaseModel):
    report: ReviewReport
    added_lines: dict[str, set[int]]
