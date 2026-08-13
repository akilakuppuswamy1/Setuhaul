from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.enums import ContactType
from app.repositories.chat_message import ChatMessageRepository
from app.repositories.chat_thread import ChatThreadRepository
from app.repositories.contact import ContactRepository
from app.schemas.chat_message import ChatMessageResponse
from app.schemas.chat_thread import ChatThreadResponse
from app.schemas.common import PaginatedResponse
from app.schemas.contact import ContactResponse
from app.services.helpers import to_paginated


class ChatThreadService:
    def __init__(self, session: Session) -> None:
        self._repo = ChatThreadRepository(session)

    def get(self, thread_id: UUID) -> ChatThreadResponse:
        thread = self._repo.get_by_id(thread_id)
        if thread is None:
            raise NotFoundError(f"Chat thread {thread_id} not found")
        return ChatThreadResponse.model_validate(thread)

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        shipment_id: UUID | None = None,
        driver_id: UUID | None = None,
    ) -> PaginatedResponse[ChatThreadResponse]:
        items, total = self._repo.list_paginated(
            page=page,
            page_size=page_size,
            shipment_id=shipment_id,
            driver_id=driver_id,
        )
        return to_paginated(
            items,
            page=page,
            page_size=page_size,
            total=total,
            response_model=ChatThreadResponse,
        )


class ChatMessageService:
    def __init__(self, session: Session) -> None:
        self._repo = ChatMessageRepository(session)

    def get(self, message_id: UUID) -> ChatMessageResponse:
        message = self._repo.get_by_id(message_id)
        if message is None:
            raise NotFoundError(f"Chat message {message_id} not found")
        return ChatMessageResponse.model_validate(message)

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        chat_thread_id: UUID | None = None,
    ) -> PaginatedResponse[ChatMessageResponse]:
        items, total = self._repo.list_paginated(
            page=page,
            page_size=page_size,
            chat_thread_id=chat_thread_id,
        )
        return to_paginated(
            items,
            page=page,
            page_size=page_size,
            total=total,
            response_model=ChatMessageResponse,
        )


class ContactService:
    def __init__(self, session: Session) -> None:
        self._repo = ContactRepository(session)

    def get(self, contact_id: UUID) -> ContactResponse:
        contact = self._repo.get_by_id(contact_id)
        if contact is None:
            raise NotFoundError(f"Contact {contact_id} not found")
        return ContactResponse.model_validate(contact)

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        facility_id: UUID | None = None,
        carrier_id: UUID | None = None,
        contact_type: ContactType | None = None,
    ) -> PaginatedResponse[ContactResponse]:
        items, total = self._repo.list_paginated(
            page=page,
            page_size=page_size,
            facility_id=facility_id,
            carrier_id=carrier_id,
            contact_type=contact_type,
        )
        return to_paginated(
            items,
            page=page,
            page_size=page_size,
            total=total,
            response_model=ContactResponse,
        )
