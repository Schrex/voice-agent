"""Alert SMS wording. Pure: facts in, text out; times in America/New_York.

Only facts on the Request record go into a text (no ETA, no availability).
"""

from dataclasses import dataclass
from datetime import date, datetime

from app.domain.local_time import LOCAL_TZ


@dataclass(frozen=True)
class TodayRequestFacts:
    ref: str
    foreman: str
    job: str | None
    """The Job's name; None when Unmatched."""
    job_spoken: str
    need: str
    quantity: str | None
    """As said: "3", "2.5"."""
    unit: str | None
    needed_by: datetime | None
    needed_by_spoken: str | None


def short_time(at: datetime) -> str:
    """E.g. "Sun, Nov 1, 5:00 PM" (the dashboard's format), in New York time."""
    local = at.astimezone(LOCAL_TZ)
    hour = local.hour % 12 or 12
    meridiem = "AM" if local.hour < 12 else "PM"
    return f"{local:%a}, {local:%b} {local.day}, {hour}:{local.minute:02d} {meridiem}"


def short_date(day: date) -> str:
    """E.g. "Sun, Nov 1"."""
    return f"{day:%a}, {day:%b} {day.day}"


def today_request_text(facts: TodayRequestFacts) -> str:
    """E.g. "Today request R-1000 from Dale Kramer, Route 104 Widening: tri-axle dump trucks,
    3 trucks, needed by Sun, Nov 1, 5:00 PM"."""
    return f"Today request {request_line(facts)}"


def request_line(facts: TodayRequestFacts) -> str:
    """E.g. "R-1000 from Dale Kramer, Route 104 Widening: tri-axle dump trucks, 3 trucks,
    needed by Sun, Nov 1, 5:00 PM" (also used by the end-of-day summary email, #23)."""
    job = facts.job if facts.job is not None else f"“{facts.job_spoken}” (Unmatched)"
    amount = " ".join(part for part in (facts.quantity, facts.unit) if part)
    what = f"{facts.need}, {amount}" if amount else facts.need
    text = f"{facts.ref} from {facts.foreman}, {job}: {what}"
    if facts.needed_by is not None:
        return f"{text}, needed by {short_time(facts.needed_by)}"
    if facts.needed_by_spoken:
        return f"{text}, needed by “{facts.needed_by_spoken}”"
    return text
