"""Wording of the new-Today-Request SMS (ticket #21): facts from the Request only."""

from datetime import UTC, datetime

from app.domain.sms_text import TodayRequestFacts, overdue_request_text, today_request_text

FACTS = TodayRequestFacts(
    ref="R-1000",
    foreman="Dale Kramer",
    job="Route 104 Widening",
    job_spoken="the 104 job",
    need="tri-axle dump trucks",
    quantity="3",
    unit="trucks",
    # 7:00 AM in New York on the day after the fall-back change (EST).
    needed_by=datetime(2026, 11, 2, 12, 0, tzinfo=UTC),
    needed_by_spoken="first thing tomorrow",
)


def test_names_ref_foreman_job_need_amount_and_new_york_needed_by() -> None:
    assert today_request_text(FACTS) == (
        "Today request R-1000 from Dale Kramer, Route 104 Widening: "
        "tri-axle dump trucks, 3 trucks, needed by Mon, Nov 2, 7:00 AM"
    )


def test_unmatched_job_is_quoted_as_said() -> None:
    text = today_request_text(
        TodayRequestFacts(**{**FACTS.__dict__, "job": None, "quantity": None, "unit": None})
    )
    assert text == (
        "Today request R-1000 from Dale Kramer, “the 104 job” (Unmatched): "
        "tri-axle dump trucks, needed by Mon, Nov 2, 7:00 AM"
    )


def test_a_day_without_a_time_gives_the_words_as_said() -> None:
    text = today_request_text(
        TodayRequestFacts(**{**FACTS.__dict__, "needed_by": None, "needed_by_spoken": "today"})
    )
    assert text.endswith("tri-axle dump trucks, 3 trucks, needed by “today”")


def test_overdue_names_urgency_the_request_and_when_it_was_recorded() -> None:
    """Ticket #22: the backup's text; facts from the record only (no ETA)."""
    text = overdue_request_text(
        FACTS, urgency="Planned", recorded_at=datetime(2026, 11, 1, 20, 4, tzinfo=UTC)
    )
    assert text == (
        "Overdue: Planned request R-1000 from Dale Kramer, Route 104 Widening: "
        "tri-axle dump trucks, 3 trucks, needed by Mon, Nov 2, 7:00 AM. "
        "Recorded Sun, Nov 1, 3:04 PM, not Acknowledged"
    )
