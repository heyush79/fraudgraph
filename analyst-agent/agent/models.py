"""The agent's state and its report contract (LLD §6.1, §6.2)."""
from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, Field, field_validator


class FraudType(str, Enum):
    RING = "RING"
    VELOCITY = "VELOCITY"
    GEO = "GEO"
    MIXED = "MIXED"
    UNCERTAIN = "UNCERTAIN"


class RecommendedAction(str, Enum):
    CONFIRM_BLOCK = "CONFIRM_BLOCK"
    RELEASE = "RELEASE"
    ESCALATE = "ESCALATE"


class Evidence(BaseModel):
    """One tool result, tagged with what produced it. The index into
    `AgentState["evidence"]` is what a finding cites, so this list is append-only:
    renumbering it mid-run would invalidate every citation already written."""

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    payload: Any = None
    error: str | None = None

    def ok(self) -> bool:
        return self.error is None


class Finding(BaseModel):
    claim: str = Field(min_length=1)
    evidence_refs: list[int] = Field(default_factory=list)

    @field_validator("evidence_refs")
    @classmethod
    def _non_negative(cls, refs: list[int]) -> list[int]:
        if any(r < 0 for r in refs):
            raise ValueError("evidence_refs must be non-negative indices")
        return refs


class Report(BaseModel):
    """LLD §6.2. Every finding must point at the evidence that supports it; `verify`
    enforces that programmatically, which is the whole point of the schema."""

    summary: str = Field(min_length=1)
    fraud_type: FraudType
    confidence: float = Field(ge=0.0, le=1.0)
    findings: list[Finding] = Field(default_factory=list)
    recommended_action: RecommendedAction


class Violation(BaseModel):
    """Why `verify` rejected a report. Fed back to the model on the single retry."""

    finding_index: int
    kind: Literal["no_refs", "bad_ref", "uncited_number", "failed_tool_ref"]
    detail: str


def _append(left: list, right: list) -> list:
    """Reducer for accumulating lists across LangGraph nodes."""
    return (left or []) + (right or [])


class AgentState(TypedDict, total=False):
    case_id: str
    messages: Annotated[list[Any], _append]    # the investigate conversation
    case: dict[str, Any]                       # the case as the case-service returns it
    evidence: Annotated[list[Evidence], _append]
    hypotheses: list[str]
    similar: list[dict[str, Any]]
    report: dict[str, Any] | None
    violations: list[Violation]                        # the latest attempt; drives routing
    # Every violation seen across attempts. The latest attempt alone is not enough: when a
    # retry returns nothing parseable, "no report was produced" would otherwise replace the
    # real reason the first draft was rejected, which is exactly what an analyst needs to see.
    all_violations: Annotated[list[Violation], _append]
    tool_calls_used: int                       # hard budget, see settings.max_tool_calls
    verify_attempts: int
    notes: Annotated[list[str], _append]       # human-readable trace for the eval harness
