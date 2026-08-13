import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ContactType, EntityStatus

if TYPE_CHECKING:
    from app.models.carrier import Carrier
    from app.models.facility import Facility
    from app.models.operational_message import OperationalMessage


class Contact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "contacts"
    __table_args__ = (
        Index("ix_contacts_facility_id", "facility_id"),
        Index("ix_contacts_carrier_id", "carrier_id"),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    contact_type: Mapped[ContactType] = mapped_column(
        Enum(ContactType, name="contact_type", native_enum=False),
        nullable=False,
    )
    facility_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("facilities.id", ondelete="SET NULL"),
        nullable=True,
    )
    carrier_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("carriers.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[EntityStatus] = mapped_column(
        Enum(EntityStatus, name="entity_status", native_enum=False, create_constraint=False),
        nullable=False,
        default=EntityStatus.ACTIVE,
    )

    facility: Mapped["Facility | None"] = relationship(back_populates="contacts")
    carrier: Mapped["Carrier | None"] = relationship(back_populates="contacts")
    operational_messages: Mapped[list["OperationalMessage"]] = relationship(
        back_populates="contact"
    )
