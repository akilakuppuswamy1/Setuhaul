import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import AppointmentSlotStatus

if TYPE_CHECKING:
    from app.models.appointment import Appointment
    from app.models.facility import Facility


class AppointmentSlot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "appointment_slots"
    __table_args__ = (
        # Supports facility slot windows ordered by start time.
        Index(
            "ix_appointment_slots_facility_id_start_time",
            "facility_id",
            "start_time",
        ),
        CheckConstraint("end_time > start_time", name="ck_appointment_slots_end_after_start"),
        CheckConstraint("capacity >= 0", name="ck_appointment_slots_capacity_non_negative"),
    )

    facility_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("facilities.id", ondelete="CASCADE"),
        nullable=False,
    )
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    capacity: Mapped[int] = mapped_column(nullable=False, default=1)
    status: Mapped[AppointmentSlotStatus] = mapped_column(
        Enum(AppointmentSlotStatus, name="appointment_slot_status", native_enum=False),
        nullable=False,
        default=AppointmentSlotStatus.OPEN,
    )

    facility: Mapped["Facility"] = relationship(back_populates="appointment_slots")
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="appointment_slot")
