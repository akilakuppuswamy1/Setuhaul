from uuid import UUID

from sqlalchemy import Select, select

from app.models.appointment_slot import AppointmentSlot
from app.models.enums import AppointmentSlotStatus
from app.repositories.base import BaseRepository


class AppointmentSlotRepository(BaseRepository[AppointmentSlot]):
    model = AppointmentSlot
    order_by_columns = (AppointmentSlot.start_time, AppointmentSlot.id)

    def _apply_filters(
        self,
        stmt: Select[tuple[AppointmentSlot]],
        *,
        facility_id: UUID | None = None,
        **_: object,
    ) -> Select[tuple[AppointmentSlot]]:
        if facility_id is not None:
            stmt = stmt.where(AppointmentSlot.facility_id == facility_id)
        return stmt

    def list_by_facility(
        self,
        facility_id: UUID,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[AppointmentSlot], int]:
        return self.list_paginated(page=page, page_size=page_size, facility_id=facility_id)

    def list_open_by_facility(self, facility_id: UUID) -> list[AppointmentSlot]:
        """Return open slots in deterministic order: start_time ASC, id ASC."""
        stmt = (
            select(AppointmentSlot)
            .where(AppointmentSlot.facility_id == facility_id)
            .where(AppointmentSlot.status == AppointmentSlotStatus.OPEN)
            .order_by(AppointmentSlot.start_time.asc(), AppointmentSlot.id.asc())
        )
        return list(self.session.scalars(stmt).all())

    def lock_by_id(self, slot_id: UUID) -> AppointmentSlot | None:
        """Acquire a row-level lock on the slot for concurrency-safe allocation."""
        stmt = (
            select(AppointmentSlot)
            .where(AppointmentSlot.id == slot_id)
            .with_for_update()
        )
        return self.session.scalar(stmt)
