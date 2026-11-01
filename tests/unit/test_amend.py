"""Amending a Request by phone (ticket #19, spec J4): the change applies only before In Progress;
from In Progress on it is a Change requested flag instead.
"""

import pytest

from app.domain.lifecycle import Status, may_amend


@pytest.mark.parametrize("status", [Status.RECORDED, Status.ACKNOWLEDGED])
def test_amend_is_allowed_before_in_progress(status: Status) -> None:
    assert may_amend(status) is True


@pytest.mark.parametrize("status", [Status.DRAFT, Status.IN_PROGRESS, Status.RESOLVED])
def test_amend_is_not_allowed_in_any_other_status(status: Status) -> None:
    assert may_amend(status) is False
