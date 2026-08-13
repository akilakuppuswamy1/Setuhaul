"""Deterministic intent/entity parsing used by FakeLLMProvider and as a fallback."""

from __future__ import annotations

import re
from uuid import UUID

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

    intent, confidence = _classify_intent(
        lowered,
        delay_minutes=delay_minutes,
        option_index=option_index,
        exception_type=exception_type,
        wants_human=wants_human,
        confirm=confirm,
        reject=reject,
    )

    return Understanding(
        intent=intent,
        confidence=confidence,
        shipment_hint=shipment_hint,
        delay_minutes=delay_minutes,
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
) -> tuple[ConversationIntent, float]:
    if wants_human:
        return ConversationIntent.HUMAN_ESCALATION, 0.9
    if _asks_status(lowered):
        return ConversationIntent.ASK_STATUS, 0.86
    if _asks_options(lowered):
        return ConversationIntent.ASK_OPTIONS, 0.92
    if exception_type is not None or _cannot_make(lowered):
        return ConversationIntent.REPORT_EXCEPTION, 0.9
    if delay_minutes is not None or _is_delay(lowered):
        if delay_minutes is not None:
            return ConversationIntent.UPDATE_ETA, 0.94
        return ConversationIntent.REPORT_DELAY, 0.8
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


def _parse_delay_minutes(lowered: str) -> int | None:
    hour = re.search(r"(\d+(?:\.\d+)?)\s*hours?\s+late", lowered)
    if hour:
        return int(float(hour.group(1)) * 60)
    minute = re.search(r"(\d+)\s*minutes?\s+late", lowered)
    if minute:
        return int(minute.group(1))
    hour_alt = re.search(r"(\d+(?:\.\d+)?)\s*hr[s]?\s+late", lowered)
    if hour_alt:
        return int(float(hour_alt.group(1)) * 60)
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
    if "traffic" in lowered or "congestion" in lowered:
        return "traffic"
    if "repair" in lowered:
        return "repair"
    return None


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


def _is_confirm(lowered: str) -> bool:
    return any(
        phrase in lowered
        for phrase in ("confirm", "book it", "book the", "yes, confirm", "go ahead", "lock it in")
    )


def _is_reject(lowered: str) -> bool:
    return any(
        phrase in lowered
        for phrase in ("reject", "don't want that", "do not want that", "not that option")
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
            "find another",
            "other appointment",
            "other slot",
        )
    )


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
    return any(phrase in lowered for phrase in ("running late", "be late", "delayed", "i'll be late", "i am late"))
