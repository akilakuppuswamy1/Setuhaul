import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import MessageChannel, OperationalMessageStatus

if TYPE_CHECKING:
    from app.models.contact import Contact
    from app.models.shipment import Shipment


class OperationalMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "operational_messages"
    __table_args__ = (Index("ix_operational_messages_contact_id", "contact_id"),)

    contact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
    )
    shipment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("shipments.id", ondelete="SET NULL"),
        nullable=True,
    )
    channel: Mapped[MessageChannel] = mapped_column(
        Enum(MessageChannel, name="message_channel", native_enum=False),
        nullable=False,
    )
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[OperationalMessageStatus] = mapped_column(
        Enum(OperationalMessageStatus, name="operational_message_status", native_enum=False),
        nullable=False,
        default=OperationalMessageStatus.PENDING,
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSON,
        nullable=True,
    )

    contact: Mapped["Contact"] = relationship(back_populates="operational_messages")
    shipment: Mapped["Shipment | None"] = relationship(back_populates="operational_messages")
