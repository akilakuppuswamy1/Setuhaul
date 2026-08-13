from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ExceptionStatus, ExceptionType
from app.schemas.validators import TimezoneAwareDatetime


class DriverExceptionCreate(BaseModel):
    exception_type: ExceptionType
    occurred_at: TimezoneAwareDatetime
    driver_id: UUID | None = None
    description: str | None = None


class DriverExceptionStatusUpdate(BaseModel):
    status: ExceptionStatus
    resolved_at: TimezoneAwareDatetime | None = None


class DriverExceptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    shipment_id: UUID
    driver_id: UUID | None
    exception_type: ExceptionType
    description: str | None
    status: ExceptionStatus
    occurred_at: datetime
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DriverExceptionDetailResponse(DriverExceptionResponse):
    destination_facility_id: UUID | None = Field(
        None,
        description="Destination facility from the linked shipment, when available.",
    )
    driver_name: str | None = Field(
        None,
        description="Driver display name when driver_id is set.",
    )
    chat_thread_ids: list[UUID] = Field(
        default_factory=list,
        description="IDs of chat threads linked to this exception.",
    )
