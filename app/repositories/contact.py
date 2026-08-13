from uuid import UUID

from sqlalchemy import Select

from app.models.contact import Contact
from app.models.enums import ContactType
from app.repositories.base import BaseRepository


class ContactRepository(BaseRepository[Contact]):
    model = Contact
    order_by_columns = (Contact.name, Contact.id)

    def _apply_filters(
        self,
        stmt: Select[tuple[Contact]],
        *,
        facility_id: UUID | None = None,
        carrier_id: UUID | None = None,
        contact_type: ContactType | None = None,
        **_: object,
    ) -> Select[tuple[Contact]]:
        if facility_id is not None:
            stmt = stmt.where(Contact.facility_id == facility_id)
        if carrier_id is not None:
            stmt = stmt.where(Contact.carrier_id == carrier_id)
        if contact_type is not None:
            stmt = stmt.where(Contact.contact_type == contact_type)
        return stmt
