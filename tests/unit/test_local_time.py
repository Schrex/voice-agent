from datetime import UTC, datetime

import pytest

from app.domain.local_time import speakable_local_time


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        # Standard time (EST, UTC-5): DST ended at 06:00Z on 1 Nov 2026.
        (datetime(2026, 11, 1, 20, 4, tzinfo=UTC), "Sunday, November 1, 2026, 3:04 PM"),
        # Daylight time (EDT, UTC-4).
        (datetime(2026, 7, 15, 11, 30, tzinfo=UTC), "Wednesday, July 15, 2026, 7:30 AM"),
        # UTC date already tomorrow; local date is still today, late evening.
        (datetime(2026, 11, 3, 2, 15, tzinfo=UTC), "Monday, November 2, 2026, 9:15 PM"),
        # Midnight and noon.
        (datetime(2026, 1, 5, 5, 0, tzinfo=UTC), "Monday, January 5, 2026, 12:00 AM"),
        (datetime(2026, 1, 5, 17, 0, tzinfo=UTC), "Monday, January 5, 2026, 12:00 PM"),
    ],
)
def test_speakable_local_time_is_new_york_time(now: datetime, expected: str) -> None:
    assert speakable_local_time(now) == expected


def test_naive_time_is_refused() -> None:
    with pytest.raises(ValueError):
        speakable_local_time(datetime(2026, 11, 1, 20, 4))
