import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import CreatedAtMixin, UUIDPrimaryKeyMixin
from app.models.enums import ETASource

if TYPE_CHECKING:
    from app.models.shipment import Shipment


class ETAUpdate(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "eta_updates"
    __table_args__ = (
        # Supports latest-ETA queries: filter by shipment, order/limit by update_timestamp.
        Index(
            "ix_eta_updates_shipment_id_update_timestamp",
            "shipment_id",
            "update_timestamp",
        ),
    )

    shipment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"),
        nullable=False,
    )
    previous_eta: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    new_eta: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    update_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[ETASource] = mapped_column(
        Enum(ETASource, name="eta_source", native_enum=False),
        nullable=False,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    shipment: Mapped["Shipment"] = relationship(back_populates="eta_updates")
