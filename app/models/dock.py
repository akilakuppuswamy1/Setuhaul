import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import DockStatus

if TYPE_CHECKING:
    from app.models.appointment import Appointment
    from app.models.facility import Facility
    from app.models.facility_checkin import FacilityCheckin


class Dock(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "docks"
    __table_args__ = (Index("ix_docks_facility_id", "facility_id"),)

    facility_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("facilities.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    dock_type: Mapped[str] = mapped_column(String(64), nullable=False)
    max_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    max_length_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    temperature_controlled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[DockStatus] = mapped_column(
        Enum(DockStatus, name="dock_status", native_enum=False),
        nullable=False,
        default=DockStatus.AVAILABLE,
    )

    facility: Mapped["Facility"] = relationship(back_populates="docks")
    checkins: Mapped[list["FacilityCheckin"]] = relationship(back_populates="dock")
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="dock")
