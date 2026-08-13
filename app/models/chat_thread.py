import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ChatThreadStatus

if TYPE_CHECKING:
    from app.models.chat_message import ChatMessage
    from app.models.driver import Driver
    from app.models.driver_exception import DriverException
    from app.models.shipment import Shipment


class ChatThread(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "chat_threads"
    __table_args__ = (Index("ix_chat_threads_shipment_id", "shipment_id"),)

    shipment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("shipments.id", ondelete="SET NULL"),
        nullable=True,
    )
    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("drivers.id", ondelete="SET NULL"),
        nullable=True,
    )
    driver_exception_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("driver_exceptions.id", ondelete="SET NULL"),
        nullable=True,
    )
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[ChatThreadStatus] = mapped_column(
        Enum(ChatThreadStatus, name="chat_thread_status", native_enum=False),
        nullable=False,
        default=ChatThreadStatus.OPEN,
    )

    shipment: Mapped["Shipment | None"] = relationship(back_populates="chat_threads")
    driver: Mapped["Driver | None"] = relationship(back_populates="chat_threads")
    driver_exception: Mapped["DriverException | None"] = relationship(
        back_populates="chat_threads"
    )
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="thread",
        order_by="ChatMessage.sent_at",
    )
