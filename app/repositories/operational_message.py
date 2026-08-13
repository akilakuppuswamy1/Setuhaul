from uuid import UUID

from sqlalchemy import Select

from app.models.operational_message import OperationalMessage
from app.repositories.base import BaseRepository


class OperationalMessageRepository(BaseRepository[OperationalMessage]):
    model = OperationalMessage
    order_by_columns = (OperationalMessage.created_at, OperationalMessage.id)

    def _apply_filters(
        self,
        stmt: Select[tuple[OperationalMessage]],
        *,
        shipment_id: UUID | None = None,
        contact_id: UUID | None = None,
        **_: object,
    ) -> Select[tuple[OperationalMessage]]:
        if shipment_id is not None:
            stmt = stmt.where(OperationalMessage.shipment_id == shipment_id)
        if contact_id is not None:
            stmt = stmt.where(OperationalMessage.contact_id == contact_id)
        return stmt
