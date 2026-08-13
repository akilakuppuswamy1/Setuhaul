"""Conversation context reconstruction from persisted message metadata."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.ai.conversation.intents import parse_uuid
from app.ai.conversation.models import (
    CandidateShipment,
    ConversationContext,
    ConversationIntent,
    PresentedOption,
)


def context_from_thread(
    *,
    thread_id: UUID,
    driver_id: UUID | None,
    shipment_id: UUID | None,
    exception_id: UUID | None,
    message_metadata: list[dict[str, Any] | None],
    candidate_shipments: list[CandidateShipment] | None = None,
) -> ConversationContext:
    context = ConversationContext(
        thread_id=thread_id,
        driver_id=driver_id,
        shipment_id=shipment_id,
        exception_id=exception_id,
        candidate_shipments=candidate_shipments or [],
    )
    for metadata in message_metadata:
        if not metadata:
            continue
        snapshot = metadata.get("context") if "context" in metadata else metadata
        if not isinstance(snapshot, dict):
            continue
        _merge_snapshot(context, snapshot)
    return context


def snapshot_context(context: ConversationContext) -> dict[str, Any]:
    return context.model_dump(mode="json")


def resolve_shipment(
    context: ConversationContext,
    hint: str | None,
    explicit_id: UUID | None,
) -> tuple[UUID | None, str | None]:
    """Return (shipment_id, clarification_question). Never guess among multiple matches."""
    if explicit_id is not None:
        allowed = {item.shipment_id for item in context.candidate_shipments}
        if context.shipment_id is not None:
            allowed.add(context.shipment_id)
        if explicit_id in allowed:
            return explicit_id, None
        if context.candidate_shipments:
            return None, _ambiguous_shipment_question(context.candidate_shipments)
        return None, "Which shipment are you referring to?"
    if hint:
        matches = _match_hint(context.candidate_shipments, hint)
        if len(matches) == 1:
            return matches[0].shipment_id, None
        if len(matches) > 1:
            return None, _ambiguous_shipment_question(matches)
        if not matches and context.candidate_shipments:
            return None, _ambiguous_shipment_question(context.candidate_shipments)
    if context.shipment_id is not None:
        return context.shipment_id, None
    if len(context.candidate_shipments) == 1:
        return context.candidate_shipments[0].shipment_id, None
    if len(context.candidate_shipments) > 1:
        return None, _ambiguous_shipment_question(context.candidate_shipments)
    return None, "Which shipment are you referring to?"


def resolve_option(context: ConversationContext, option_index: int | None) -> PresentedOption | None:
    if option_index is None:
        return None
    for option in context.presented_options:
        if option.index == option_index:
            return option
    return None


def _merge_snapshot(context: ConversationContext, snapshot: dict[str, Any]) -> None:
    shipment_id = parse_uuid(snapshot.get("shipment_id"))
    if shipment_id is not None:
        context.shipment_id = shipment_id
    exception_id = parse_uuid(snapshot.get("exception_id"))
    if exception_id is not None:
        context.exception_id = exception_id
    proposal_id = parse_uuid(snapshot.get("proposal_id"))
    if proposal_id is not None:
        context.proposal_id = proposal_id
    if snapshot.get("latest_eta"):
        context.latest_eta = snapshot["latest_eta"]
    if snapshot.get("presented_options"):
        options: list[PresentedOption] = []
        for item in snapshot["presented_options"]:
            try:
                options.append(PresentedOption.model_validate(item))
            except (ValueError, TypeError):
                continue
        if options:
            context.presented_options = options
    proposal_slot_id = parse_uuid(snapshot.get("proposal_slot_id"))
    if proposal_slot_id is not None:
        context.proposal_slot_id = proposal_slot_id
    if snapshot.get("selected_option_index") is not None:
        context.selected_option_index = snapshot["selected_option_index"]
    if snapshot.get("pending_clarification") is not None:
        context.pending_clarification = snapshot["pending_clarification"]
    pending_intent = snapshot.get("pending_intent")
    if pending_intent:
        try:
            context.pending_intent = ConversationIntent(pending_intent)
        except ValueError:
            pass
    if snapshot.get("pending_delay_minutes") is not None:
        context.pending_delay_minutes = snapshot["pending_delay_minutes"]
    if snapshot.get("requires_human"):
        context.requires_human = True
        context.escalation_reason = snapshot.get("escalation_reason")
    if snapshot.get("last_tool_result") is not None:
        context.last_tool_result = snapshot["last_tool_result"]


def _match_hint(candidates: list[CandidateShipment], hint: str) -> list[CandidateShipment]:
    needle = hint.lower().strip()
    matches: list[CandidateShipment] = []
    for candidate in candidates:
        haystack = " ".join(
            [
                candidate.shipment_number,
                candidate.destination_location,
                candidate.origin_location,
            ]
        ).lower()
        if needle in haystack or needle.replace(" ", "") in candidate.shipment_number.lower():
            matches.append(candidate)
    return matches


def _ambiguous_shipment_question(matches: list[CandidateShipment]) -> str:
    labels = ", ".join(
        f"{item.shipment_number} ({item.destination_location})" for item in matches[:5]
    )
    return f"I have more than one active shipment for you. Which one do you mean: {labels}?"
