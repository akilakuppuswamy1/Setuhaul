import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import EntityStatus

if TYPE_CHECKING:
    from app.models.carrier import Carrier
    from app.models.chat_thread import ChatThread
    from app.models.driver_exception import DriverException
    from app.models.shipment import Shipment


class Driver(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "drivers"
    __table_args__ = (Index("ix_drivers_carrier_id", "carrier_id"),)

    carrier_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("carriers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[EntityStatus] = mapped_column(
        Enum(EntityStatus, name="entity_status", native_enum=False, create_constraint=False),
        nullable=False,
        default=EntityStatus.ACTIVE,
    )

    carrier: Mapped["Carrier"] = relationship(back_populates="drivers")
    shipments: Mapped[list["Shipment"]] = relationship(back_populates="driver")
    exceptions: Mapped[list["DriverException"]] = relationship(back_populates="driver")
    chat_threads: Mapped[list["ChatThread"]] = relationship(back_populates="driver")
