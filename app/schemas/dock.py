from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import DockStatus


class DockResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    facility_id: UUID
    name: str
    dock_type: str
    max_weight_kg: Decimal | None
    max_length_m: Decimal | None
    temperature_controlled: bool
    status: DockStatus
    created_at: datetime
    updated_at: datetime
