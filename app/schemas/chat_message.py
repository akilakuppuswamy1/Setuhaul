from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import MessageDirection, SenderType


class ChatMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    chat_thread_id: UUID
    sender_type: SenderType
    content: str
    sent_at: datetime
    direction: MessageDirection
    metadata: dict[str, Any] | None = Field(None, validation_alias="metadata_")
    created_at: datetime
