from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import AppointmentStatus


class AppointmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    shipment_id: UUID
    facility_id: UUID
    appointment_slot_id: UUID | None
    dock_id: UUID | None
    status: AppointmentStatus
    notes: str | None
    shipment_number: str | None = None
    created_at: datetime
    updated_at: datetime
