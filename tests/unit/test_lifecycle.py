"""Request lifecycle guards: Draft → Recorded (#6); Recorded → Acknowledged with an Owner (#11)."""

import itertools

import pytest

from app.domain.lifecycle import (
    OwnerRequired,
    Status,
    TransitionNotAllowed,
    acknowledge,
    transition,
)


def test_lifecycle_words_are_the_glossary_words() -> None:
    assert [s.value for s in Status] == [
        "Draft",
        "Recorded",
        "Acknowledged",
        "In Progress",
        "Resolved",
    ]


def test_draft_to_recorded_is_allowed() -> None:
    assert transition(Status.DRAFT, Status.RECORDED) is Status.RECORDED


@pytest.mark.parametrize(
    ("current", "target"),
    [pair for pair in itertools.product(Status, Status) if pair != (Status.DRAFT, Status.RECORDED)],
    ids=lambda s: s.value,
)
def test_every_other_transition_raises(current: Status, target: Status) -> None:
    with pytest.raises(TransitionNotAllowed):
        transition(current, target)


def test_recorded_to_acknowledged_with_an_owner_is_allowed() -> None:
    assert acknowledge(Status.RECORDED, owner_id=7) is Status.ACKNOWLEDGED


def test_acknowledge_without_an_owner_raises() -> None:
    with pytest.raises(OwnerRequired):
        acknowledge(Status.RECORDED, owner_id=None)


@pytest.mark.parametrize(
    "current", [s for s in Status if s is not Status.RECORDED], ids=lambda s: s.value
)
def test_acknowledge_from_any_other_status_raises(current: Status) -> None:
    with pytest.raises(TransitionNotAllowed):
        acknowledge(current, owner_id=7)


def test_acknowledged_is_not_reachable_without_the_owner_guard() -> None:
    with pytest.raises(TransitionNotAllowed):
        transition(Status.RECORDED, Status.ACKNOWLEDGED)
