from uuid import UUID

from sqlalchemy import Select

from app.models.facility import Facility
from app.repositories.base import BaseRepository


class FacilityRepository(BaseRepository[Facility]):
    model = Facility
    order_by_columns = (Facility.name, Facility.id)

    def _apply_filters(
        self,
        stmt: Select[tuple[Facility]],
        *,
        facility_name: str | None = None,
        name: str | None = None,
        **_: object,
    ) -> Select[tuple[Facility]]:
        target_name = facility_name or name
        if target_name is not None:
            stmt = stmt.where(Facility.name.ilike(f"%{target_name}%"))
        return stmt
