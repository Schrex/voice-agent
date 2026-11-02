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


def overdue_request_text(facts: TodayRequestFacts, *, urgency: str, recorded_at: datetime) -> str:
    """E.g. "Overdue: Today request R-1000 from Dale Kramer, Route 104 Widening: tri-axle dump
    trucks, 3 trucks, needed by Sun, Nov 1, 5:00 PM. Recorded Sun, Nov 1, 3:04 PM, not
    Acknowledged" (ticket #22)."""
    return (
        f"Overdue: {urgency} request {request_line(facts)}. "
        f"Recorded {short_time(recorded_at)}, not Acknowledged"
    )


def urgent_note_text(facts: TodayRequestFacts, note: str) -> str:
    """E.g. "Urgent note on R-1000 from Dale Kramer, Route 104 Widening (tri-axle dump trucks):
    “need an answer today”" (spec J3 step 4, AC3.5: the coordinator is alerted)."""
    return (
        f"Urgent note on {facts.ref} from {facts.foreman}, {_job_or_unmatched(facts)} "
        f"({facts.need}): “{note.strip()}”"
    )


def withdrawn_text(facts: TodayRequestFacts) -> str:
    """E.g. "Withdrawn by foreman: R-1000 from Dale Kramer, Route 104 Widening: tri-axle dump
    trucks, 3 trucks, needed by Mon, Nov 2, 7:00 AM" (spec J4, AC4.1: the coordinator is
    notified)."""
    return f"Withdrawn by foreman: {request_line(facts)}"


def _job_or_unmatched(facts: TodayRequestFacts) -> str:
    return facts.job if facts.job is not None else f"“{facts.job_spoken}” (Unmatched)"


def request_line(facts: TodayRequestFacts) -> str:
    """E.g. "R-1000 from Dale Kramer, Route 104 Widening: tri-axle dump trucks, 3 trucks,
    needed by Sun, Nov 1, 5:00 PM" (also used by the end-of-day summary email, #23)."""
    job = _job_or_unmatched(facts)
    amount = " ".join(part for part in (facts.quantity, facts.unit) if part)
    what = f"{facts.need}, {amount}" if amount else facts.need
    text = f"{facts.ref} from {facts.foreman}, {job}: {what}"
    if facts.needed_by is not None:
        return f"{text}, needed by {short_time(facts.needed_by)}"
    if facts.needed_by_spoken:
        return f"{text}, needed by “{facts.needed_by_spoken}”"
    return text


def callback_request_text(*, ref: str, foreman: str, caller_e164: str | None, reason: str) -> str:
    """E.g. "Callback request R-1042 from Dale Kramer (+15855550102), about: the pump"
    (ticket #24). No reason given → "about: not stated", as in the spec J5 transfer text."""
    who = f"{foreman} ({caller_e164})" if caller_e164 else foreman
    return f"Callback request {ref} from {who}, about: {reason or 'not stated'}"


def overdue_callback_text(*, ref: str, foreman: str, reason: str, recorded_at: datetime) -> str:
    """E.g. "Overdue: Callback request R-1042 from Dale Kramer, about: the pump. Recorded Sun,
    Nov 1, 3:04 PM, not Acknowledged" (ticket #22, in #24's Callback wording)."""
    return (
        f"Overdue: Callback request {ref} from {foreman}, about: {reason or 'not stated'}. "
        f"Recorded {short_time(recorded_at)}, not Acknowledged"
    )


NOT_STATED = "not stated"


def transfer_text(foreman: str, job: str | None, job_spoken: str | None, about: str | None) -> str:
    """Spec J5 step 2, verbatim: "Incoming transfer: <foreman>, <job>, about: <need or 'not
    stated'>". An Unmatched Job is quoted as said (as in the Today text); a Job not said at all
    is "not stated" too (open question on #25)."""
    need = about.strip() if about and about.strip() else NOT_STATED
    return f"Incoming transfer: {foreman}, {_job_text(job, job_spoken)}, about: {need}"


def _job_text(job: str | None, job_spoken: str | None) -> str:
    """The Job's name; else `“said” (Unmatched)`; else "not stated" (#25 open question 1)."""
    if job is not None:
        return job
    if job_spoken and job_spoken.strip():
        return f"“{job_spoken.strip()}” (Unmatched)"
    return NOT_STATED


def emergency_text(foreman: str, job: str | None, job_spoken: str | None, summary: str) -> str:
    """Spec J6 step 3, verbatim: "EMERGENCY call from <foreman>, <job>: <summary>" (ticket #26).

    The Job as in the transfer text: its name, else quoted as said (Unmatched), else "not
    stated". `summary` is the Foreman's own words for what happened.
    """
    return f"EMERGENCY call from {foreman}, {_job_text(job, job_spoken)}: {summary.strip()}"
