from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import ContactType, EntityStatus


class ContactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: str | None
    phone: str | None
    contact_type: ContactType
    facility_id: UUID | None
    carrier_id: UUID | None
    status: EntityStatus
    created_at: datetime
    updated_at: datetime
