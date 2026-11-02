"""Request lifecycle guards (architecture §5): Draft → Recorded (#6); Recorded → Acknowledged with
an Owner (#11); Acknowledged → In Progress and any non-Resolved → Resolved with an Outcome and an
explanation (#12).
"""

import itertools

import pytest

from app.domain.lifecycle import (
    ExplanationRequired,
    Outcome,
    OutcomeRequired,
    OwnerRequired,
    Status,
    TransitionNotAllowed,
    acknowledge,
    resolve,
    start,
    transition,
)

D, R, A, P, X = (
    Status.DRAFT,
    Status.RECORDED,
    Status.ACKNOWLEDGED,
    Status.IN_PROGRESS,
    Status.RESOLVED,
)

# Architecture §5 "Lifecycle guards", written out by hand: Draft→Recorded; Recorded→Acknowledged
# (owner required); Acknowledged→In Progress; any non-Resolved→Resolved (outcome + explanation
# required). Every pair not listed is refused.
ALLOWED = {(D, R), (R, A), (A, P), (D, X), (R, X), (A, X), (P, X)}


def _move(current: Status, target: Status) -> Status:
    """Attempt `current → target` through the guard for `target`, with its requirements met."""
    if target is Status.ACKNOWLEDGED:
        return acknowledge(current, owner_id=7)
    if target is Status.IN_PROGRESS:
        return start(current)
    if target is Status.RESOLVED:
        return resolve(current, Outcome.FULFILLED, "Two trucks sent at 7")
    return transition(current, target)


def test_lifecycle_words_are_the_glossary_words() -> None:
    assert [s.value for s in Status] == [
        "Draft",
        "Recorded",
        "Acknowledged",
        "In Progress",
        "Resolved",
    ]


def test_outcome_words_are_the_glossary_words() -> None:
    assert [o.value for o in Outcome] == ["Fulfilled", "Partially Fulfilled", "Denied", "Withdrawn"]


@pytest.mark.parametrize(("current", "target"), sorted(ALLOWED), ids=lambda s: s.value)
def test_allowed_transition(current: Status, target: Status) -> None:
    assert _move(current, target) is target


@pytest.mark.parametrize(
    ("current", "target"),
    [pair for pair in itertools.product(Status, Status) if pair not in ALLOWED],
    ids=lambda s: s.value,
)
def test_every_other_transition_raises(current: Status, target: Status) -> None:
    with pytest.raises(TransitionNotAllowed):
        _move(current, target)


def test_guarded_moves_are_not_reachable_through_the_generic_transition() -> None:
    for target in (A, P, X):
        for current in Status:
            with pytest.raises(TransitionNotAllowed):
                transition(current, target)


def test_acknowledge_without_an_owner_raises() -> None:
    with pytest.raises(OwnerRequired):
        acknowledge(Status.RECORDED, owner_id=None)


@pytest.mark.parametrize("current", [D, R, A, P], ids=lambda s: s.value)
def test_resolve_without_an_outcome_raises(current: Status) -> None:
    with pytest.raises(OutcomeRequired):
        resolve(current, None, "Two trucks sent at 7")


@pytest.mark.parametrize("explanation", [None, "", "   \n"], ids=["none", "empty", "blank"])
def test_resolve_without_an_explanation_raises(explanation: str | None) -> None:
    with pytest.raises(ExplanationRequired):
        resolve(Status.IN_PROGRESS, Outcome.DENIED, explanation)


@pytest.mark.parametrize("outcome", list(Outcome), ids=lambda o: o.value)
def test_resolve_accepts_every_outcome(outcome: Outcome) -> None:
    assert resolve(Status.ACKNOWLEDGED, outcome, "Called back") is Status.RESOLVED


def test_a_resolved_request_cannot_be_resolved_again() -> None:
    with pytest.raises(TransitionNotAllowed):
        resolve(Status.RESOLVED, Outcome.DENIED, "Changed my mind")
