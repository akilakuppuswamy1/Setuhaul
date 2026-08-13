"""Pydantic schemas for resource allocation."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.engines.feasibility.models import FeasibilityOutcome
from app.models.enums import AppointmentStatus
from app.schemas.appointment import AppointmentResponse
from app.schemas.appointment_slot import AppointmentSlotResponse
from app.schemas.dock import DockResponse
from app.schemas.feasibility import FeasibilityResponse
from app.schemas.validators import TimezoneAwareDatetime


class AllocationRequest(BaseModel):
    """Request to allocate operational resources for a shipment."""

    appointment_slot_id: UUID | None = Field(
        default=None,
        description="Specific slot to allocate; auto-selected when omitted",
    )
    dock_id: UUID | None = Field(
        default=None,
        description="Specific dock to allocate; auto-selected when omitted",
    )
    notes: str | None = Field(default=None, description="Optional allocation notes")
    evaluated_at: TimezoneAwareDatetime | None = Field(
        default=None,
        description="Explicit evaluation timestamp for deterministic feasibility",
    )


class AllocationResponse(BaseModel):
    """Result of a successful or attempted allocation."""

    model_config = ConfigDict(from_attributes=True)

    success: bool
    shipment_id: UUID
    appointment: AppointmentResponse | None = None
    appointment_slot: AppointmentSlotResponse | None = None
    dock: DockResponse | None = None
    feasibility: FeasibilityResponse | None = None
    reason: str
    conflict: bool = False
    allocated_at: datetime | None = None
