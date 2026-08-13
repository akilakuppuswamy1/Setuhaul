from uuid import UUID

from sqlalchemy import Select

from app.models.eta_update import ETAUpdate
from app.models.enums import ETASource
from app.repositories.base import BaseRepository


class ETAUpdateRepository(BaseRepository[ETAUpdate]):
    model = ETAUpdate
    order_by_columns = (ETAUpdate.update_timestamp, ETAUpdate.id)

    def _apply_filters(
        self,
        stmt: Select[tuple[ETAUpdate]],
        *,
        shipment_id: UUID | None = None,
        source: ETASource | None = None,
        **_: object,
    ) -> Select[tuple[ETAUpdate]]:
        if shipment_id is not None:
            stmt = stmt.where(ETAUpdate.shipment_id == shipment_id)
        if source is not None:
            stmt = stmt.where(ETAUpdate.source == source)
        return stmt

    def list_by_shipment(
        self,
        shipment_id: UUID,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[ETAUpdate], int]:
        return self.list_paginated(page=page, page_size=page_size, shipment_id=shipment_id)
