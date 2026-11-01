"""Local (America/New_York) time as the voice agent hears it. Pure: the caller passes `now`."""

from datetime import datetime
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/New_York")


def speakable_local_time(now: datetime) -> str:
    """E.g. "Sunday, November 1, 2026, 3:04 PM" for 2026-11-01T20:04Z. `now` must be aware."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local = now.astimezone(LOCAL_TZ)
    hour = local.hour % 12 or 12
    meridiem = "AM" if local.hour < 12 else "PM"
    return f"{local:%A}, {local:%B} {local.day}, {local.year}, {hour}:{local.minute:02d} {meridiem}"
