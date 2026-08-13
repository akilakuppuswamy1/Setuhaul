"""Shared Pydantic validators for operational schemas."""

from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator


def _require_timezone_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        msg = "timestamp must be timezone-aware"
        raise ValueError(msg)
    return value


TimezoneAwareDatetime = Annotated[datetime, AfterValidator(_require_timezone_aware)]
