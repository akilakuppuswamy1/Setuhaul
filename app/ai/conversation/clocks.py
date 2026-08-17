"""Local clock constraints from driver language. No travel or unload invention."""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_CLOCK = (
    r"(?P<hour>\d{1,2})(?:[:.\s](?P<minute>[0-5]\d))?\s*(?P<meridiem>a\.?m\.?|p\.?m\.?)?"
)
_AFTER = re.compile(
    r"(?:after|later than|later then)\s+" + _CLOCK,
    flags=re.IGNORECASE,
)
_DEADLINE = re.compile(
    r"\b(?:by|before)\s+" + _CLOCK,
    flags=re.IGNORECASE,
)
_LEAVE_BY = re.compile(
    r"(?:leave by|leaving by|have to leave by|need to leave by|must leave by|"
    r"got to leave by|gotta leave by)\s+" + _CLOCK,
    flags=re.IGNORECASE,
)
_ARRIVAL_CUE = re.compile(
    r"\b(?:reach|arrive|arriving|be there|get there|expect me|show up|(?:my\s+)?eta)\b",
    flags=re.IGNORECASE,
)
_SUPPOSED = re.compile(r"supposed to\s+(?:reach|arrive)", flags=re.IGNORECASE)
_SUPPOSED_CLOCK = re.compile(
    r"supposed to\s+(?:reach|arrive)(?:\s+by)?\s+" + _CLOCK,
    flags=re.IGNORECASE,
)
_RELATIVE_DELAY_AFTER_CLOCK = re.compile(
    r"^\s*(?:hours?|hrs?|minutes?)\s+(?:late|behind)\b",
    flags=re.IGNORECASE,
)


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


def parse_original_appointment_local(lowered: str) -> str | None:
    match = _SUPPOSED_CLOCK.search(lowered)
    if match is None:
        return None
    return _match_to_hhmm(match)


def parse_completion_by_local(lowered: str) -> str | None:
    """Clock after by/before when asking whether the current plan finishes in time."""
    last: str | None = None
    for match in _DEADLINE.finditer(lowered):
        prefix = lowered[max(0, match.start() - 20) : match.start()]
        if re.search(r"\bleav(?:e|ing)\b", prefix, flags=re.IGNORECASE):
            continue
        hhmm = _match_to_hhmm(match)
        if hhmm:
            last = hhmm
    return last


def parse_eta_local(lowered: str) -> str | None:
    """Explicit arrival clock. Leave-by and 'N hours late' are not arrival times."""
    last: str | None = None
    for cue in _ARRIVAL_CUE.finditer(lowered):
        prefix = lowered[max(0, cue.start() - 24) : cue.start()]
        if _SUPPOSED.search(prefix):
            continue
        window = lowered[cue.end() : cue.end() + 48]
        match = re.search(_CLOCK, window, flags=re.IGNORECASE)
        if match is None:
            continue
        if _RELATIVE_DELAY_AFTER_CLOCK.search(window[match.end() :]):
            continue
        hhmm = _match_to_hhmm(match)
        if hhmm:
            last = hhmm
    return last


def asks_informal_options(lowered: str) -> bool:
    if re.search(
        r"\b(?:any(?:thing)?|something)\b.{0,28}\b(?:after|later|open|available|tonight|around then)\b",
        lowered,
        flags=re.IGNORECASE,
    ):
        return True
    if re.search(r"\b(?:later|after)\s+than\b", lowered, flags=re.IGNORECASE):
        return True
    if re.search(r"\bdo you have anything\b", lowered, flags=re.IGNORECASE):
        return True
    if re.search(r"\b(?:slots?|options?)\s+after\b", lowered, flags=re.IGNORECASE):
        return True
    return bool(re.search(r"\b(?:come|available)\s+after\b", lowered, flags=re.IGNORECASE))


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


def localize_operational_clock(
    reference: datetime,
    hhmm: str,
    timezone_name: str | None,
) -> datetime | None:
    """Place a local clock on the operational day of `reference`.

    Early-morning clocks (before noon) that accompany an afternoon/evening
    reference roll to the next calendar day so 2:00 AM after 8:30 PM is overnight,
    not the same morning.
    """
    bound = localize_clock_on(reference, hhmm, timezone_name)
    if bound is None:
        return None
    parsed = parse_hhmm(hhmm)
    if parsed is None:
        return bound
    hour, _minute = parsed
    local_ref = _aware(reference).astimezone(resolve_zone(timezone_name))
    if hour < 12 and local_ref.hour >= 12:
        return bound + timedelta(days=1)
    return bound


def resolve_zone(timezone_name: str | None) -> ZoneInfo:
    name = (timezone_name or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        return ZoneInfo("UTC")


def parse_clock_tokens(lowered: str) -> list[str]:
    found: list[str] = []
    for match in re.finditer(_CLOCK, lowered, flags=re.IGNORECASE):
        following = lowered[match.end() : match.end() + 16]
        if re.match(r"\s*(?:hours?|hrs?|minutes?)\b", following):
            continue
        hhmm = _match_to_hhmm(match)
        if hhmm:
            found.append(hhmm)
    return found


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
