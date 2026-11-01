"""Mark Foreman Informed guard (ticket #32; GLOSSARY: "a mark that a person has told the foreman
the outcome of a resolved request").
"""

from datetime import UTC, datetime

import pytest

from app.domain.lifecycle import AlreadyInformed, NotResolved, Status, mark_informed

AT = datetime(2026, 11, 1, 15, 0, tzinfo=UTC)


def test_a_resolved_request_not_yet_informed_can_be_marked() -> None:
    mark_informed(Status.RESOLVED, foreman_informed_at=None)


@pytest.mark.parametrize(
    "status", [Status.DRAFT, Status.RECORDED, Status.ACKNOWLEDGED, Status.IN_PROGRESS]
)
def test_only_a_resolved_request_can_be_marked(status: Status) -> None:
    with pytest.raises(NotResolved):
        mark_informed(status, foreman_informed_at=None)


def test_a_request_already_marked_cannot_be_marked_again() -> None:
    with pytest.raises(AlreadyInformed):
        mark_informed(Status.RESOLVED, foreman_informed_at=AT)
