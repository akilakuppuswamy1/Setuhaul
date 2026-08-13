from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import ChatThreadStatus


class ChatThreadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    shipment_id: UUID | None
    driver_id: UUID | None
    driver_exception_id: UUID | None
    subject: str | None
    status: ChatThreadStatus
    created_at: datetime
    updated_at: datetime
