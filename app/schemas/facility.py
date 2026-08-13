from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import EntityStatus


class FacilityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    code: str
    address: str | None
    timezone: str
    status: EntityStatus
    created_at: datetime
    updated_at: datetime
