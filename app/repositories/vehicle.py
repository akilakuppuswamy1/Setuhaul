from uuid import UUID

from sqlalchemy import Select

from app.models.vehicle import Vehicle
from app.repositories.base import BaseRepository


class VehicleRepository(BaseRepository[Vehicle]):
    model = Vehicle
    order_by_columns = (Vehicle.license_plate, Vehicle.id)

    def _apply_filters(
        self,
        stmt: Select[tuple[Vehicle]],
        *,
        carrier_id: UUID | None = None,
        **_: object,
    ) -> Select[tuple[Vehicle]]:
        if carrier_id is not None:
            stmt = stmt.where(Vehicle.carrier_id == carrier_id)
        return stmt
