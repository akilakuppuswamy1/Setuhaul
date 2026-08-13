from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import MessageChannel, OperationalMessageStatus


class OperationalMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    contact_id: UUID
    shipment_id: UUID | None
    channel: MessageChannel
    subject: str | None
    body: str
    status: OperationalMessageStatus
    sent_at: datetime | None
    metadata: dict[str, Any] | None = Field(None, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime
