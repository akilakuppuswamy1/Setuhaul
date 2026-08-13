from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ETASource
from app.schemas.validators import TimezoneAwareDatetime


class ETAUpdateCreate(BaseModel):
    new_eta: TimezoneAwareDatetime
    update_timestamp: TimezoneAwareDatetime
    source: ETASource
    reason: str | None = None


class LatestETAResponse(BaseModel):
    shipment_id: UUID
    latest_eta: datetime | None = Field(
        None,
        description="Most recent new_eta from ETAUpdate history; null when no updates exist.",
    )
    eta_update: "ETAUpdateResponse | None" = Field(
        None,
        description="Full latest ETAUpdate record, if one exists.",
    )


class ETAUpdateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    shipment_id: UUID
    previous_eta: datetime | None
    new_eta: datetime
    update_timestamp: datetime
    source: ETASource
    reason: str | None
    created_at: datetime


LatestETAResponse.model_rebuild()
