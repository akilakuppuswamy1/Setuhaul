from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import EntityStatus


class VehicleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    carrier_id: UUID
    license_plate: str
    vehicle_type: str
    max_weight_kg: Decimal | None
    max_volume_cbm: Decimal | None
    equipment_type: str | None
    status: EntityStatus
    created_at: datetime
    updated_at: datetime
