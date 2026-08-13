from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    get_chat_message_service,
    get_chat_thread_service,
    get_contact_service,
    get_conversation_service,
    get_pagination,
)
from app.models.enums import ContactType
from app.schemas.chat_message import ChatMessageResponse
from app.schemas.chat_thread import ChatThreadResponse
from app.schemas.common import PaginatedResponse
from app.schemas.contact import ContactResponse
from app.schemas.conversation import (
    ConversationCreateRequest,
    ConversationCreateResponse,
    ConversationMessageRequest,
    ConversationMessageResponse,
)
from app.services.conversation import ConversationService
from app.services.conversations import ChatMessageService, ChatThreadService, ContactService

router = APIRouter(tags=["Conversations"])


@router.post(
    "/conversations",
    response_model=ConversationCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a driver conversation thread",
    responses={404: {"description": "Driver or shipment not found"}},
)
def create_conversation(
    payload: ConversationCreateRequest,
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationCreateResponse:
    return service.create_thread(payload)


@router.post(
    "/conversations/{thread_id}/messages",
    response_model=ConversationMessageResponse,
    summary="Send a driver message and receive a conversational response",
    responses={
        404: {"description": "Conversation thread not found"},
        422: {"description": "Malformed request"},
    },
)
def post_conversation_message(
    thread_id: UUID,
    payload: ConversationMessageRequest,
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationMessageResponse:
    return service.handle_message(thread_id, payload)


@router.get(
    "/chat-threads",
    response_model=PaginatedResponse[ChatThreadResponse],
    summary="List chat threads",
)
def list_chat_threads(
    pagination: tuple[int, int] = Depends(get_pagination),
    shipment_id: UUID | None = Query(None, description="Filter by shipment"),
    driver_id: UUID | None = Query(None, description="Filter by driver"),
    service: ChatThreadService = Depends(get_chat_thread_service),
) -> PaginatedResponse[ChatThreadResponse]:
    page, page_size = pagination
    return service.list(
        page=page,
        page_size=page_size,
        shipment_id=shipment_id,
        driver_id=driver_id,
    )


@router.get(
    "/chat-threads/{thread_id}",
    response_model=ChatThreadResponse,
    summary="Get chat thread by ID",
    responses={404: {"description": "Chat thread not found"}},
)
def get_chat_thread(
    thread_id: UUID,
    service: ChatThreadService = Depends(get_chat_thread_service),
) -> ChatThreadResponse:
    return service.get(thread_id)


@router.get(
    "/chat-messages",
    response_model=PaginatedResponse[ChatMessageResponse],
    summary="List chat messages",
)
def list_chat_messages(
    pagination: tuple[int, int] = Depends(get_pagination),
    chat_thread_id: UUID | None = Query(None, description="Filter by chat thread"),
    service: ChatMessageService = Depends(get_chat_message_service),
) -> PaginatedResponse[ChatMessageResponse]:
    page, page_size = pagination
    return service.list(page=page, page_size=page_size, chat_thread_id=chat_thread_id)


@router.get(
    "/chat-messages/{message_id}",
    response_model=ChatMessageResponse,
    summary="Get chat message by ID",
    responses={404: {"description": "Chat message not found"}},
)
def get_chat_message(
    message_id: UUID,
    service: ChatMessageService = Depends(get_chat_message_service),
) -> ChatMessageResponse:
    return service.get(message_id)


@router.get(
    "/contacts",
    response_model=PaginatedResponse[ContactResponse],
    summary="List contacts",
)
def list_contacts(
    pagination: tuple[int, int] = Depends(get_pagination),
    facility_id: UUID | None = Query(None, description="Filter by facility"),
    carrier_id: UUID | None = Query(None, description="Filter by carrier"),
    contact_type: ContactType | None = Query(None, description="Filter by contact type"),
    service: ContactService = Depends(get_contact_service),
) -> PaginatedResponse[ContactResponse]:
    page, page_size = pagination
    return service.list(
        page=page,
        page_size=page_size,
        facility_id=facility_id,
        carrier_id=carrier_id,
        contact_type=contact_type,
    )


@router.get(
    "/contacts/{contact_id}",
    response_model=ContactResponse,
    summary="Get contact by ID",
    responses={404: {"description": "Contact not found"}},
)
def get_contact(
    contact_id: UUID,
    service: ContactService = Depends(get_contact_service),
) -> ContactResponse:
    return service.get(contact_id)
