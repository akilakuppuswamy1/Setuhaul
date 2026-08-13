from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import CheckinType


class FacilityCheckinResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    shipment_id: UUID
    facility_id: UUID
    dock_id: UUID | None
    checkin_type: CheckinType
    occurred_at: datetime
    notes: str | None
    created_at: datetime
