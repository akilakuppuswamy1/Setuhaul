import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import EntityStatus

if TYPE_CHECKING:
    from app.models.contact import Contact
    from app.models.driver import Driver
    from app.models.shipment import Shipment
    from app.models.vehicle import Vehicle


class Carrier(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "carriers"
    __table_args__ = (UniqueConstraint("code", name="uq_carriers_code"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[EntityStatus] = mapped_column(
        Enum(EntityStatus, name="entity_status", native_enum=False),
        nullable=False,
        default=EntityStatus.ACTIVE,
    )

    drivers: Mapped[list["Driver"]] = relationship(back_populates="carrier")
    vehicles: Mapped[list["Vehicle"]] = relationship(back_populates="carrier")
    shipments: Mapped[list["Shipment"]] = relationship(back_populates="carrier")
    contacts: Mapped[list["Contact"]] = relationship(back_populates="carrier")
