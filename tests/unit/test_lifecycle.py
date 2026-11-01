"""Request lifecycle guards (ticket #6): only Draft → Recorded is allowed so far."""

import itertools

import pytest

from app.domain.lifecycle import Status, TransitionNotAllowed, transition


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
