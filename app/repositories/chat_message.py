from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, desc, select

from app.models.chat_message import ChatMessage
from app.models.enums import MessageDirection, SenderType
from app.repositories.base import BaseRepository


class ChatMessageRepository(BaseRepository[ChatMessage]):
    model = ChatMessage
    order_by_columns = (ChatMessage.sent_at, ChatMessage.id)

    def _apply_filters(
        self,
        stmt: Select[tuple[ChatMessage]],
        *,
        chat_thread_id: UUID | None = None,
        **_: object,
    ) -> Select[tuple[ChatMessage]]:
        if chat_thread_id is not None:
            stmt = stmt.where(ChatMessage.chat_thread_id == chat_thread_id)
        return stmt

    def create(
        self,
        *,
        chat_thread_id: UUID,
        sender_type: SenderType,
        content: str,
        sent_at: datetime,
        direction: MessageDirection,
        metadata_: dict[str, Any] | None = None,
    ) -> ChatMessage:
        entity = ChatMessage(
            chat_thread_id=chat_thread_id,
            sender_type=sender_type,
            content=content,
            sent_at=sent_at,
            direction=direction,
            metadata_=metadata_,
        )
        self.session.add(entity)
        self.session.flush()
        self.session.refresh(entity)
        return entity

    def list_recent(self, chat_thread_id: UUID, *, limit: int = 40) -> list[ChatMessage]:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.chat_thread_id == chat_thread_id)
            .order_by(desc(ChatMessage.sent_at), desc(ChatMessage.id))
            .limit(limit)
        )
        items = list(self.session.scalars(stmt).all())
        items.reverse()
        return items
