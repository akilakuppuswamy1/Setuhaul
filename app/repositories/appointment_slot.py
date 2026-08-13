from uuid import UUID

from sqlalchemy import Select

from app.models.appointment_slot import AppointmentSlot
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
