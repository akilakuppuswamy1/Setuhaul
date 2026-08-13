from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ShipmentStatus


class ShipmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    carrier_id: UUID
    driver_id: UUID | None
    vehicle_id: UUID | None
    shipment_number: str
    origin_location: str
    destination_location: str
    origin_facility_id: UUID | None
    destination_facility_id: UUID | None
    status: ShipmentStatus
    is_active: bool
    weight_kg: Decimal | None
    volume_cbm: Decimal | None
    pallet_count: int | None
    equipment_required: str | None
    scheduled_pickup_at: datetime | None
    scheduled_delivery_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ShipmentDetailResponse(ShipmentResponse):
    """Shipment with latest ETA derived from ETAUpdate history (source of truth)."""

    latest_eta: datetime | None = Field(
        None,
        description="Most recent new_eta from ETAUpdate history; not a stored column.",
    )
