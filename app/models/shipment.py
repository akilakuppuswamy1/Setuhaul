import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ShipmentStatus

if TYPE_CHECKING:
    from app.models.appointment import Appointment
    from app.models.carrier import Carrier
    from app.models.chat_thread import ChatThread
    from app.models.driver import Driver
    from app.models.driver_exception import DriverException
    from app.models.eta_update import ETAUpdate
    from app.models.facility import Facility
    from app.models.facility_checkin import FacilityCheckin
    from app.models.operational_message import OperationalMessage
    from app.models.vehicle import Vehicle


class Shipment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "shipments"
    __table_args__ = (
        Index("ix_shipments_driver_id", "driver_id"),
        Index("ix_shipments_carrier_id", "carrier_id"),
        Index("ix_shipments_destination_facility_id", "destination_facility_id"),
    )

    carrier_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("carriers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("drivers.id", ondelete="SET NULL"),
        nullable=True,
    )
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("vehicles.id", ondelete="SET NULL"),
        nullable=True,
    )
    shipment_number: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    origin_location: Mapped[str] = mapped_column(Text, nullable=False)
    destination_location: Mapped[str] = mapped_column(Text, nullable=False)
    origin_facility_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("facilities.id", ondelete="SET NULL"),
        nullable=True,
    )
    destination_facility_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("facilities.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[ShipmentStatus] = mapped_column(
        Enum(ShipmentStatus, name="shipment_status", native_enum=False),
        nullable=False,
        default=ShipmentStatus.PENDING,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    volume_cbm: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    pallet_count: Mapped[int | None] = mapped_column(nullable=True)
    equipment_required: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scheduled_pickup_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    scheduled_delivery_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    carrier: Mapped["Carrier"] = relationship(back_populates="shipments")
    driver: Mapped["Driver | None"] = relationship(back_populates="shipments")
    vehicle: Mapped["Vehicle | None"] = relationship(back_populates="shipments")
    origin_facility: Mapped["Facility | None"] = relationship(
        back_populates="origin_shipments",
        foreign_keys=[origin_facility_id],
    )
    destination_facility: Mapped["Facility | None"] = relationship(
        back_populates="destination_shipments",
        foreign_keys=[destination_facility_id],
    )
    eta_updates: Mapped[list["ETAUpdate"]] = relationship(
        back_populates="shipment",
        order_by="ETAUpdate.update_timestamp",
    )
    exceptions: Mapped[list["DriverException"]] = relationship(back_populates="shipment")
    checkins: Mapped[list["FacilityCheckin"]] = relationship(back_populates="shipment")
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="shipment")
    chat_threads: Mapped[list["ChatThread"]] = relationship(back_populates="shipment")
    operational_messages: Mapped[list["OperationalMessage"]] = relationship(
        back_populates="shipment"
    )
