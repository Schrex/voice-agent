"""Edit fields / fix the Job (ticket #31): which Requests a coordinator may edit, and what an edit
records as changed. Pure domain.
"""

import pytest

from app.domain.lifecycle import NotEditable, Status, edit
from app.domain.request_edit import changed_fields


@pytest.mark.parametrize(
    "status", [Status.DRAFT, Status.RECORDED, Status.ACKNOWLEDGED, Status.IN_PROGRESS]
)
def test_a_request_that_is_not_resolved_is_editable(status: Status) -> None:
    assert edit(status) is status


def test_a_resolved_request_is_not_editable() -> None:
    with pytest.raises(NotEditable):
        edit(Status.RESOLVED)


def test_only_fields_whose_value_changes_are_recorded_before_and_after() -> None:
    current = {"job_id": None, "need": "tri-axle dumps", "quantity": None, "unit": None}
    proposed = {"job_id": 4, "need": "tri-axle dumps", "unit": None}

    assert changed_fields(current, proposed) == ({"job_id": None}, {"job_id": 4})


def test_nothing_changed_gives_empty_before_and_after() -> None:
    assert changed_fields({"need": "a", "unit": "tons"}, {"need": "a"}) == ({}, {})


def test_a_proposed_field_that_is_not_editable_is_refused() -> None:
    with pytest.raises(KeyError):
        changed_fields({"need": "a"}, {"status": "Resolved"})
