from uuid import UUID

from sqlalchemy import Select

from app.models.driver import Driver
from app.models.enums import EntityStatus
from app.repositories.base import BaseRepository


class DriverRepository(BaseRepository[Driver]):
    model = Driver
    order_by_columns = (Driver.name, Driver.id)

    def _apply_filters(
        self,
        stmt: Select[tuple[Driver]],
        *,
        carrier_id: UUID | None = None,
        driver_status: EntityStatus | None = None,
        **_: object,
    ) -> Select[tuple[Driver]]:
        if carrier_id is not None:
            stmt = stmt.where(Driver.carrier_id == carrier_id)
        if driver_status is not None:
            stmt = stmt.where(Driver.status == driver_status)
        return stmt
