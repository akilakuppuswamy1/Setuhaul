from uuid import UUID

from sqlalchemy import Select

from app.models.appointment import Appointment
from app.models.enums import AppointmentStatus
from app.repositories.base import BaseRepository


class AppointmentRepository(BaseRepository[Appointment]):
    model = Appointment
    order_by_columns = (Appointment.created_at, Appointment.id)

    def _apply_filters(
        self,
        stmt: Select[tuple[Appointment]],
        *,
        shipment_id: UUID | None = None,
        facility_id: UUID | None = None,
        appointment_status: AppointmentStatus | None = None,
        **_: object,
    ) -> Select[tuple[Appointment]]:
        if shipment_id is not None:
            stmt = stmt.where(Appointment.shipment_id == shipment_id)
        if facility_id is not None:
            stmt = stmt.where(Appointment.facility_id == facility_id)
        if appointment_status is not None:
            stmt = stmt.where(Appointment.status == appointment_status)
        return stmt

    def list_by_shipment(
        self,
        shipment_id: UUID,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[Appointment], int]:
        return self.list_paginated(page=page, page_size=page_size, shipment_id=shipment_id)
