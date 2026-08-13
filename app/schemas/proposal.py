"""Step 7 proposal request/response schemas."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class ProposalStatus(str, Enum):
    """API-facing proposal lifecycle states (mapped from appointment records)."""

    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    STALE = "stale"
    CONFIRMED = "confirmed"


class ProposalCreateRequest(BaseModel):
    appointment_slot_id: UUID
    dock_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=2000)


class ProposalResponse(BaseModel):
    proposal_id: UUID
    shipment_id: UUID
    slot_id: UUID | None
    dock_id: UUID | None
    status: ProposalStatus
    expires_at: datetime
    message: str
    reason: str | None = None
    appointment_id: UUID | None = None
