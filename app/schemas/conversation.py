"""Request/response schemas for the Step 8 conversational API."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ConversationCreateRequest(BaseModel):
    driver_id: UUID
    shipment_id: UUID | None = None
    subject: str | None = Field(default=None, max_length=255)


class ConversationCreateResponse(BaseModel):
    thread_id: UUID
    driver_id: UUID | None
    shipment_id: UUID | None
    status: str


class ConversationMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


class ToolCallRecord(BaseModel):
    name: str
    success: bool
    error: str | None = None


class ConversationMessageResponse(BaseModel):
    thread_id: UUID
    message_id: UUID
    response: str
    intent: str
    status: str
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    requires_clarification: bool = False
    requires_human: bool = False
    shipment_id: UUID | None = None
    proposal_id: UUID | None = None
    metadata: dict[str, Any] | None = None
