import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import EntityStatus

if TYPE_CHECKING:
    from app.models.carrier import Carrier
    from app.models.shipment import Shipment


class Vehicle(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "vehicles"
    __table_args__ = (Index("ix_vehicles_carrier_id", "carrier_id"),)

    carrier_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("carriers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    license_plate: Mapped[str] = mapped_column(String(32), nullable=False)
    vehicle_type: Mapped[str] = mapped_column(String(64), nullable=False)
    max_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    max_volume_cbm: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    equipment_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[EntityStatus] = mapped_column(
        Enum(EntityStatus, name="entity_status", native_enum=False, create_constraint=False),
        nullable=False,
        default=EntityStatus.ACTIVE,
    )

    carrier: Mapped["Carrier"] = relationship(back_populates="vehicles")
    shipments: Mapped[list["Shipment"]] = relationship(back_populates="vehicle")
