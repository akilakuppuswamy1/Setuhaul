import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.facility import Facility


class FacilityRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "facility_rules"
    __table_args__ = (
        Index("ix_facility_rules_facility_id", "facility_id"),
        CheckConstraint(
            "effective_end IS NULL OR effective_end > effective_start",
            name="ck_facility_rules_effective_end_after_start",
        ),
    )

    facility_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("facilities.id", ondelete="CASCADE"),
        nullable=False,
    )
    rule_type: Mapped[str] = mapped_column(String(128), nullable=False)
    rule_value: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    effective_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    facility: Mapped["Facility"] = relationship(back_populates="rules")
