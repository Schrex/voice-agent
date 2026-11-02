"""Reassign owner (spec J9 "Reassign owner"): a coordinator changes the Owner of a Request that
already has one and is not finished. Not a status move. Pure."""

import pytest

from app.domain.lifecycle import NotReassignable, OwnerRequired, Status, reassign


@pytest.mark.parametrize("status", [Status.ACKNOWLEDGED, Status.IN_PROGRESS])
def test_an_owned_open_request_can_be_reassigned_and_keeps_its_status(status: Status) -> None:
    assert reassign(status, 7) is status


@pytest.mark.parametrize("status", [Status.DRAFT, Status.RECORDED, Status.RESOLVED])
def test_a_request_without_an_owner_or_finished_cannot_be_reassigned(status: Status) -> None:
    with pytest.raises(NotReassignable):
        reassign(status, 7)


def test_reassigning_needs_an_owner() -> None:
    with pytest.raises(OwnerRequired):
        reassign(Status.ACKNOWLEDGED, None)
