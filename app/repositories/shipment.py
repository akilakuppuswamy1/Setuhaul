from uuid import UUID

from sqlalchemy import Select, desc, select

from app.models.eta_update import ETAUpdate
from app.models.enums import ETASource, ShipmentStatus
from app.models.shipment import Shipment
from app.repositories.base import BaseRepository


class ShipmentRepository(BaseRepository[Shipment]):
    model = Shipment
    order_by_columns = (Shipment.shipment_number, Shipment.id)

    def _apply_filters(
        self,
        stmt: Select[tuple[Shipment]],
        *,
        driver_id: UUID | None = None,
        carrier_id: UUID | None = None,
        facility_id: UUID | None = None,
        destination_facility_id: UUID | None = None,
        status: ShipmentStatus | None = None,
        current_status: ShipmentStatus | None = None,
        is_active: bool | None = None,
        **_: object,
    ) -> Select[tuple[Shipment]]:
        if driver_id is not None:
            stmt = stmt.where(Shipment.driver_id == driver_id)
        if carrier_id is not None:
            stmt = stmt.where(Shipment.carrier_id == carrier_id)
        target_facility = facility_id or destination_facility_id
        if target_facility is not None:
            stmt = stmt.where(Shipment.destination_facility_id == target_facility)
        target_status = status or current_status
        if target_status is not None:
            stmt = stmt.where(Shipment.status == target_status)
        if is_active is not None:
            stmt = stmt.where(Shipment.is_active == is_active)
        return stmt

    def get_latest_eta(self, shipment_id: UUID) -> ETAUpdate | None:
        stmt = (
            select(ETAUpdate)
            .where(ETAUpdate.shipment_id == shipment_id)
            .order_by(desc(ETAUpdate.update_timestamp), desc(ETAUpdate.id))
            .limit(1)
        )
        return self.session.scalar(stmt)

    def lock_by_id(self, shipment_id: UUID) -> Shipment | None:
        """Acquire a row-level lock on the shipment for concurrency-safe allocation."""
        stmt = (
            select(Shipment)
            .where(Shipment.id == shipment_id)
            .with_for_update()
        )
        return self.session.scalar(stmt)
