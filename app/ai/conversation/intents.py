"""Deterministic intent/entity parsing used by FakeLLMProvider and as a fallback."""

from __future__ import annotations

import re
from uuid import UUID

from app.ai.conversation.clocks import (
    asks_informal_options,
    parse_earliest_start_local,
    parse_eta_local,
    parse_leave_by_local,
)
from app.ai.conversation.models import ConversationIntent, Understanding

_INJECTION_MARKERS = (
    "ignore previous",
    "ignore all previous",
    "ignore all instructions",
    "ignore feasibility",
    "system prompt",
    "reveal your system prompt",
    "reveal the openrouter",
    "reveal prompt",
    "execute sql",
    "use sql to",
    "execute arbitrary",
    "bypass feasibility",
    "bypass allocation",
    "call the allocation",
    "allocate dock",
    "call app.services",
    "drop table",
    "api key",
    "override the facility capacity",
    "override capacity",
    "tell the system that the shipment is feasible",
)

_ORDINAL = {
    "first": 1,
    "1st": 1,
    "second": 2,
    "2nd": 2,
    "third": 3,
    "3rd": 3,
    "fourth": 4,
    "4th": 4,
}


def parse_understanding(message: str) -> Understanding:
    text = message.strip()
    lowered = text.lower()
    injection = any(marker in lowered for marker in _INJECTION_MARKERS)

    delay_minutes = _parse_delay_minutes(lowered)
    option_index = _parse_option_index(lowered)
    shipment_hint = _parse_shipment_hint(text)
    exception_type = _parse_exception_type(lowered)
    wants_human = _wants_human(lowered)
    confirm = _is_confirm(lowered)
    reject = _is_reject(lowered)
    earliest_start_local = parse_earliest_start_local(lowered)
    leave_by_local = parse_leave_by_local(lowered)
    eta_local = parse_eta_local(lowered)

    intent, confidence = _classify_intent(
        lowered,
        delay_minutes=delay_minutes,
        option_index=option_index,
        exception_type=exception_type,
        wants_human=wants_human,
        confirm=confirm,
        reject=reject,
        earliest_start_local=earliest_start_local,
        leave_by_local=leave_by_local,
    )
    if intent != ConversationIntent.ACCEPT_PROPOSAL:
        confirm = False

    return Understanding(
        intent=intent,
        confidence=confidence,
        shipment_hint=shipment_hint,
        delay_minutes=delay_minutes,
        eta_local=eta_local,
        earliest_start_local=earliest_start_local,
        leave_by_local=leave_by_local,
        option_index=option_index,
        confirm=confirm,
        reject=reject,
        wants_human=wants_human,
        exception_type=exception_type,
        injection_attempt=injection,
        raw_message=text,
    )


def parse_uuid(value: object) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _classify_intent(
    lowered: str,
    *,
    delay_minutes: int | None,
    option_index: int | None,
    exception_type: str | None,
    wants_human: bool,
    confirm: bool,
    reject: bool,
    earliest_start_local: str | None = None,
    leave_by_local: str | None = None,
) -> tuple[ConversationIntent, float]:
    _ = leave_by_local
    if wants_human:
        return ConversationIntent.HUMAN_ESCALATION, 0.9
    if _declines_confirm(lowered) or _asks_confirmation_status(lowered) or _asks_status(lowered):
        return ConversationIntent.ASK_STATUS, 0.86
    if _asks_facility_schedule(lowered):
        return ConversationIntent.ASK_FACILITY_SCHEDULE, 0.9
    if _asks_options(lowered) or earliest_start_local is not None:
        return ConversationIntent.ASK_OPTIONS, 0.92
    if delay_minutes is not None or _is_delay(lowered):
        if delay_minutes is not None:
            return ConversationIntent.UPDATE_ETA, 0.94
        return ConversationIntent.REPORT_DELAY, 0.8
    if _is_operational_exception(lowered, exception_type) or _cannot_make(lowered):
        return ConversationIntent.REPORT_EXCEPTION, 0.9
    if reject:
        return ConversationIntent.REJECT_PROPOSAL, 0.88
    if confirm and option_index is not None:
        return ConversationIntent.ACCEPT_PROPOSAL, 0.9
    if confirm:
        return ConversationIntent.ACCEPT_PROPOSAL, 0.86
    if option_index is not None:
        return ConversationIntent.PROPOSE_CHANGE, 0.88
    if "cancel" in lowered:
        return ConversationIntent.CANCEL_REQUEST, 0.8
    return ConversationIntent.CLARIFICATION_REQUIRED, 0.4


_WORD_QUANTITIES = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "fifteen": 15,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "forty-five": 45,
    "forty five": 45,
    "sixty": 60,
    "ninety": 90,
}
_QUANTITY = r"(?P<qty>\d+(?:\.\d+)?|forty-five|forty five|ninety|thirty|fifteen|twenty|sixty|one|two|three|four|five|six|seven|eight|nine|ten|forty)"


def _quantity_to_number(raw: str) -> float:
    text = raw.strip().lower()
    if text in _WORD_QUANTITIES:
        return float(_WORD_QUANTITIES[text])
    return float(text)


