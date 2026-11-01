"""Duplicate rule (ticket #18, spec J2). Pure: no I/O.

A new need duplicates an existing Request of the same Foreman on the same Job in the same
Category that is still open: Recorded, Acknowledged or In Progress. A Resolved Request is not
open, and a Draft was never confirmed by the Foreman (GLOSSARY). An Unmatched need or Request
has no Job, so it is never the same Job as anything.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from app.domain.lifecycle import OPEN_STATUSES, Status


@dataclass(frozen=True)
class NewNeed:
    foreman_id: int
    job_id: int | None
    category: str


@dataclass(frozen=True)
class ExistingRequest:
    ref: str
    foreman_id: int
    job_id: int | None
    category: str
    status: Status


def is_duplicate(new: NewNeed, other: ExistingRequest) -> bool:
    return (
        new.job_id is not None
        and other.foreman_id == new.foreman_id
        and other.job_id == new.job_id
        and other.category == new.category
        and other.status in OPEN_STATUSES
    )


def duplicates_of(new: NewNeed, others: Iterable[ExistingRequest]) -> list[ExistingRequest]:
    """The `others` that `new` duplicates, in the given order."""
    return [other for other in others if is_duplicate(new, other)]
