from uuid import UUID

from sqlalchemy import Select

from app.models.facility_checkin import FacilityCheckin
from app.repositories.base import BaseRepository


class FacilityCheckinRepository(BaseRepository[FacilityCheckin]):
    model = FacilityCheckin
    order_by_columns = (FacilityCheckin.occurred_at, FacilityCheckin.id)

    def _apply_filters(
        self,
        stmt: Select[tuple[FacilityCheckin]],
        *,
        shipment_id: UUID | None = None,
        facility_id: UUID | None = None,
        **_: object,
    ) -> Select[tuple[FacilityCheckin]]:
        if shipment_id is not None:
            stmt = stmt.where(FacilityCheckin.shipment_id == shipment_id)
        if facility_id is not None:
            stmt = stmt.where(FacilityCheckin.facility_id == facility_id)
        return stmt

    def list_by_shipment(
        self,
        shipment_id: UUID,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[FacilityCheckin], int]:
        return self.list_paginated(page=page, page_size=page_size, shipment_id=shipment_id)

    def list_by_facility(
        self,
        facility_id: UUID,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[FacilityCheckin], int]:
        return self.list_paginated(page=page, page_size=page_size, facility_id=facility_id)
