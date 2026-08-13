import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import AppointmentStatus

if TYPE_CHECKING:
    from app.models.appointment_slot import AppointmentSlot
    from app.models.dock import Dock
    from app.models.facility import Facility
    from app.models.shipment import Shipment


class Appointment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "appointments"
    __table_args__ = (
        Index("ix_appointments_facility_id", "facility_id"),
        # Supports appointment history and status-filtered lookups per shipment.
        Index("ix_appointments_shipment_id_status", "shipment_id", "status"),
    )

    shipment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"),
        nullable=False,
    )
    facility_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("facilities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    appointment_slot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("appointment_slots.id", ondelete="SET NULL"),
        nullable=True,
    )
    dock_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("docks.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[AppointmentStatus] = mapped_column(
        Enum(AppointmentStatus, name="appointment_status", native_enum=False),
        nullable=False,
        default=AppointmentStatus.REQUESTED,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    shipment: Mapped["Shipment"] = relationship(back_populates="appointments")
    facility: Mapped["Facility"] = relationship(back_populates="appointments")
    appointment_slot: Mapped["AppointmentSlot | None"] = relationship(
        back_populates="appointments"
    )
    dock: Mapped["Dock | None"] = relationship(back_populates="appointments")
