from uuid import UUID

from sqlalchemy import Select

from app.models.chat_message import ChatMessage
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
