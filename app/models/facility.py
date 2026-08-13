import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import EntityStatus

if TYPE_CHECKING:
    from app.models.appointment import Appointment
    from app.models.appointment_slot import AppointmentSlot
    from app.models.contact import Contact
    from app.models.dock import Dock
    from app.models.facility_checkin import FacilityCheckin
    from app.models.facility_rule import FacilityRule
    from app.models.shipment import Shipment


class Facility(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "facilities"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    status: Mapped[EntityStatus] = mapped_column(
        Enum(EntityStatus, name="entity_status", native_enum=False, create_constraint=False),
        nullable=False,
        default=EntityStatus.ACTIVE,
    )

    docks: Mapped[list["Dock"]] = relationship(back_populates="facility")
    rules: Mapped[list["FacilityRule"]] = relationship(back_populates="facility")
    appointment_slots: Mapped[list["AppointmentSlot"]] = relationship(back_populates="facility")
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="facility")
    checkins: Mapped[list["FacilityCheckin"]] = relationship(back_populates="facility")
    contacts: Mapped[list["Contact"]] = relationship(back_populates="facility")
    origin_shipments: Mapped[list["Shipment"]] = relationship(
        back_populates="origin_facility",
        foreign_keys="Shipment.origin_facility_id",
    )
    destination_shipments: Mapped[list["Shipment"]] = relationship(
        back_populates="destination_facility",
        foreign_keys="Shipment.destination_facility_id",
    )
