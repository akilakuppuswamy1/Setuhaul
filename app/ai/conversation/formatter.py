"""Convert structured backend results into driver-facing text. No invented facts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.ai.conversation.models import PresentedOption, ToolResult


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
    parts: list[str] = []
    for result in results or []:
        parts.append(_format_result(result))
    text = " ".join(part for part in parts if part).strip()
    return text or "I recorded your message."


def format_options(options: list[PresentedOption]) -> str:
    if not options:
        return "I could not find a feasible appointment option from the current operational data."
    lines = ["I found these feasible options:"]
    for option in options:
        when = _format_window(option.start_time, option.end_time)
        lines.append(f"{option.index}. {when}")
    lines.append("Which would you prefer?")
    return "\n".join(lines)


def _format_result(result: ToolResult) -> str:
    if not result.success:
        return _format_error(result)
    data = result.data
    name = result.name
    if name == "record_eta_update":
        eta = data.get("new_eta")
        return f"I've recorded your updated ETA as {eta}." if eta else "I've recorded your ETA update."
    if name == "create_driver_exception":
        exception_type = data.get("exception_type", "exception")
        return f"I've recorded a {exception_type} exception on the shipment."
    if name == "get_shipment_status":
        number = data.get("shipment_number", "your shipment")
        status = data.get("status", "unknown")
        eta = data.get("latest_eta")
        eta_part = f" Latest ETA is {eta}." if eta else ""
        return f"{number} is currently {status}.{eta_part}"
    if name == "get_available_options":
        options = [PresentedOption.model_validate(item) for item in data.get("options", [])]
        return format_options(options)
    if name == "create_proposal":
        status = data.get("status", "proposed")
        return f"I've created a proposal for that option. It is currently {status}. Say confirm if you want me to book it."
    if name == "accept_proposal":
        status = data.get("status")
        if status == "confirmed":
            return "The appointment is confirmed."
        if status == "stale":
            return (
                "That option is no longer available because the slot changed. "
                "I can look for another option."
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
    return ""


def _format_error(result: ToolResult) -> str:
    code = result.error_code or ""
    error = (result.error or "").lower()
    if "stale" in error or code == "stale":
        return (
            "That option is no longer available because the slot changed. "
            "I can look for another option."
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


def _format_window(start: datetime | None, end: datetime | None) -> str:
    if start is None:
        return "available slot"
    if end is None:
        return _display_time(start)
    return f"{_display_time(start)} – {_display_time(end)}"


def _display_time(value: datetime) -> str:
    return value.strftime("%H:%M UTC")


def public_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    blocked = {"api_key", "authorization", "prompt", "system_prompt", "hidden_reasoning"}
    return {key: value for key, value in payload.items() if key not in blocked}
