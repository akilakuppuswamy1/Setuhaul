from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import ETASource


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
