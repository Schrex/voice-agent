"""What a coordinator may do to a Request now, from the lifecycle guards alone (ADR 0004: the
backend owns every rule; the dashboard only shows what this returns). Pure."""

from datetime import UTC, datetime

import pytest

from app.domain.lifecycle import Status, allowed_actions

INFORMED = datetime(2026, 11, 1, 20, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("status", "informed", "expected"),
    [
        (Status.DRAFT, None, ["resolve", "merge", "edit", "note"]),
        (Status.RECORDED, None, ["acknowledge", "resolve", "merge", "edit", "note"]),
        (Status.ACKNOWLEDGED, None, ["start", "reassign", "resolve", "merge", "edit", "note"]),
        (Status.IN_PROGRESS, None, ["reassign", "resolve", "merge", "edit", "note"]),
        (Status.RESOLVED, None, ["mark_informed", "note"]),
        (Status.RESOLVED, INFORMED, ["note"]),
    ],
)
def test_allowed_actions_follow_the_guards(
    status: Status, informed: datetime | None, expected: list[str]
) -> None:
    assert allowed_actions(status, foreman_informed_at=informed) == expected
