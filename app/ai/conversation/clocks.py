"""Local clock constraints from driver language. No travel or unload invention."""

from __future__ import annotations

import re
from datetime import datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_CLOCK = (
    r"(?P<hour>\d{1,2})(?::(?P<minute>[0-5]\d))?\s*(?P<meridiem>a\.?m\.?|p\.?m\.?)?"
)
_AFTER = re.compile(
    r"(?:after|later than|later then)\s+" + _CLOCK,
    flags=re.IGNORECASE,
)
_LEAVE_BY = re.compile(
    r"(?:leave by|leaving by|have to leave by|need to leave by|must leave by|"
    r"got to leave by|gotta leave by)\s+" + _CLOCK,
    flags=re.IGNORECASE,
)
_ETA = re.compile(
    r"(?:(?:i(?:'ll| will)\s+)?reach(?:\s+around)?|arrive(?:\s+around)?|"
    r"(?:my\s+)?eta(?:\s+is)?|reach around)\s+" + _CLOCK,
    flags=re.IGNORECASE,
)
_SUPPOSED = re.compile(r"supposed to\s+(?:reach|arrive)", flags=re.IGNORECASE)


def parse_earliest_start_local(lowered: str) -> str | None:
    match = _AFTER.search(lowered)
    if match is None:
        return None
    return _match_to_hhmm(match)


def parse_leave_by_local(lowered: str) -> str | None:
    match = _LEAVE_BY.search(lowered)
    if match is None:
        return None
    return _match_to_hhmm(match)


def parse_eta_local(lowered: str) -> str | None:
    last: str | None = None
    for match in _ETA.finditer(lowered):
        start = match.start()
        prefix = lowered[max(0, start - 24) : start]
        if _SUPPOSED.search(prefix):
            continue
        last = _match_to_hhmm(match)
    return last


def asks_informal_options(lowered: str) -> bool:
    return any(
        phrase in lowered
        for phrase in (
            "anything after",
            "anything later",
            "any slots after",
            "slots after",
            "come after",
            "options after",
            "available after",
            "do you have anything",
            "later than",
            "anything available after",
        )
    )


def slot_starts_on_or_after(
    start: datetime | None,
    earliest_hhmm: str | None,
    timezone_name: str | None,
) -> bool | None:
    if not earliest_hhmm:
        return True
    if start is None:
        return None
    bound = localize_clock_on(start, earliest_hhmm, timezone_name)
    if bound is None:
        return None
    return _aware(start) >= bound


def slot_ends_on_or_before(
    end: datetime | None,
    leave_by_hhmm: str | None,
    timezone_name: str | None,
) -> bool | None:
    if not leave_by_hhmm:
        return True
    if end is None:
        return None
    bound = localize_clock_on(end, leave_by_hhmm, timezone_name)
    if bound is None:
        return None
    return _aware(end) <= bound


def localize_clock_on(
    reference: datetime,
    hhmm: str,
    timezone_name: str | None,
) -> datetime | None:
    parsed = parse_hhmm(hhmm)
    if parsed is None:
        return None
    hour, minute = parsed
    tz = resolve_zone(timezone_name)
    local_ref = _aware(reference).astimezone(tz)
    return datetime.combine(local_ref.date(), time(hour, minute), tzinfo=tz)


def resolve_zone(timezone_name: str | None) -> ZoneInfo:
    name = (timezone_name or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        return ZoneInfo("UTC")


def parse_hhmm(value: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", value.strip())
    if match is None:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def _match_to_hhmm(match: re.Match[str]) -> str | None:
    hour = int(match.group("hour"))
    minute = int(match.group("minute") or 0)
    meridiem = (match.group("meridiem") or "").lower().replace(".", "")
    if hour > 23 or minute > 59:
        return None
    if meridiem.startswith("p") and hour < 12:
        hour += 12
    elif meridiem.startswith("a") and hour == 12:
        hour = 0
    elif not meridiem and 1 <= hour <= 11:
        hour += 12
    if hour > 23:
        return None
    return f"{hour:02d}:{minute:02d}"


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=ZoneInfo("UTC"))
    return value
