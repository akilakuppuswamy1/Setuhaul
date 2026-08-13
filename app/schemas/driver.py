from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import EntityStatus


class DriverResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    carrier_id: UUID
    name: str
    phone: str | None
    external_id: str | None
    status: EntityStatus
    created_at: datetime
    updated_at: datetime
