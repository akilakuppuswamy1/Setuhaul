from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import AppointmentSlotStatus


class AppointmentSlotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    facility_id: UUID
    start_time: datetime
    end_time: datetime
    capacity: int
    status: AppointmentSlotStatus
    created_at: datetime
    updated_at: datetime
