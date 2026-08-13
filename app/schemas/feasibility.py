"""Pydantic schemas for feasibility evaluation."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.engines.feasibility.models import FeasibilityOutcome, RuleCategory, RuleSeverity
from app.schemas.validators import TimezoneAwareDatetime


class FeasibilityEvaluateRequest(BaseModel):
    """Optional context for evaluating a specific operational scenario."""

    appointment_slot_id: UUID | None = Field(
        default=None,
        description="Evaluate against a specific appointment slot (optional)",
    )
    dock_id: UUID | None = Field(
        default=None,
        description="Evaluate against a specific dock (optional)",
    )
    evaluated_at: TimezoneAwareDatetime | None = Field(
        default=None,
        description="Explicit evaluation timestamp for deterministic results",
    )


class RuleResultResponse(BaseModel):
    rule_id: str
    rule_name: str
    category: RuleCategory
    passed: bool
    severity: RuleSeverity
    reason: str
    evaluable: bool
    facts: dict[str, Any] = Field(default_factory=dict)


class FeasibilityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    outcome: FeasibilityOutcome
    feasible: bool
    evaluated_at: datetime
    shipment_id: UUID
    rule_results: list[RuleResultResponse]
    blocking_reasons: list[str]
    warnings: list[str]
    operational_facts: dict[str, Any]
