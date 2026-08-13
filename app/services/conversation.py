"""Conversational orchestration service. Persists chat records and delegates language to the AI layer."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.ai.conversation.agent import ConversationAgent
from app.ai.conversation.context import context_from_thread, snapshot_context
from app.ai.conversation.executor import ToolExecutor
from app.ai.conversation.models import CandidateShipment, ConversationIntent
from app.ai.conversation.provider import LLMProvider, get_llm_provider
from app.core.config import settings
from app.core.exceptions import NotFoundError, SetuHaulError
from app.models.enums import MessageDirection, SenderType, ShipmentStatus
from app.schemas.conversation import (
    ConversationCreateRequest,
    ConversationCreateResponse,
    ConversationMessageRequest,
    ConversationMessageResponse,
    ToolCallRecord,
)
from app.services.appointment import AppointmentSlotService
from app.services.conversations import ChatMessageService, ChatThreadService
from app.services.driver import DriverService
from app.services.feasibility import FeasibilityService
from app.services.operations import DriverExceptionService, ETAUpdateService
from app.services.proposal import ProposalService
from app.services.shipment import ShipmentService

_ACTIVE_STATUSES = {
    ShipmentStatus.PENDING,
    ShipmentStatus.ASSIGNED,
    ShipmentStatus.IN_TRANSIT,
    ShipmentStatus.AT_FACILITY,
}


class ConversationService:
    def __init__(self, session: Session, provider: LLMProvider | None = None) -> None:
        self._session = session
        self._threads = ChatThreadService(session)
        self._messages = ChatMessageService(session)
        self._drivers = DriverService(session)
        self._shipments = ShipmentService(session)
        executor = ToolExecutor(
            shipment_service=self._shipments,
            eta_service=ETAUpdateService(session),
            exception_service=DriverExceptionService(session),
            feasibility_service=FeasibilityService(session),
            slot_service=AppointmentSlotService(session),
            proposal_service=ProposalService(session),
        )
        resolved_provider = provider or get_llm_provider(
            provider_name=settings.llm_provider,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            base_url=settings.llm_base_url,
        )
        self._agent = ConversationAgent(executor, resolved_provider)

    def create_thread(self, payload: ConversationCreateRequest) -> ConversationCreateResponse:
        self._drivers.get(payload.driver_id)
        if payload.shipment_id is not None:
            shipment = self._shipments.get(payload.shipment_id)
            if shipment.driver_id is not None and shipment.driver_id != payload.driver_id:
                raise SetuHaulError("Shipment is not assigned to this driver")
        thread = self._threads.create(
            driver_id=payload.driver_id,
            shipment_id=payload.shipment_id,
            subject=payload.subject or "Driver conversation",
        )
        return ConversationCreateResponse(
            thread_id=thread.id,
            driver_id=thread.driver_id,
            shipment_id=thread.shipment_id,
            status=thread.status.value,
        )

    def handle_message(
        self,
        thread_id: UUID,
        payload: ConversationMessageRequest,
    ) -> ConversationMessageResponse:
        thread = self._threads.get(thread_id)
        self._messages.create(
            chat_thread_id=thread_id,
            sender_type=SenderType.DRIVER,
            content=payload.message,
            direction=MessageDirection.INBOUND,
        )
        try:
            context = self._load_context(thread_id, thread)
        except Exception:
            from app.ai.conversation.models import ConversationContext

            context = ConversationContext(
                thread_id=thread_id,
                driver_id=thread.driver_id,
                shipment_id=thread.shipment_id,
                exception_id=thread.driver_exception_id,
            )
        try:
            turn = self._agent.handle(payload.message, context)
        except Exception:
            outbound = self._messages.create(
                chat_thread_id=thread_id,
                sender_type=SenderType.SYSTEM,
                content="I could not complete that request.",
                direction=MessageDirection.OUTBOUND,
                metadata={"intent": "CLARIFICATION_REQUIRED", "status": "error"},
            )
            return ConversationMessageResponse(
                thread_id=thread_id,
                message_id=outbound.id,
                response="I could not complete that request.",
                intent="CLARIFICATION_REQUIRED",
                status="error",
                requires_clarification=True,
            )
        metadata = _turn_metadata(turn)
        outbound = self._messages.create(
            chat_thread_id=thread_id,
            sender_type=SenderType.SYSTEM,
            content=turn.response,
            direction=MessageDirection.OUTBOUND,
            metadata=metadata,
        )
        self._persist_thread_links(thread_id, thread, turn.context, turn.requires_human)
        return ConversationMessageResponse(
            thread_id=thread_id,
            message_id=outbound.id,
            response=turn.response,
            intent=turn.intent.value,
            status=turn.status,
            tool_calls=[
                ToolCallRecord(name=item.name, success=item.success, error=item.error)
                for item in turn.tool_calls
            ],
            requires_clarification=turn.requires_clarification,
            requires_human=turn.requires_human,
            shipment_id=turn.context.shipment_id,
            proposal_id=turn.context.proposal_id,
            metadata=_public_response_metadata(metadata),
        )

    def _load_context(self, thread_id: UUID, thread: Any) -> Any:
        history = self._messages.list_recent(thread_id, limit=40)
        metadata_list = [item.metadata for item in history]
        candidates: list[CandidateShipment] = []
        if thread.driver_id is not None:
            listed = self._shipments.list(
                page=1,
                page_size=50,
                driver_id=thread.driver_id,
                is_active=True,
            )
            for shipment in listed.items:
                if shipment.status in _ACTIVE_STATUSES:
                    candidates.append(
                        CandidateShipment(
                            shipment_id=shipment.id,
                            shipment_number=shipment.shipment_number,
                            destination_location=shipment.destination_location,
                            origin_location=shipment.origin_location,
                            status=shipment.status.value,
                        )
                    )
        return context_from_thread(
            thread_id=thread_id,
            driver_id=thread.driver_id,
            shipment_id=thread.shipment_id,
            exception_id=thread.driver_exception_id,
            message_metadata=metadata_list,
            candidate_shipments=candidates,
        )

    def _persist_thread_links(self, thread_id: UUID, thread: Any, context: Any, requires_human: bool) -> None:
        subject = thread.subject
        if requires_human and subject and "[ESCALATED]" not in subject:
            subject = f"[ESCALATED] {subject}"
        elif requires_human and not subject:
            subject = "[ESCALATED] Driver conversation"
        self._threads.update_links(
            thread_id,
            shipment_id=context.shipment_id,
            driver_exception_id=context.exception_id,
            subject=subject,
        )


def _turn_metadata(turn: Any) -> dict[str, Any]:
    return {
        "intent": turn.intent.value if isinstance(turn.intent, ConversationIntent) else str(turn.intent),
        "status": turn.status,
        "requires_clarification": turn.requires_clarification,
        "requires_human": turn.requires_human,
        "tool_calls": [
            {"name": item.name, "success": item.success, "error_code": item.error_code}
            for item in turn.tool_calls
        ],
        "context": snapshot_context(turn.context),
    }


def _public_response_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "intent": metadata.get("intent"),
        "requires_human": metadata.get("requires_human"),
        "tool_calls": metadata.get("tool_calls"),
    }
