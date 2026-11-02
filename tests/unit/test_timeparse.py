"""Spoken needed-by → a time in America/New_York, and its Urgency (ticket #14). Pure, table-driven.

Expected instants are worked out by hand from the New York offset on that date:
EDT (UTC-4) until 06:00Z on Sun 1 Nov 2026, EST (UTC-5) after; EDT again from Sun 8 Mar 2026.
"""

from datetime import UTC, date, datetime, time

import pytest

from app.domain.timeparse import NeededBy, parse_needed_by, speakable, urgency_for
from app.domain.urgency import Urgency

# Sunday, November 1, 2026, 3:04 PM EST: the day DST ended.
SUN_AFTERNOON = datetime(2026, 11, 1, 20, 4, tzinfo=UTC)
# Saturday, October 31, 2026, 11:50 PM EDT: a late-night call; "tomorrow" is the DST change day.
SAT_LATE = datetime(2026, 11, 1, 3, 50, tzinfo=UTC)
# Sunday, November 1, 2026, 11:50 PM EST.
SUN_LATE = datetime(2026, 11, 2, 4, 50, tzinfo=UTC)
# Sunday, November 1, 2026, 12:30 AM EDT: just after midnight.
SUN_JUST_AFTER_MIDNIGHT = datetime(2026, 11, 1, 4, 30, tzinfo=UTC)
# Saturday, March 7, 2026, 10:00 AM EST: "tomorrow" is the day DST starts.
SAT_BEFORE_SPRING_FORWARD = datetime(2026, 3, 7, 15, 0, tzinfo=UTC)


def utc(month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=UTC)


@pytest.mark.parametrize(
    ("spoken", "now", "expected_utc"),
    [
        # Day + clock time; Mon 2 Nov is EST, so 7:00 AM local = 12:00Z.
        ("tomorrow at seven", SUN_AFTERNOON, utc(11, 2, 12)),
        ("Tomorrow at 7 AM.", SUN_AFTERNOON, utc(11, 2, 12)),
        ("tomorrow at 7:30 a.m.", SUN_AFTERNOON, utc(11, 2, 12, 30)),
        ("by seven o'clock tomorrow", SUN_AFTERNOON, utc(11, 2, 12)),
        ("tomorrow at 19:00", SUN_AFTERNOON, utc(11, 3, 0)),
        ("tomorrow at seven in the evening", SUN_AFTERNOON, utc(11, 3, 0)),
        ("tomorrow at 2", SUN_AFTERNOON, utc(11, 2, 19)),
        ("noon tomorrow", SUN_AFTERNOON, utc(11, 2, 17)),
        # Named times.
        ("first thing tomorrow", SUN_AFTERNOON, utc(11, 2, 12)),
        ("tomorrow, first thing in the morning", SUN_AFTERNOON, utc(11, 2, 12)),
        ("tomorrow morning", SUN_AFTERNOON, utc(11, 2, 12)),
        ("tomorrow morning at six thirty", SUN_AFTERNOON, utc(11, 2, 11, 30)),
        ("tomorrow afternoon around 3", SUN_AFTERNOON, utc(11, 2, 20)),
        ("this afternoon", SUN_AFTERNOON, utc(11, 1, 18)),
        # Weekdays: the next one after today.
        ("Tuesday at seven forty-five", SUN_AFTERNOON, utc(11, 3, 12, 45)),
        ("this Wednesday at 3 pm", SUN_AFTERNOON, utc(11, 4, 20)),
        ("Sunday at 7", SUN_AFTERNOON, utc(11, 8, 12)),
        # No day said: the next time it comes round.
        ("at four", SUN_AFTERNOON, utc(11, 1, 21)),
        ("by two", SUN_AFTERNOON, utc(11, 2, 19)),
        ("first thing", SUN_AFTERNOON, utc(11, 2, 12)),
        # A call at 11:50 PM, the night before DST ends: 7:00 AM Sunday is EST (UTC-5).
        ("tomorrow at seven", SAT_LATE, utc(11, 1, 12)),
        ("first thing", SAT_LATE, utc(11, 1, 12)),
        # A call at 11:50 PM on a plain night.
        ("tomorrow at seven", SUN_LATE, utc(11, 2, 12)),
        ("today at 23:55", SUN_LATE, utc(11, 2, 4, 55)),
        # Just after midnight, "first thing" is this morning.
        ("first thing", SUN_JUST_AFTER_MIDNIGHT, utc(11, 1, 12)),
        # The day DST starts: 7:00 AM Sunday 8 March is EDT (UTC-4).
        ("tomorrow at seven", SAT_BEFORE_SPRING_FORWARD, utc(3, 8, 11)),
    ],
)
def test_spoken_time_resolves_to_a_new_york_time(
    spoken: str, now: datetime, expected_utc: datetime
) -> None:
    resolved = parse_needed_by(spoken, now)
    assert resolved is not None
    assert resolved.at == expected_utc


@pytest.mark.parametrize(
    ("spoken", "expected_day"),
    [
        ("tomorrow", date(2026, 11, 2)),
        ("Friday", date(2026, 11, 6)),
        ("today", date(2026, 11, 1)),
    ],
)
def test_a_day_without_a_time_keeps_the_time_unknown(spoken: str, expected_day: date) -> None:
    assert parse_needed_by(spoken, SUN_AFTERNOON) == NeededBy(expected_day, None)


@pytest.mark.parametrize(
    "spoken",
    [
        "",
        "I don't know",
        "not sure yet",
        "next Tuesday",
        "end of the day",
        "tomorrow evening",
        "tomorrow at seven or eight",
        "Tuesday tomorrow",
        "seven pm in the morning",
        "noon in the morning",
        "tomorrow at 25:00",
        "tomorrow at 7:75",
        "this",
        "pm",
    ],
)
def test_what_is_not_understood_is_not_guessed(spoken: str) -> None:
    assert parse_needed_by(spoken, SUN_AFTERNOON) is None


