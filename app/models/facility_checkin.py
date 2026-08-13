import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import CreatedAtMixin, UUIDPrimaryKeyMixin
from app.models.enums import CheckinType

if TYPE_CHECKING:
    from app.models.dock import Dock
    from app.models.facility import Facility
    from app.models.shipment import Shipment


class FacilityCheckin(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "facility_checkins"
    __table_args__ = (
        Index("ix_facility_checkins_shipment_id", "shipment_id"),
        Index("ix_facility_checkins_facility_id", "facility_id"),
    )

    shipment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"),
        nullable=False,
    )
    facility_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("facilities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    dock_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("docks.id", ondelete="SET NULL"),
        nullable=True,
    )
    checkin_type: Mapped[CheckinType] = mapped_column(
        Enum(CheckinType, name="checkin_type", native_enum=False),
        nullable=False,
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    shipment: Mapped["Shipment"] = relationship(back_populates="checkins")
    facility: Mapped["Facility"] = relationship(back_populates="checkins")
    dock: Mapped["Dock | None"] = relationship(back_populates="checkins")
