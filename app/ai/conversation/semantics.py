"""Canonical operational meaning extracted from driver language.

Language may identify intent, entities, facts, and constraints.
Python services remain authoritative for feasibility, capacity, booking,
and confirmation. This module does not write ETA, exceptions, or proposals.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.ai.conversation.clocks import (
    asks_informal_options,
    parse_clock_tokens,
    parse_completion_by_local,
    parse_earliest_start_local,
    parse_eta_local,
    parse_leave_by_local,
    parse_original_appointment_local,
)

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
    "an": 1,
    "a": 1,
}
_QUANTITY = (
    r"(?P<qty>\d+(?:\.\d+)?|forty-five|forty five|ninety|thirty|fifteen|"
    r"twenty|sixty|one|two|three|four|five|six|seven|eight|nine|ten|forty|an|a)"
)
_REPAIR_DURATION = re.compile(
    r"(?:repair|fix(?:ing)?|puncture|tyre|tire).{0,48}?"
    r"(?:take|takes|taking|need|needs|will be)\s+"
    r"(?:(?:about|around|approximately|roughly)\s+)?"
    + _QUANTITY
    + r"\s*(?P<unit>hours?|hrs?|minutes?)",
    flags=re.IGNORECASE,
)
_REPAIR_DURATION_FLIP = re.compile(
    r"(?:(?:about|around|approximately|roughly)\s+)?"
    + _QUANTITY
    + r"\s*(?P<unit>hours?|hrs?|minutes?).{0,32}?"
    r"(?:repair|to (?:fix|repair)|fix(?:ing)?|tyre|tire|puncture|flat)",
    flags=re.IGNORECASE,
)
_REQUEST_CUE = re.compile(
    r"\b(?:any|anything|something|what(?:'s|s)?|whats|what else|when|can you|could you|"
    r"can i|do you(?: have)?|do i(?: have)?|is there|are there|show(?: me)?|"
    r"find(?: me)?|see (?:if|what)|look(?:ing)? for|another|other|else|next|"
    r"check|give me|offer|fit me|get in)\b",
    flags=re.IGNORECASE,
)
_AVAILABILITY_CUE = re.compile(
    r"\b(?:slot|slots|appointment|appointments|option|options|window|windows|"
    r"available|availability|later|after|tonight|open|opening|fit|another time|"
    r"different time|come|offer|earliest|room|get in|around then|around that)\b",
    flags=re.IGNORECASE,
)
_HELP_CUE = re.compile(
    r"what can i do|what else can i|what are my options|show me what|"
    r"what (?:else )?can i (?:take|choose|have|make|get)|when can i (?:get in|come)|"
    r"give me (?:some )?options|give me option|check availability|"
    r"what can you offer|next available|any chance of a slot|can i get a slot|"
    r"can you fit me|is there room",
    flags=re.IGNORECASE,
)
_QUESTION_CUE = re.compile(
    r"\?|\b(?:will i|will it|will this|will that|will they|would i|should i|"
    r"do i|does that|does this|did you|can i|could i|am i|"
    r"is it|is this|is my|has it|have you|have i)\b",
    flags=re.IGNORECASE,
)
_WAIT_QUESTION = re.compile(
    r"\b(?:should i wait|have to wait|need to wait|do i (?:need to )?wait|"
    r"will i (?:have to )?wait|wait for (?:my |the )?(?:slot|appointment)|"
    r"waiting)\b",
    flags=re.IGNORECASE,
)
_COMPLETION_CUE = re.compile(
    r"\b(?:completed|complete|done|finished|finish|unloaded|unload(?:ing)?)\b",
    flags=re.IGNORECASE,
)
_MAKE_CURRENT = re.compile(
    r"\bmake (?:it|my appointment|the appointment|my slot|the slot)\b",
    flags=re.IGNORECASE,
)
_CURRENT_PLAN_WORKS = re.compile(
    r"\b(?:will|does|would) (?:this|that|it) work\b|"
    r"\b(?:this|that|my|the) (?:appointment|slot|plan).{0,24}\b(?:still )?work",
    flags=re.IGNORECASE,
)
_ARRIVAL_ACCEPT = re.compile(
    r"\b(?:take me|when i arrive|when i get there|they take me)\b",
    flags=re.IGNORECASE,
)
_INVENTORY_CUE = re.compile(
    r"\b(?:slots?|options?|available|availability|another|later|open(?:ing)?|"
    r"next available|fit me|get in|room|anything (?:open|later|after))\b",
    flags=re.IGNORECASE,
)
_AFFIRM_EXACT = {
    "yes",
    "yeah",
    "yep",
    "ok",
    "okay",
    "sure",
    "fine",
    "please",
    "please do",
    "go ahead",
    "do that",
}
_OPTION_EARLIEST = re.compile(
    r"\b(?:earliest|the first (?:one|option|slot)|give me the earliest)\b",
    flags=re.IGNORECASE,
)
_OPTION_LATEST = re.compile(
    r"\b(?:later one|latest|last one|that later|the later)\b",
    flags=re.IGNORECASE,
)
_OPTION_SHORTEST = re.compile(
    r"\bshortest wait|least wait|shortest (?:one|option)\b",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class SemanticFacts:
    """Structured meaning. Times are independent facts, not one interchangeable clock."""

    delay_minutes: int | None = None
    repair_duration_minutes: int | None = None
    eta_local: str | None = None
    leave_by_local: str | None = None
    earliest_start_local: str | None = None
    original_appointment_local: str | None = None
    exception_type: str | None = None
    asks_options: bool = False
    cannot_make_appointment: bool = False
    delay_mentioned: bool = False
    leave_by_ambiguous: bool = False
    option_preference: str | None = None
    option_clock_local: str | None = None
    completion_by_local: str | None = None
    asks_feasibility_status: bool = False
    asks_status: bool = False


def extract_semantic_facts(message: str) -> SemanticFacts:
    lowered = message.strip().lower()
    repair_duration = _parse_repair_duration(lowered)
    delay_minutes = _parse_relative_delay_minutes(lowered)
    if repair_duration is not None and delay_minutes == repair_duration and not _has_lateness_language(lowered):
        delay_minutes = None
    leave_by_local = parse_leave_by_local(lowered)
    eta_local = parse_eta_local(lowered)
    if eta_local and leave_by_local and eta_local == leave_by_local and "leave" in lowered:
        eta_local = None
    exception_type = _parse_exception_type(lowered)
    cannot_make = _cannot_make(lowered)
    delay_mentioned = delay_minutes is not None or _is_delay(lowered)
    leave_by_ambiguous = bool(
        leave_by_local
        and eta_local is None
        and delay_minutes is None
        and delay_mentioned
    )
    asks_options = _asks_for_alternatives(lowered)
    asks_feasibility = _asks_feasibility_status(lowered)
    if asks_feasibility and asks_options and not _INVENTORY_CUE.search(lowered):
        asks_options = False
    completion_by = None
    if asks_feasibility:
        completion_by = parse_completion_by_local(lowered)
    return SemanticFacts(
        delay_minutes=delay_minutes,
        repair_duration_minutes=repair_duration,
        eta_local=eta_local,
        leave_by_local=leave_by_local,
        earliest_start_local=parse_earliest_start_local(lowered),
        original_appointment_local=parse_original_appointment_local(lowered),
        exception_type=exception_type,
        asks_options=asks_options,
        cannot_make_appointment=cannot_make,
        delay_mentioned=delay_mentioned,
        leave_by_ambiguous=leave_by_ambiguous,
        option_preference=_parse_option_preference(lowered),
        option_clock_local=_parse_option_clock(lowered, eta_local, leave_by_local),
        completion_by_local=completion_by,
        asks_feasibility_status=asks_feasibility,
        asks_status=_asks_operational_status(lowered),
    )


def is_informal_affirmative(message: str) -> bool:
    """Natural yes to a pending question. Not an exhaustive phrase list."""
    text = message.strip().lower().strip(".!,")
    if not text:
        return False
    if re.search(r"\b(no|not|don't|dont|do not)\b", text) and "confirm" not in text:
        return False
    if "confirm" in text or "book" in text:
        return False
    if text in _AFFIRM_EXACT:
        return True
    if re.fullmatch(r"(?:yes|yeah|yep|ok|okay|sure|fine)(?:\s+\w+){0,6}", text):
        return True
    if re.search(
        r"\b(?:please do|please check|show me|check availability|find them|"
        r"that works|go ahead|do that|that would be (?:great|fine|good)|"
        r"sounds good|go for it)\b",
        text,
    ):
        return True
    return bool(re.search(r"\b(?:ok|okay|yes|yeah|yep)\b.{0,16}\b(?:check|find|show|do)\b", text))


def _parse_option_preference(lowered: str) -> str | None:
    if re.search(r"\b(?:reject|don't want|do not want|not that option)\b", lowered):
        return None
    if _OPTION_SHORTEST.search(lowered):
        return "shortest_wait"
    if _OPTION_LATEST.search(lowered):
        return "latest"
    if _OPTION_EARLIEST.search(lowered) and "after" not in lowered:
        return "earliest"
    if re.search(
        r"\b(?:that one|this one|that slot|that option)\b",
        lowered,
    ) and not re.search(r"\b(?:does|will|would|should) that\b", lowered):
        if not re.search(r"\b(?:later|earliest|first|second|third)\b", lowered):
            return "that_one"
    return None


def _parse_option_clock(lowered: str, eta_local: str | None, leave_by_local: str | None) -> str | None:
    if re.search(r"\b(?:repair|tyre|tire|puncture|fix(?:ing)?)\b.{0,24}\btake", lowered):
        return None
    if not re.search(
        r"\b(?:i'll take|lets take|let's take|take the|slot|option|works|choose|pick|"
        r"go with|get the)\b",
        lowered,
    ):
        return None
    if _asks_feasibility_status(lowered) and not re.search(r"\b(?:slot|option)\b", lowered):
        return None
    clocks = [item for item in parse_clock_tokens(lowered) if item != leave_by_local]
    if not clocks:
        return None
    last = clocks[-1]
    if last == eta_local and "take" not in lowered and "slot" not in lowered and "let" not in lowered:
        return None
    return last


def quantity_to_number(raw: str) -> float:
    text = raw.strip().lower()
    if text in _WORD_QUANTITIES:
        return float(_WORD_QUANTITIES[text])
    return float(text)


def _parse_repair_duration(lowered: str) -> int | None:
    match = _REPAIR_DURATION.search(lowered) or _REPAIR_DURATION_FLIP.search(lowered)
    if match is None:
        return None
    return _duration_to_minutes(match.group("qty"), match.group("unit"))


def _parse_relative_delay_minutes(lowered: str) -> int | None:
    late_by_hour = re.search(
        r"late\s+by\s+(?:(?:about|around|approximately|roughly)\s+)?"
        + _QUANTITY
        + r"\s*(?:hours?|hrs?)",
        lowered,
    )
    if late_by_hour:
        return max(1, int(quantity_to_number(late_by_hour.group("qty")) * 60))
    late_by_minute = re.search(
        r"late\s+by\s+(?:(?:about|around|approximately|roughly)\s+)?"
        + _QUANTITY
        + r"\s*minutes?",
        lowered,
    )
    if late_by_minute:
        return max(1, int(quantity_to_number(late_by_minute.group("qty"))))
    hour = re.search(
        r"(?:(?:about|around|approximately|roughly)\s+)?"
        + _QUANTITY
        + r"\s*(?:hours?|hrs?)\s+(?:late|behind)",
        lowered,
    )
    if hour:
        return max(1, int(quantity_to_number(hour.group("qty")) * 60))
    minute = re.search(
        r"(?:(?:about|around|approximately|roughly)\s+)?"
        + _QUANTITY
        + r"\s*minutes?\s+(?:late|behind)",
        lowered,
    )
    if minute:
        return max(1, int(quantity_to_number(minute.group("qty"))))
    arrive_hours = re.search(
        r"(?:arrive|arrival).{0,24}" + _QUANTITY + r"\s*(?:hours?|hrs?)\s+late",
        lowered,
    )
    if arrive_hours:
        return max(1, int(quantity_to_number(arrive_hours.group("qty")) * 60))
    delayed_by = re.search(
        r"delayed\s+by\s+(?:(?:about|around|approximately|roughly)\s+)?"
        + _QUANTITY
        + r"\s*(?:hours?|hrs?|minutes?)",
        lowered,
    )
    if delayed_by:
        unit = delayed_by.group(0)
        minutes = quantity_to_number(delayed_by.group("qty"))
        if "minute" in unit:
            return max(1, int(minutes))
        return max(1, int(minutes * 60))
    return None


def _duration_to_minutes(qty: str, unit: str) -> int:
    amount = quantity_to_number(qty)
    if unit.lower().startswith("hour") or unit.lower().startswith("hr"):
        return max(1, int(amount * 60))
    return max(1, int(amount))


def _parse_exception_type(lowered: str) -> str | None:
    if any(token in lowered for token in ("breakdown", "broke down", "broken down")):
        return "breakdown"
    if any(token in lowered for token in ("tyre", "tire", "puncture", "flat")):
        return "repair"
    if "accident" in lowered:
        return "other"
    if "vehicle issue" in lowered or "safety issue" in lowered or "cannot continue" in lowered:
        return "other"
    if "repair" in lowered:
        return "repair"
    if "traffic" in lowered or "congestion" in lowered:
        return "traffic"
    return None


def _asks_for_alternatives(lowered: str) -> bool:
    if _asks_current_appointment_lookup(lowered):
        return False
    if _asks_feasibility_status(lowered) and not _INVENTORY_CUE.search(lowered):
        return False
    if _HELP_CUE.search(lowered):
        return True
    if asks_informal_options(lowered):
        return True
    return bool(_REQUEST_CUE.search(lowered) and _AVAILABILITY_CUE.search(lowered))


def _asks_feasibility_status(lowered: str) -> bool:
    if _OPTION_SHORTEST.search(lowered):
        return False
    wait_hit = bool(_WAIT_QUESTION.search(lowered) or (
        re.search(r"\bwait\b", lowered) and re.search(r"\b(?:should i|do i|will i|have to)\b", lowered)
    ))
    if wait_hit:
        return True
    if not _QUESTION_CUE.search(lowered):
        return False
    if _COMPLETION_CUE.search(lowered):
        return True
    if _MAKE_CURRENT.search(lowered):
        return True
    if _CURRENT_PLAN_WORKS.search(lowered):
        return True
    if _ARRIVAL_ACCEPT.search(lowered):
        return True
    if _is_arrival_statement(lowered):
        return False
    if re.search(r"\b(?:arriv\w+|get there|be there|make).{0,28}\b(?:by|before)\b", lowered):
        return not _INVENTORY_CUE.search(lowered)
    return False


def _is_arrival_statement(lowered: str) -> bool:
    return bool(
        re.search(
            r"\b(?:i(?:'ll| will)|expect me|my eta|i should (?:reach|be there|arrive|get there)|"
            r"i can (?:reach|get there|arrive|be there))\b",
            lowered,
        )
    )


def _asks_operational_status(lowered: str) -> bool:
    if re.search(r"\b(has|have|is|was|were|did|does)\b.{0,40}\b(?:confirmed|booked)\b", lowered):
        return True
    if re.search(r"\b(?:whether|if)\b.{0,40}\b(?:confirmed|booked)\b", lowered):
        return True
    if re.search(r"\bcheck\b.{0,40}\bconfirmed\b", lowered):
        return True
    return bool(
        re.search(
            r"\b(?:what's my status|what is my status|what's the status|what is the status|"
            r"whats the status|appointment status|where do i stand|did you book)\b",
            lowered,
        )
    )


def _asks_current_appointment_lookup(lowered: str) -> bool:
    if re.search(r"\b(?:option|options|another|can't make|cannot make|won't make|what can i do)\b", lowered):
        return False
    return bool(
        re.search(
            r"\b(?:my appointment time|when is my|when'?s my|what time am i|"
            r"when am i scheduled|my slot|my scheduled)\b",
            lowered,
        )
    )


def _cannot_make(lowered: str) -> bool:
    return any(
        phrase in lowered
        for phrase in (
            "cannot make",
            "can't make",
            "can not make",
            "won't make",
            "will not make",
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
            "late by",
            "arrive late",
            "arrival delayed",
        )
    )


def _has_lateness_language(lowered: str) -> bool:
    return bool(re.search(r"\b(?:late|behind|delayed)\b", lowered))
