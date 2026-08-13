"""Pydantic contracts for the optional facility scheduling evaluation API."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.engines.scheduling.models import AssignmentKind, UnassignedReason
from app.schemas.validators import TimezoneAwareDatetime


class ScheduleEvaluateRequest(BaseModel):
    scheduling_start: TimezoneAwareDatetime | None = Field(
        default=None,
        description="Inclusive horizon start. Defaults to evaluated_at when omitted.",
    )
    scheduling_end: TimezoneAwareDatetime | None = Field(
        default=None,
        description="Exclusive horizon end. Defaults to start + 24 hours when omitted.",
    )
    shipment_ids: list[UUID] | None = Field(
        default=None,
        description="Optional explicit shipment set. Duplicates are ignored. Cross-facility IDs are rejected.",
    )
    evaluated_at: TimezoneAwareDatetime | None = Field(
        default=None,
        description="Explicit evaluation timestamp for deterministic results.",
    )

    @model_validator(mode="after")
    def validate_window(self) -> "ScheduleEvaluateRequest":
        if (
            self.scheduling_start is not None
            and self.scheduling_end is not None
            and self.scheduling_end <= self.scheduling_start
        ):
            raise ValueError("scheduling_end must be after scheduling_start")
        return self


class ScheduleAssignmentResponse(BaseModel):
    shipment_id: UUID
    shipment_number: str
    slot_id: UUID | None
    dock_id: UUID | None
    rank: int
    score: int | None
    kind: AssignmentKind
    lateness_seconds: int | None
    early_wait_seconds: int | None
    alignment_seconds: int | None
    yard_wait_seconds: int | None
    reasons: list[str]


class UnassignedShipmentResponse(BaseModel):
    shipment_id: UUID
    shipment_number: str
    reason: UnassignedReason
    detail: str


class CandidateShipmentResponse(BaseModel):
    shipment_id: UUID
    shipment_number: str
    status: str
    latest_eta: datetime | None
    gate_in_at: datetime | None
    has_active_exception: bool
    missing_eta: bool
    protected: bool


class ScheduleEvaluateResponse(BaseModel):
    facility_id: UUID
    evaluated_at: datetime
    scheduling_start: datetime
    scheduling_end: datetime
    ranking_policy: str
    read_only: bool = True
    commits_capacity: bool = False
    candidate_shipments: list[CandidateShipmentResponse]
    proposed_assignments: list[ScheduleAssignmentResponse]
    unassigned_shipments: list[UnassignedShipmentResponse]
    warnings: list[str]