@pytest.mark.parametrize(
    ("spoken", "now", "expected"),
    [
        ("this afternoon", SUN_AFTERNOON, Urgency.TODAY),
        ("at four", SUN_AFTERNOON, Urgency.TODAY),
        ("today", SUN_AFTERNOON, Urgency.TODAY),
        ("tomorrow at seven", SUN_AFTERNOON, Urgency.PLANNED),
        ("Friday", SUN_AFTERNOON, Urgency.PLANNED),
        # A time already passed today rolls to tomorrow: Planned.
        ("by two", SUN_AFTERNOON, Urgency.PLANNED),
        # Local day decides, not UTC: 11:55 PM EST is already 2 Nov in UTC.
        ("today at 23:55", SUN_LATE, Urgency.TODAY),
        # Late-night "tomorrow" is the next calendar day (spec §12 cut-off is an open question).
        ("tomorrow at seven", SAT_LATE, Urgency.PLANNED),
        ("first thing", SUN_JUST_AFTER_MIDNIGHT, Urgency.TODAY),
    ],
)
def test_urgency_is_today_when_needed_today_else_planned(
    spoken: str, now: datetime, expected: Urgency
) -> None:
    resolved = parse_needed_by(spoken, now)
    assert resolved is not None
    assert urgency_for(resolved, now) == expected


@pytest.mark.parametrize(
    ("needed_by", "expected"),
    [
        (NeededBy(date(2026, 11, 2), time(7, 0)), "Monday, November 2 at 7:00 AM"),
        (NeededBy(date(2026, 11, 3), time(12, 0)), "Tuesday, November 3 at 12:00 PM"),
        (NeededBy(date(2026, 11, 3), time(19, 45)), "Tuesday, November 3 at 7:45 PM"),
        (NeededBy(date(2026, 11, 6), None), "Friday, November 6"),
    ],
)
def test_read_back_names_the_weekday_and_date_never_tomorrow(
    needed_by: NeededBy, expected: str
) -> None:
    assert speakable(needed_by) == expected


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("tomorrow 7am", utc(11, 2, 12)),
        ("tomorrow 7:30pm", utc(11, 3, 0, 30)),
        ("Tuesday 10AM", utc(11, 3, 15)),
    ],
)
def test_am_pm_typed_against_the_hour_is_understood(typed: str, expected: datetime) -> None:
    """A coordinator types "7am" where a transcript has "7 am" (quick entry, ticket #30)."""
    needed_by = parse_needed_by(typed, SUN_AFTERNOON)
    assert needed_by is not None
    assert needed_by.at == expected


def test_naive_now_is_refused() -> None:
    with pytest.raises(ValueError):
        parse_needed_by("tomorrow at seven", datetime(2026, 11, 1, 15, 4))


def test_speakable_at_reads_an_instant_in_new_york_time() -> None:
    from app.domain.timeparse import speakable_at

    assert speakable_at(utc(11, 2, 12, 0)) == "Monday, November 2 at 7:00 AM"


# Spec §5: Today = "needed today or work stopped"; "need it now" is needed at the call time.
@pytest.mark.parametrize(
    ("spoken", "now", "expected_utc"),
    [
        ("now", SUN_AFTERNOON, utc(11, 1, 20, 4)),
        ("right now", SUN_AFTERNOON, utc(11, 1, 20, 4)),
        ("Right now!", SUN_AFTERNOON, utc(11, 1, 20, 4)),
        ("ASAP", SUN_AFTERNOON, utc(11, 1, 20, 4)),
        ("a.s.a.p.", SUN_AFTERNOON, utc(11, 1, 20, 4)),
        ("as soon as possible", SUN_AFTERNOON, utc(11, 1, 20, 4)),
        ("immediately", SUN_AFTERNOON, utc(11, 1, 20, 4)),
        # Late at night "now" is still the call's own day and minute.
        ("now", SUN_LATE, utc(11, 2, 4, 50)),
    ],
)
def test_now_words_resolve_to_the_call_time_and_are_today(
    spoken: str, now: datetime, expected_utc: datetime
) -> None:
    resolved = parse_needed_by(spoken, now)
    assert resolved is not None
    assert resolved.at == expected_utc
    assert urgency_for(resolved, now) == Urgency.TODAY


@pytest.mark.parametrize("spoken", ["now tomorrow", "tomorrow right now", "now at seven"])
def test_now_with_another_time_is_not_guessed(spoken: str) -> None:
    assert parse_needed_by(spoken, SUN_AFTERNOON) is None


@pytest.mark.parametrize(
    ("from_needed_by", "said", "expected"),
    [
        # Keywords decide only when the needed-by gave no Urgency.
        (None, "we're stopped, need a pump", Urgency.TODAY),
        (None, "the crew is shut down without it", Urgency.TODAY),
        (None, "we're waiting on it", Urgency.TODAY),
        (None, "Work STOPPED on the trench", Urgency.TODAY),
        (None, "a lowboy for the dozer", None),
        (None, "the unstoppable crew", None),
        (None, "", None),
        # A said needed-by wins: keywords never override it.
        (Urgency.PLANNED, "we're stopped", Urgency.PLANNED),
        (Urgency.TODAY, "a lowboy", Urgency.TODAY),
    ],
)
def test_work_stopped_keywords_make_a_request_today_when_no_needed_by_says(
    from_needed_by: Urgency | None, said: str, expected: Urgency | None
) -> None:
    from app.domain.urgency import infer_urgency

    assert infer_urgency(from_needed_by, said) == expected
