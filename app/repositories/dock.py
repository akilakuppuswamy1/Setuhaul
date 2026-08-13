from uuid import UUID

from sqlalchemy import Select, select

from app.models.dock import Dock
from app.models.enums import DockStatus
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

    def list_available_by_facility(self, facility_id: UUID) -> list[Dock]:
        """Return available docks in deterministic order: name ASC, id ASC."""
        stmt = (
            select(Dock)
            .where(Dock.facility_id == facility_id)
            .where(Dock.status == DockStatus.AVAILABLE)
            .order_by(Dock.name.asc(), Dock.id.asc())
        )
        return list(self.session.scalars(stmt).all())

    def lock_by_id(self, dock_id: UUID) -> Dock | None:
        """Acquire a row-level lock on the dock for concurrency-safe allocation."""
        stmt = (
            select(Dock)
            .where(Dock.id == dock_id)
            .with_for_update()
        )
        return self.session.scalar(stmt)
