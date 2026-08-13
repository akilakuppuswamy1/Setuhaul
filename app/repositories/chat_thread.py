from uuid import UUID

from sqlalchemy import Select

from app.models.chat_thread import ChatThread
from app.repositories.base import BaseRepository


class ChatThreadRepository(BaseRepository[ChatThread]):
    model = ChatThread
    order_by_columns = (ChatThread.created_at, ChatThread.id)

    def _apply_filters(
        self,
        stmt: Select[tuple[ChatThread]],
        *,
        shipment_id: UUID | None = None,
        driver_id: UUID | None = None,
        **_: object,
    ) -> Select[tuple[ChatThread]]:
        if shipment_id is not None:
            stmt = stmt.where(ChatThread.shipment_id == shipment_id)
        if driver_id is not None:
            stmt = stmt.where(ChatThread.driver_id == driver_id)
        return stmt

    def list_by_shipment(
        self,
        shipment_id: UUID,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[ChatThread], int]:
        return self.list_paginated(page=page, page_size=page_size, shipment_id=shipment_id)
