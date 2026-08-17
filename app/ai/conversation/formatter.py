"""Convert structured backend results into driver-facing text. No invented facts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.ai.conversation.clocks import localize_clock_on, resolve_zone, slot_ends_on_or_before
from app.ai.conversation.models import PresentedOption, ToolResult


def format_feasibility_status(
    results: list[ToolResult],
    *,
    completion_by_local: str | None = None,
) -> str:
    """Read-only answer from current ETA, appointment, and feasibility facts."""
    by_name = {item.name: item for item in results if item.success}
    feasibility = by_name.get("evaluate_feasibility")
    appointment = by_name.get("get_appointment")
    timezone_name: str | None = None
    for result in results:
        if result.success and isinstance(result.data.get("timezone_name"), str):
            timezone_name = result.data["timezone_name"]
    parts: list[str] = []
    if appointment and appointment.success:
        appt = dict(appointment.data)
        if timezone_name and not appt.get("timezone_name"):
            appt["timezone_name"] = timezone_name
        parts.append(_format_appointment(appt))
    if feasibility and feasibility.success:
        data = feasibility.data
        original = _format_original_appointment(data, timezone_name)
        if original:
            parts.append(original)
        elif data.get("feasible"):
            parts.append("The current appointment is feasible under current operational rules.")
        else:
            reasons = data.get("blocking_reasons") or []
            reason_text = "; ".join(str(item) for item in reasons[:3])
            parts.append(
                f"The current appointment is not feasible. {reason_text}".strip()
                if reason_text
                else "The current appointment is not feasible under current operational rules."
            )
        wait_text = _format_wait_fact(data, timezone_name)
        joined = " ".join(parts).lower()
        if wait_text and "wait" not in joined:
            parts.append(wait_text)
        deadline_text = _format_completion_by(data, completion_by_local, timezone_name)
        if deadline_text:
            parts.append(deadline_text)
    text = " ".join(part for part in parts if part).strip()
    return text


def _format_wait_fact(data: dict[str, Any], timezone_name: str | None) -> str:
    relation = data.get("arrival_relation")
    if relation == "before_window":
        start = _parse_iso_datetime(data.get("slot_start"))
        when = _display_local_time(start, timezone_name) if start is not None else "your appointment start"
        return f"You would need to wait until {when} to be taken."
    if relation == "during_window" and data.get("eta_window_passed"):
        return "You should be taken when you arrive; you do not need to wait for a later slot."
    if relation == "after_window":
        return "Waiting at the original slot would not make that appointment feasible."
    return ""


def _format_completion_by(
    data: dict[str, Any],
    completion_by_local: str | None,
    timezone_name: str | None,
) -> str:
    if not completion_by_local:
        return ""
    end = _parse_iso_datetime(data.get("slot_end")) or _parse_iso_datetime(data.get("slot_start"))
    if end is None:
        return ""
    fits = slot_ends_on_or_before(end, completion_by_local, timezone_name)
    bound = localize_clock_on(end, completion_by_local, timezone_name)
    deadline = _display_local_time(bound, timezone_name) if bound is not None else completion_by_local
    window_end = _display_local_time(end, timezone_name)
    if fits is True:
        return f"The current appointment window ends at {window_end}, which is by {deadline}."
    if fits is False:
        return f"The current appointment window ends at {window_end}, which is after {deadline}."
    return ""


def format_turn(
    *,
    clarification: str | None = None,
    results: list[ToolResult] | None = None,
    escalation_message: str | None = None,
) -> str:
    if clarification:
        return clarification
    if escalation_message:
        return escalation_message
    results = results or []
    names = {item.name for item in results}
    if names & {
        "record_eta_update",
        "evaluate_feasibility",
        "create_driver_exception",
        "get_available_options",
    } and len(results) > 1:
        composed = _format_operational_bundle(results)
        if composed:
            return composed
    parts: list[str] = []
    for result in results:
        parts.append(_format_result(result))
    text = " ".join(part for part in parts if part).strip()
    return text or "I recorded your message."


def format_options(options: list[PresentedOption], *, timezone_name: str | None = None) -> str:
    if not options:
        return "I could not find a feasible appointment option from the current operational data."
    if len(options) == 1:
        when = _format_option_when(options[0], timezone_name)
        return (
            f"The next feasible slot is {when}. "
            "Would you like me to request this appointment?"
        )
    lines = ["I found the next feasible appointment options:"]
    for option in options:
        when = _format_option_when(option, timezone_name)
        lines.append(f"{option.index}. {when}")
    lines.append("Which slot would you like to request?")
    return "\n".join(lines)


def _format_result(result: ToolResult) -> str:
    if not result.success:
        return _format_error(result)
    data = result.data
    name = result.name
    if name == "record_eta_update":
        eta = data.get("new_eta")
        timezone_name = data.get("timezone_name") if isinstance(data.get("timezone_name"), str) else None
        parsed = _parse_iso_datetime(eta)
        if parsed is not None:
            when = _display_local_time(parsed, timezone_name)
            return f"I've recorded your updated ETA as {when}."
        return f"I've recorded your updated ETA as {eta}." if eta else "I've recorded your ETA update."
    if name == "create_driver_exception":
        exception_type = data.get("exception_type", "exception")
        return f"I've recorded a {exception_type} exception on the shipment."
    if name == "get_shipment_status":
        number = data.get("shipment_number", "your shipment")
        status = data.get("status", "unknown")
        eta = data.get("latest_eta")
        timezone_name = data.get("timezone_name") if isinstance(data.get("timezone_name"), str) else None
        parsed = _parse_iso_datetime(eta)
        if parsed is not None:
            eta_part = f" Latest ETA is {_display_local_time(parsed, timezone_name)}."
        else:
            eta_part = f" Latest ETA is {eta}." if eta else ""
        return f"{number} is currently {status}.{eta_part}"
    if name == "get_appointment":
        return _format_appointment(data)
    if name == "get_available_options":
        options = [PresentedOption.model_validate(item) for item in data.get("options", [])]
        timezone_name = data.get("timezone_name") if isinstance(data.get("timezone_name"), str) else None
        if options:
            return format_options(options, timezone_name=timezone_name)
        note = data.get("constraint_note")
        if note:
            return str(note) + " Would you like a different window?"
        return format_options(options, timezone_name=timezone_name)
    if name == "create_proposal":
        status = data.get("status", "proposed")
        return f"I've created a proposal for that option. It is currently {status}. Say confirm if you want me to book it."
    if name == "accept_proposal":
        status = data.get("status")
        if status == "confirmed":
            return "The appointment is confirmed."
        if status == "stale":
            return (
                "That option is no longer available because the previously proposed slot was taken. "
                "I can look for current options again."
            )
        return f"Proposal status is now {status}."
    if name == "reject_proposal":
        return "I've rejected that proposal. I can look for another option if you want."
    if name == "get_proposal":
        return f"The current proposal status is {data.get('status', 'unknown')}."
    if name == "evaluate_feasibility":
        if data.get("feasible"):
            return "That option is feasible under current operational rules."
        reasons = data.get("blocking_reasons") or []
        reason_text = "; ".join(str(item) for item in reasons[:3])
        return (
            f"That option is not feasible. {reason_text}"
            if reason_text
            else "That option is not feasible under current operational rules."
        )
    if name == "request_human_escalation":
        return data.get("message") or "I've marked this for human operations review."
    if name == "evaluate_facility_schedule":
        assignments = data.get("proposed_assignments") or []
        unassigned = data.get("unassigned_shipments") or []
        if not assignments and not unassigned:
            return "I could not build a proposed facility schedule from current operational data."
        lines = ["Here is a proposed facility schedule. It does not book or confirm capacity."]
        for item in assignments[:8]:
            kind = item.get("kind", "proposed")
            rank = item.get("rank")
            number = item.get("shipment_number") or item.get("shipment_id")
            lines.append(f"{rank}. {number} ({kind})")
        if unassigned:
            lines.append(f"{len(unassigned)} shipment(s) were not assigned a proposed slot.")
        return " ".join(lines) if len(lines) == 1 else "\n".join(lines)
    return ""


def _format_operational_bundle(results: list[ToolResult]) -> str:
    parts: list[str] = []
    timezone_name: str | None = None
    for result in results:
        if result.success and isinstance(result.data.get("timezone_name"), str):
            timezone_name = result.data["timezone_name"]
    by_name = {item.name: item for item in results}
    exception = by_name.get("create_driver_exception")
    if exception and exception.success:
        parts.append(_format_result(exception))
    eta = by_name.get("record_eta_update")
    if eta and eta.success:
        parts.append(_format_result(eta))
    elif eta and not eta.success and eta.error:
        parts.append(eta.error)
    feasibility = by_name.get("evaluate_feasibility")
    if feasibility and feasibility.success:
        parts.append(_format_original_appointment(feasibility.data, timezone_name))
    options = by_name.get("get_available_options")
    if options:
        parts.append(_format_result(options))
    return " ".join(part for part in parts if part).strip()


def _format_original_appointment(data: dict[str, Any], timezone_name: str | None) -> str:
    slot_start = _parse_iso_datetime(data.get("slot_start"))
    if slot_start is None:
        return ""
    window = _display_local_time(slot_start, timezone_name)
    eta = _parse_iso_datetime(data.get("latest_eta"))
    eta_text = _display_local_time(eta, timezone_name) if eta is not None else None
    relation = data.get("arrival_relation")
    if data.get("eta_window_passed"):
        if relation == "before_window" and eta_text:
            return (
                f"Your original {window} appointment still works if you wait after arriving around {eta_text}."
            )
        if eta_text:
            return f"Your original {window} appointment still works with an arrival around {eta_text}."
        return f"Your original {window} appointment still works."
    if eta_text:
        return (
            f"Your original {window} appointment is no longer feasible because your updated ETA is {eta_text}."
        )
    reason = data.get("eta_window_reason")
    if reason:
        return f"Your original {window} appointment is no longer feasible. {reason}"
    return f"Your original {window} appointment is no longer feasible."


def _format_error(result: ToolResult) -> str:
    code = result.error_code or ""
    error = (result.error or "").lower()
    if "concurrent_confirmation" in error:
        return "Proposal is stale: concurrent_confirmation"
    if "stale" in error or code == "stale":
        return (
            "That option is no longer available because the previously proposed slot was taken. "
            "I can look for current options again."
        )
    if "conflict" in error or code == "conflict":
        return (
            "That appointment could not be confirmed because another booking took the available capacity. "
            "I can look for another slot."
        )
    if code == "not_found":
        return "I could not find that record."
    if result.error:
        return result.error
    return "I could not complete that request."


def _format_appointment(data: dict[str, Any]) -> str:
    if not data.get("found"):
        return "I don't have a current appointment on file for this shipment."
    start = _parse_iso_datetime(data.get("start_time"))
    end = _parse_iso_datetime(data.get("end_time"))
    timezone_name = data.get("timezone_name") if isinstance(data.get("timezone_name"), str) else None
    window = _format_local_window(start, end, timezone_name, include_zone=True)
    status = data.get("status")
    status_part = f" It is currently {status}." if status else ""
    if window:
        return f"Your appointment window is {window}.{status_part}"
    if status:
        return f"I found an appointment on file. It is currently {status}, but no time window is stored."
    return "I found an appointment on file, but no time window is stored."


def _format_option_when(option: PresentedOption, timezone_name: str | None) -> str:
    local = _format_local_window(option.start_time, option.end_time, timezone_name, include_zone=False)
    if local:
        return local
    return _format_window(option.start_time, option.end_time)


def _format_window(start: datetime | None, end: datetime | None) -> str:
    if start is None:
        return "available slot"
    if end is None:
        return _display_time(start)
    return f"{_display_time(start)} – {_display_time(end)}"


def _format_local_window(
    start: datetime | None,
    end: datetime | None,
    timezone_name: str | None,
    *,
    include_zone: bool = False,
) -> str | None:
    if start is None:
        return None
    start_text = _display_local_time(start, timezone_name)
    if end is None:
        label = start_text
    else:
        label = f"{start_text} – {_display_local_time(end, timezone_name)}"
    if include_zone:
        zone_label = (timezone_name or "").strip() or "UTC"
        return f"{label} {zone_label}"
    return label


def _display_time(value: datetime) -> str:
    return value.strftime("%H:%M UTC")


def _display_local_time(value: datetime, timezone_name: str | None) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    local = value.astimezone(resolve_zone(timezone_name))
    hour12 = local.hour % 12 or 12
    suffix = "AM" if local.hour < 12 else "PM"
    return f"{hour12}:{local.minute:02d} {suffix}"


def _parse_iso_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def public_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    blocked = {"api_key", "authorization", "prompt", "system_prompt", "hidden_reasoning"}
    return {key: value for key, value in payload.items() if key not in blocked}
