"""Uninformed math (ticket #32; spec §4, §5 flags, AC9.4; architecture §5 "Derived, not stored").

Uninformed = Resolved, not marked Foreman Informed, and more than 2 h since it was Resolved.
The clock is frozen: every check takes `now` explicitly.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.lifecycle import Status
from app.domain.sla import UNINFORMED_AFTER, is_uninformed, uninformed_cutoff

RESOLVED_AT = datetime(2026, 11, 1, 14, 0, tzinfo=UTC)  # 9:00 AM in New York


def test_the_uninformed_threshold_is_two_hours() -> None:
    assert timedelta(hours=2) == UNINFORMED_AFTER


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (RESOLVED_AT, False),
        (datetime(2026, 11, 1, 15, 59, 59, tzinfo=UTC), False),
        (datetime(2026, 11, 1, 16, 0, tzinfo=UTC), False),  # exactly 2 h: not yet
        (datetime(2026, 11, 1, 16, 0, 1, tzinfo=UTC), True),
        (datetime(2026, 11, 2, 9, 0, tzinfo=UTC), True),
    ],
)
def test_a_resolved_request_not_informed_is_uninformed_only_after_two_hours(
    now: datetime, expected: bool
) -> None:
    assert (
        is_uninformed(Status.RESOLVED, resolved_at=RESOLVED_AT, foreman_informed_at=None, now=now)
        is expected
    )


def test_marking_foreman_informed_clears_uninformed() -> None:
    late = datetime(2026, 11, 1, 18, 0, tzinfo=UTC)

    assert not is_uninformed(
        Status.RESOLVED, resolved_at=RESOLVED_AT, foreman_informed_at=late, now=late
    )


@pytest.mark.parametrize(
    "status", [Status.DRAFT, Status.RECORDED, Status.ACKNOWLEDGED, Status.IN_PROGRESS]
)
def test_a_request_that_is_not_resolved_is_never_uninformed(status: Status) -> None:
    now = datetime(2026, 11, 3, tzinfo=UTC)

    assert not is_uninformed(status, resolved_at=None, foreman_informed_at=None, now=now)


def test_requests_resolved_before_the_cutoff_are_uninformed_now() -> None:
    now = datetime(2026, 11, 1, 16, 0, 1, tzinfo=UTC)

    assert uninformed_cutoff(now) == datetime(2026, 11, 1, 14, 0, 1, tzinfo=UTC)


def test_a_request_merged_into_another_is_never_uninformed() -> None:
    """Product owner decision on #32/#33: the surviving Request carries the flag."""
    now = RESOLVED_AT + timedelta(days=1)
    assert not is_uninformed(
        Status.RESOLVED, resolved_at=RESOLVED_AT, foreman_informed_at=None, now=now, merged=True
    )