def _parse_delay_minutes(lowered: str) -> int | None:
    hour = re.search(_QUANTITY + r"\s*(?:hours?|hrs?)\s+(?:late|behind)", lowered)
    if hour:
        return max(1, int(_quantity_to_number(hour.group("qty")) * 60))
    minute = re.search(_QUANTITY + r"\s*minutes?\s+(?:late|behind)", lowered)
    if minute:
        return max(1, int(_quantity_to_number(minute.group("qty"))))
    arrive_hours = re.search(r"(?:arrive|arrival).{0,24}" + _QUANTITY + r"\s*(?:hours?|hrs?)\s+late", lowered)
    if arrive_hours:
        return max(1, int(_quantity_to_number(arrive_hours.group("qty")) * 60))
    return None


def _parse_option_index(lowered: str) -> int | None:
    numbered = re.search(r"\b(?:option|choice|slot)\s*#?\s*(\d+)\b", lowered)
    if numbered:
        return int(numbered.group(1))
    lone_number = re.search(r"\b(?:the\s+)?(\d+)(?:st|nd|rd|th)?\s+(?:one|option|slot)\b", lowered)
    if lone_number:
        return int(lone_number.group(1))
    for word, index in _ORDINAL.items():
        if re.search(rf"\b{word}\b", lowered):
            return index
    return None


def _parse_shipment_hint(text: str) -> str | None:
    number = re.search(r"\bSHP[- ]?\d+\b", text, flags=re.IGNORECASE)
    if number:
        return number.group(0)
    city = re.search(
        r"\b(chicago|dallas|houston|austin|new york|los angeles)\b",
        text,
        flags=re.IGNORECASE,
    )
    if city:
        return city.group(1)
    return None


def _parse_exception_type(lowered: str) -> str | None:
    if "breakdown" in lowered or "broke down" in lowered:
        return "breakdown"
    if "accident" in lowered:
        return "other"
    if "vehicle issue" in lowered or "safety issue" in lowered or "cannot continue" in lowered:
        return "other"
    if "repair" in lowered:
        return "repair"
    if "traffic" in lowered or "congestion" in lowered:
        return "traffic"
    return None


def _is_operational_exception(lowered: str, exception_type: str | None) -> bool:
    if exception_type in {"breakdown", "repair"}:
        return True
    return any(
        phrase in lowered
        for phrase in (
            "accident",
            "vehicle issue",
            "safety issue",
            "cannot continue",
            "can't continue",
            "can not continue",
        )
    )


def _wants_human(lowered: str) -> bool:
    return any(
        phrase in lowered
        for phrase in (
            "talk to a human",
            "speak to a human",
            "human operator",
            "dispatcher please",
            "talk to dispatch",
            "speak to dispatch",
            "real person",
            "human review",
        )
    )


def _declines_confirm(lowered: str) -> bool:
    return any(
        phrase in lowered
        for phrase in (
            "don't confirm",
            "do not confirm",
            "dont confirm",
            "not confirm it",
            "don't book",
            "do not book",
        )
    )


def _asks_confirmation_status(lowered: str) -> bool:
    if re.search(r"\b(has|have|is|was|were|did|does)\b.{0,40}\bconfirmed\b", lowered):
        return True
    if re.search(r"\b(whether|if)\b.{0,40}\bconfirmed\b", lowered):
        return True
    if re.search(r"\bcheck\b.{0,40}\bconfirmed\b", lowered):
        return True
    return "don't change anything" in lowered and "confirm" in lowered


def _is_confirm(lowered: str) -> bool:
    if _declines_confirm(lowered) or _asks_confirmation_status(lowered):
        return False
    return any(
        phrase in lowered
        for phrase in (
            "confirm it",
            "please confirm",
            "yes, confirm",
            "yes confirm",
            "i want to confirm",
            "go ahead and confirm",
            "go ahead",
            "lock it in",
            "book it",
            "book the",
            "confirm the",
        )
    )


def _is_reject(lowered: str) -> bool:
    return any(
        phrase in lowered
        for phrase in ("reject", "don't want that", "do not want that", "not that option")
    )


def _asks_facility_schedule(lowered: str) -> bool:
    return any(
        phrase in lowered
        for phrase in (
            "which truck should go first",
            "who goes first",
            "facility schedule",
            "proposed schedule",
            "rank the trucks",
            "which truck goes first",
        )
    )


def _asks_options(lowered: str) -> bool:
    return any(
        phrase in lowered
        for phrase in (
            "another slot",
            "another appointment",
            "find me another",
            "available options",
            "what are my options",
            "what options do i have",
            "what options are available",
            "what options",
            "find another",
            "other appointment",
            "other slot",
            "get another slot",
            "come later",
            "missed my appointment",
        )
    ) or asks_informal_options(lowered)


def _asks_status(lowered: str) -> bool:
    return any(
        phrase in lowered
        for phrase in ("what's my status", "what is my status", "appointment status", "where do i stand")
    )


def _cannot_make(lowered: str) -> bool:
    return any(
        phrase in lowered
        for phrase in (
            "cannot make",
            "can't make",
            "can not make",
            "won't make that appointment",
            "will not make that appointment",
        )
    )


def _is_delay(lowered: str) -> bool:
    return any(
        phrase in lowered
        for phrase in (
            "running late",
            "running behind",
            "be late",
            "delayed",
            "i'll be late",
            "i am late",
            "i'm late",
            "hours late",
            "hour late",
            "minutes late",
            "hours behind",
            "hour behind",
            "arrive late",
            "arrival delayed",
        )
    )
