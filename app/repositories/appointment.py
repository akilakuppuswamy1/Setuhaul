from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, func, select

from app.models.appointment import Appointment
from app.models.appointment_slot import AppointmentSlot
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

    def get_active_for_shipment(
        self,
        shipment_id: UUID,
        statuses: tuple[AppointmentStatus, ...],
    ) -> Appointment | None:
        stmt = (
            select(Appointment)
            .where(Appointment.shipment_id == shipment_id)
            .where(Appointment.status.in_(statuses))
            .order_by(Appointment.created_at.desc(), Appointment.id.desc())
            .limit(1)
        )
        return self.session.scalar(stmt)

    def count_by_slot(
        self,
        slot_id: UUID,
        statuses: tuple[AppointmentStatus, ...],
        *,
        exclude_shipment_id: UUID | None = None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(Appointment)
            .where(Appointment.appointment_slot_id == slot_id)
            .where(Appointment.status.in_(statuses))
        )
        if exclude_shipment_id is not None:
            stmt = stmt.where(Appointment.shipment_id != exclude_shipment_id)
        return int(self.session.scalar(stmt) or 0)

    def count_by_facility_between(
        self,
        facility_id: UUID,
        start: datetime,
        end: datetime,
        statuses: tuple[AppointmentStatus, ...],
        *,
        exclude_shipment_id: UUID | None = None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(Appointment)
            .join(AppointmentSlot, Appointment.appointment_slot_id == AppointmentSlot.id)
            .where(Appointment.facility_id == facility_id)
            .where(Appointment.status.in_(statuses))
            .where(AppointmentSlot.start_time >= start)
            .where(AppointmentSlot.start_time < end)
        )
        if exclude_shipment_id is not None:
            stmt = stmt.where(Appointment.shipment_id != exclude_shipment_id)
        return int(self.session.scalar(stmt) or 0)
