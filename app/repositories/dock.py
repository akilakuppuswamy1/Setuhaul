from uuid import UUID

from sqlalchemy import Select

from app.models.dock import Dock
from app.repositories.base import BaseRepository


class DockRepository(BaseRepository[Dock]):
    model = Dock
    order_by_columns = (Dock.facility_id, Dock.name, Dock.id)

    def _apply_filters(
        self,
        stmt: Select[tuple[Dock]],
        *,
        facility_id: UUID | None = None,
        **_: object,
    ) -> Select[tuple[Dock]]:
        if facility_id is not None:
            stmt = stmt.where(Dock.facility_id == facility_id)
        return stmt

    def list_by_facility(
        self,
        facility_id: UUID,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[Dock], int]:
        return self.list_paginated(page=page, page_size=page_size, facility_id=facility_id)
