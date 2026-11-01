"""Overdue math (ticket #22; spec §4 ack windows, §5 flags, AC9.3; architecture §5 "Derived").

Overdue = still Recorded and `now > ack_due_at`; `ack_due_at` = when it was Recorded plus the
ack window of its Urgency (Today 15 min, Planned 2 h by default). The clock is frozen: every
check takes `now` explicitly.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.lifecycle import Status
from app.domain.sla import AckWindows, ack_due_at, is_overdue
from app.domain.urgency import Urgency

RECORDED_AT = datetime(2026, 11, 1, 20, 4, tzinfo=UTC)  # 3:04 PM in New York
DEFAULT = AckWindows()


def test_the_default_ack_windows_are_15_minutes_for_today_and_2_hours_for_planned() -> None:
    assert (DEFAULT.today, DEFAULT.planned) == (timedelta(minutes=15), timedelta(hours=2))


def test_a_today_request_is_due_15_minutes_after_it_was_recorded() -> None:
    assert ack_due_at(Urgency.TODAY, RECORDED_AT, DEFAULT) == datetime(
        2026, 11, 1, 20, 19, tzinfo=UTC
    )


def test_a_planned_request_is_due_2_hours_after_it_was_recorded() -> None:
    assert ack_due_at(Urgency.PLANNED, RECORDED_AT, DEFAULT) == datetime(
        2026, 11, 1, 22, 4, tzinfo=UTC
    )


def test_the_windows_are_the_offices_settings() -> None:
    windows = AckWindows(today=timedelta(minutes=5), planned=timedelta(minutes=30))
    assert ack_due_at(Urgency.TODAY, RECORDED_AT, windows) == RECORDED_AT + timedelta(minutes=5)
    assert ack_due_at(Urgency.PLANNED, RECORDED_AT, windows) == RECORDED_AT + timedelta(minutes=30)


@pytest.mark.parametrize("urgency", [Urgency.EMERGENCY, None])
def test_no_window_is_set_where_the_spec_gives_none(urgency: Urgency | None) -> None:
    """Spec §4 gives windows for Today/Callback and Planned only (open question on #22)."""
    assert ack_due_at(urgency, RECORDED_AT, DEFAULT) is None


DUE = datetime(2026, 11, 1, 20, 19, tzinfo=UTC)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (RECORDED_AT, False),
        (datetime(2026, 11, 1, 20, 18, 59, tzinfo=UTC), False),
        (DUE, False),  # exactly at the boundary: not yet
        (datetime(2026, 11, 1, 20, 19, 0, 1, tzinfo=UTC), True),
        (datetime(2026, 11, 2, 12, 0, tzinfo=UTC), True),
    ],
)
def test_a_recorded_request_is_overdue_only_after_its_ack_window(
    now: datetime, expected: bool
) -> None:
    assert is_overdue(Status.RECORDED, ack_due_at=DUE, now=now) is expected


@pytest.mark.parametrize(
    "status", [Status.DRAFT, Status.ACKNOWLEDGED, Status.IN_PROGRESS, Status.RESOLVED]
)
def test_only_a_recorded_request_can_be_overdue(status: Status) -> None:
    assert is_overdue(status, ack_due_at=DUE, now=DUE + timedelta(days=1)) is False


def test_a_request_without_an_ack_window_is_never_overdue() -> None:
    assert is_overdue(Status.RECORDED, ack_due_at=None, now=DUE + timedelta(days=1)) is False
