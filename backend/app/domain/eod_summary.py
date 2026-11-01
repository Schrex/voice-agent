"""End-of-day summary email (ticket #23; spec J1 step 8, J9 "Alerts"; architecture §6).

At 17:00 New York time the Coordinators get one email listing the new Planned Requests and the
open counts. "New" = Recorded in the 24 hours up to that 17:00 (since the previous summary).
Pure: facts in, text out; only facts on the Request records (no ETA, no availability).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from app.domain.local_time import LOCAL_TZ
from app.domain.sms_text import TodayRequestFacts, request_line, short_date, short_time

SUMMARY_TIME = time(17, 0)


@dataclass(frozen=True)
class OpenCounts:
    recorded: int
    acknowledged: int
    in_progress: int

    @property
    def total(self) -> int:
        return self.recorded + self.acknowledged + self.in_progress


def summary_day(now: datetime) -> date:
    """The New York date whose summary `now` belongs to."""
    return now.astimezone(LOCAL_TZ).date()


def is_due(now: datetime) -> bool:
    """True from 17:00 New York time until midnight (a late start still sends that day's)."""
    return now.astimezone(LOCAL_TZ).time() >= SUMMARY_TIME


def summary_window(day: date) -> tuple[datetime, datetime]:
    """(start, end]: the previous day's 17:00 to `day`'s 17:00, New York time."""
    end = datetime.combine(day, SUMMARY_TIME, tzinfo=LOCAL_TZ)
    start = datetime.combine(day - timedelta(days=1), SUMMARY_TIME, tzinfo=LOCAL_TZ)
    return start, end


def summary_subject(day: date) -> str:
    return f"End-of-day summary, {short_date(day)}"


def summary_text(
    day: date, planned: Sequence[tuple[TodayRequestFacts, str]], counts: OpenCounts
) -> str:
    """Plain-text body. `planned` is each new Planned Request with its current status."""
    start, _ = summary_window(day)
    lines = [
        summary_subject(day),
        "",
        f"New Planned requests since {short_time(start)}: {len(planned)}",
    ]
    lines += [f"- {request_line(facts)} ({status})" for facts, status in planned] or ["- None"]
    lines += [
        "",
        f"Open requests: {counts.total}",
        f"- Recorded: {counts.recorded}",
        f"- Acknowledged: {counts.acknowledged}",
        f"- In Progress: {counts.in_progress}",
    ]
    return "\n".join(lines) + "\n"
