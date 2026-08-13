import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ExceptionStatus, ExceptionType

if TYPE_CHECKING:
    from app.models.chat_thread import ChatThread
    from app.models.driver import Driver
    from app.models.shipment import Shipment


class DriverException(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "driver_exceptions"
    __table_args__ = (Index("ix_driver_exceptions_shipment_id", "shipment_id"),)

    shipment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"),
        nullable=False,
    )
    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("drivers.id", ondelete="SET NULL"),
        nullable=True,
    )
    exception_type: Mapped[ExceptionType] = mapped_column(
        Enum(ExceptionType, name="exception_type", native_enum=False),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ExceptionStatus] = mapped_column(
        Enum(ExceptionStatus, name="exception_status", native_enum=False),
        nullable=False,
        default=ExceptionStatus.OPEN,
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    shipment: Mapped["Shipment"] = relationship(back_populates="exceptions")
    driver: Mapped["Driver | None"] = relationship(back_populates="exceptions")
    chat_threads: Mapped[list["ChatThread"]] = relationship(back_populates="driver_exception")
