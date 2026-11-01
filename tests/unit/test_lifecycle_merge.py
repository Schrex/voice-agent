"""Merge duplicates guard (ticket #33; spec J2 "Coordinators can also merge duplicates", J9).

Request A is merged into Request B: A becomes Resolved (so A must still be resolvable) and B
must be a different Request that is not Resolved.
"""

import pytest

from app.domain.lifecycle import (
    ExplanationRequired,
    MergeIntoItself,
    Outcome,
    OutcomeRequired,
    Status,
    TransitionNotAllowed,
    merge,
)

D, R, A, P, X = (
    Status.DRAFT,
    Status.RECORDED,
    Status.ACKNOWLEDGED,
    Status.IN_PROGRESS,
    Status.RESOLVED,
)


@pytest.mark.parametrize("source", [D, R, A, P], ids=lambda s: s.value)
@pytest.mark.parametrize("target", [D, R, A, P], ids=lambda s: s.value)
def test_merge_resolves_the_source_into_any_unresolved_target(
    source: Status, target: Status
) -> None:
    assert merge(source, target, same=False, outcome=Outcome.WITHDRAWN, explanation="Dup") is X


@pytest.mark.parametrize("source", [D, R, A, P], ids=lambda s: s.value)
def test_cannot_merge_into_a_resolved_request(source: Status) -> None:
    with pytest.raises(TransitionNotAllowed):
        merge(source, X, same=False, outcome=Outcome.WITHDRAWN, explanation="Dup")


def test_cannot_merge_a_resolved_request() -> None:
    with pytest.raises(TransitionNotAllowed):
        merge(X, R, same=False, outcome=Outcome.WITHDRAWN, explanation="Dup")


@pytest.mark.parametrize("status", [R, A, P], ids=lambda s: s.value)
def test_cannot_merge_a_request_into_itself(status: Status) -> None:
    with pytest.raises(MergeIntoItself):
        merge(status, status, same=True, outcome=Outcome.WITHDRAWN, explanation="Dup")


def test_merge_needs_what_resolve_needs() -> None:
    with pytest.raises(OutcomeRequired):
        merge(R, A, same=False, outcome=None, explanation="Dup")
    with pytest.raises(ExplanationRequired):
        merge(R, A, same=False, outcome=Outcome.WITHDRAWN, explanation="  ")
