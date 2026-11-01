"""End-of-day summary email (ticket #23): when it is due, what it covers, what it says.

Pure domain; times in America/New_York, `now` explicit.
"""

from datetime import UTC, date, datetime

from app.domain.eod_summary import (
    OpenCounts,
    is_due,
    summary_day,
    summary_subject,
    summary_text,
    summary_window,
)
from app.domain.sms_text import TodayRequestFacts

PLANNED = TodayRequestFacts(
    ref="R-1001",
    foreman="Dale Kramer",
    job="Route 104 Widening",
    job_spoken="the 104 job",
    need="tri-axle dump trucks",
    quantity="3",
    unit="trucks",
    # Tue, Nov 3, 7:00 AM in New York (EST).
    needed_by=datetime(2026, 11, 3, 12, 0, tzinfo=UTC),
    needed_by_spoken="Tuesday at seven",
)


def test_not_due_before_five_pm_new_york() -> None:
    # 4:59 PM EST on Mon, Nov 2 (UTC 21:59).
    assert not is_due(datetime(2026, 11, 2, 21, 59, tzinfo=UTC))


def test_due_from_five_pm_new_york_to_midnight() -> None:
    assert is_due(datetime(2026, 11, 2, 22, 0, tzinfo=UTC))  # 5:00 PM EST
    assert is_due(datetime(2026, 11, 3, 4, 59, tzinfo=UTC))  # 11:59 PM EST


def test_the_summary_day_is_the_new_york_date() -> None:
    # 8:30 PM EST Mon, Nov 2 is already Nov 3 in UTC.
    assert summary_day(datetime(2026, 11, 3, 1, 30, tzinfo=UTC)) == date(2026, 11, 2)


def test_window_is_previous_five_pm_to_this_five_pm_new_york() -> None:
    start, end = summary_window(date(2026, 11, 2))
    assert start == datetime(2026, 11, 1, 22, 0, tzinfo=UTC)  # Sun 5:00 PM EST
    assert end == datetime(2026, 11, 2, 22, 0, tzinfo=UTC)  # Mon 5:00 PM EST


def test_window_over_the_fall_back_change_is_25_hours() -> None:
    # Clocks fall back at 2 AM on Sun, Nov 1, 2026: Sat 5 PM is EDT, Sun 5 PM is EST.
    start, end = summary_window(date(2026, 11, 1))
    assert start == datetime(2026, 10, 31, 21, 0, tzinfo=UTC)
    assert end == datetime(2026, 11, 1, 22, 0, tzinfo=UTC)


def test_subject_names_the_day() -> None:
    assert summary_subject(date(2026, 11, 2)) == "End-of-day summary, Mon, Nov 2"


def test_text_lists_each_new_planned_request_and_the_open_counts() -> None:
    text = summary_text(
        date(2026, 11, 2),
        [(PLANNED, "Recorded")],
        OpenCounts(recorded=2, acknowledged=1, in_progress=3),
    )
    assert text == (
        "End-of-day summary, Mon, Nov 2\n"
        "\n"
        "New Planned requests since Sun, Nov 1, 5:00 PM: 1\n"
        "- R-1001 from Dale Kramer, Route 104 Widening: tri-axle dump trucks, 3 trucks, "
        "needed by Tue, Nov 3, 7:00 AM (Recorded)\n"
        "\n"
        "Open requests: 6\n"
        "- Recorded: 2\n"
        "- Acknowledged: 1\n"
        "- In Progress: 3\n"
    )


def test_text_with_no_new_planned_requests_says_none() -> None:
    none_open = OpenCounts(recorded=0, acknowledged=0, in_progress=0)
    text = summary_text(date(2026, 11, 2), [], none_open)
    assert "New Planned requests since Sun, Nov 1, 5:00 PM: 0\n- None\n" in text
    assert "Open requests: 0\n" in text
