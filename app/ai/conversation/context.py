"""Conversation context reconstruction from persisted message metadata."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.ai.conversation.clocks import parse_hhmm, resolve_zone
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


def match_presented_option(
    context: ConversationContext,
    *,
    option_index: int | None = None,
    preference: str | None = None,
    clock_hhmm: str | None = None,
) -> tuple[PresentedOption | None, str | None]:
    """Map language onto an already presented option. Never invents a slot."""
    options = list(context.presented_options)
    if not options:
        return None, None
    if option_index is not None:
        matched = resolve_option(context, option_index)
        if matched is None:
            return None, "I couldn't match that to a presented option. Which numbered option do you mean?"
        return matched, None
    if clock_hhmm:
        hits = [item for item in options if _option_matches_clock(item, clock_hhmm, context.facility_timezone)]
        if len(hits) == 1:
            return hits[0], None
        if len(hits) > 1:
            return None, "More than one shown option matches that time. Which numbered option do you mean?"
        return None, "I don't see a shown option at that time. Which numbered option do you mean?"
    if preference == "earliest":
        ranked = sorted(options, key=lambda item: (_aware(item.start_time), item.index))
        return ranked[0], None
    if preference == "latest":
        ranked = sorted(options, key=lambda item: (_aware(item.start_time), -item.index), reverse=True)
        return ranked[0], None
    if preference == "shortest_wait":
        eta = _context_eta(context)
        ranked = sorted(
            options,
            key=lambda item: (_wait_seconds(eta, item.start_time), _aware(item.start_time), item.index),
        )
        return ranked[0], None
    if preference == "that_one":
        if len(options) == 1:
            return options[0], None
        return None, "Which numbered option do you mean?"
    return None, None


def _option_matches_clock(option: PresentedOption, hhmm: str, timezone_name: str | None) -> bool:
    parsed = parse_hhmm(hhmm)
    if parsed is None or option.start_time is None:
        return False
    hour, minute = parsed
    local = _aware(option.start_time).astimezone(resolve_zone(timezone_name))
    return local.hour == hour and local.minute == minute


def _context_eta(context: ConversationContext) -> datetime | None:
    raw = context.latest_eta
    if isinstance(raw, datetime):
        return _aware(raw)
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        return _aware(parsed)
    return None


def _wait_seconds(eta: datetime | None, start: datetime | None) -> int:
    if start is None:
        return 10**12
    start_aware = _aware(start)
    if eta is None:
        return int(start_aware.timestamp())
    wait = (start_aware - eta).total_seconds()
    return int(wait if wait > 0 else 0)


def _aware(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


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
    if "presented_options" in snapshot:
        raw_options = snapshot.get("presented_options") or []
        options: list[PresentedOption] = []
        for item in raw_options:
            try:
                options.append(PresentedOption.model_validate(item))
            except (ValueError, TypeError):
                continue
        context.presented_options = options
    proposal_slot_id = parse_uuid(snapshot.get("proposal_slot_id"))
    if proposal_slot_id is not None:
        context.proposal_slot_id = proposal_slot_id
    if snapshot.get("pending_proposal_count") is not None:
        try:
            context.pending_proposal_count = int(snapshot["pending_proposal_count"])
        except (TypeError, ValueError):
            pass
    if "selected_option_index" in snapshot:
        context.selected_option_index = snapshot.get("selected_option_index")
    if "pending_clarification" in snapshot:
        context.pending_clarification = snapshot.get("pending_clarification")
    if "pending_intent" in snapshot:
        pending_intent = snapshot.get("pending_intent")
        if pending_intent:
            try:
                context.pending_intent = ConversationIntent(pending_intent)
            except ValueError:
                context.pending_intent = None
        else:
            context.pending_intent = None
    if "pending_delay_minutes" in snapshot:
        context.pending_delay_minutes = snapshot.get("pending_delay_minutes")
    if snapshot.get("facility_timezone"):
        context.facility_timezone = snapshot["facility_timezone"]
    if snapshot.get("earliest_start_local"):
        context.earliest_start_local = snapshot["earliest_start_local"]
    if snapshot.get("leave_by_local"):
        context.leave_by_local = snapshot["leave_by_local"]
    if snapshot.get("repair_duration_minutes") is not None:
        context.repair_duration_minutes = snapshot["repair_duration_minutes"]
    if snapshot.get("reported_delay_minutes") is not None:
        context.reported_delay_minutes = snapshot["reported_delay_minutes"]
    if snapshot.get("explicit_eta_local"):
        context.explicit_eta_local = snapshot["explicit_eta_local"]
    if snapshot.get("eta_authority"):
        context.eta_authority = snapshot["eta_authority"]
    if snapshot.get("exception_type"):
        context.exception_type = snapshot["exception_type"]
    if snapshot.get("original_appointment_feasible") is not None:
        context.original_appointment_feasible = snapshot["original_appointment_feasible"]
    if snapshot.get("last_clarification_key"):
        context.last_clarification_key = snapshot["last_clarification_key"]
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
