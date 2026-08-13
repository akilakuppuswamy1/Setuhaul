from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import ExceptionStatus, ExceptionType


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
