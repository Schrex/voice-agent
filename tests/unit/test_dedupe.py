"""Duplicate rule (ticket #18, spec J2, AC2.1).

A new need duplicates an existing Request when it is the same Foreman, the same Job and the
same Category, and the existing Request is not Resolved. A Draft was never confirmed by the
Foreman (GLOSSARY), so it is not an open Request to ask about.
"""

import pytest

from app.domain.dedupe import ExistingRequest, NewNeed, duplicates_of, is_duplicate
from app.domain.lifecycle import Status

DALE, RITA = 1, 2
ROUTE_104, PENFIELD = 14, 12

NEW = NewNeed(foreman_id=DALE, job_id=ROUTE_104, category="Trucking")


def existing(
    *,
    foreman_id: int = DALE,
    job_id: int | None = ROUTE_104,
    category: str = "Trucking",
    status: Status = Status.RECORDED,
    ref: str = "R-1042",
) -> ExistingRequest:
    return ExistingRequest(
        ref=ref, foreman_id=foreman_id, job_id=job_id, category=category, status=status
    )


@pytest.mark.parametrize(
    ("other", "duplicate"),
    [
        pytest.param(existing(), True, id="same foreman, job, category; Recorded"),
        pytest.param(existing(status=Status.ACKNOWLEDGED), True, id="Acknowledged"),
        pytest.param(existing(status=Status.IN_PROGRESS), True, id="In Progress"),
        pytest.param(existing(status=Status.RESOLVED), False, id="Resolved"),
        pytest.param(existing(status=Status.DRAFT), False, id="Draft"),
        pytest.param(existing(foreman_id=RITA), False, id="another Foreman"),
        pytest.param(existing(job_id=PENFIELD), False, id="another Job"),
        pytest.param(existing(job_id=None), False, id="existing Request Unmatched"),
        pytest.param(existing(category="Material"), False, id="another Category"),
        pytest.param(existing(category="Equipment Repair"), False, id="Equipment vs Repair"),
    ],
)
def test_duplicate_is_same_foreman_job_and_category_and_not_resolved(
    other: ExistingRequest, duplicate: bool
) -> None:
    assert is_duplicate(NEW, other) is duplicate


def test_an_unmatched_new_need_duplicates_nothing() -> None:
    # No Job to compare: an Unmatched need is never the same Job as anything.
    unmatched = NewNeed(foreman_id=DALE, job_id=None, category="Trucking")

    assert is_duplicate(unmatched, existing()) is False
    assert is_duplicate(unmatched, existing(job_id=None)) is False


def test_duplicates_of_keeps_only_the_duplicates_in_the_given_order() -> None:
    others = [
        existing(ref="R-1050"),
        existing(ref="R-1049", category="Material"),
        existing(ref="R-1048", status=Status.RESOLVED),
        existing(ref="R-1047", status=Status.ACKNOWLEDGED),
        existing(ref="R-1046", foreman_id=RITA),
    ]

    assert [r.ref for r in duplicates_of(NEW, others)] == ["R-1050", "R-1047"]
