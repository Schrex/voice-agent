"""Uninformed Requests (ticket #32; spec §5 flags, AC9.4): Resolved, not marked Foreman Informed,
and Resolved more than the threshold ago (`app.domain.sla`). Read-only; dashboard only.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Foreman, Job, Request
from app.domain.lifecycle import Status
from app.domain.sla import uninformed_cutoff


@dataclass(frozen=True)
class UninformedRow:
    ref: str
    foreman: str
    job: str | None
    """The Job's name; None when Unmatched."""
    job_spoken: str
    need: str
    outcome: str
    resolved_at: datetime


def uninformed_requests(session: Session, now: datetime) -> list[UninformedRow]:
    """Uninformed at `now`, longest-waiting (oldest Resolved) first; ref breaks ties."""
    rows = session.execute(
        select(Request, Foreman, Job.name)
        .join(Foreman, Request.foreman_id == Foreman.id)
        .outerjoin(Job, Request.job_id == Job.id)
        .where(
            Request.status == Status.RESOLVED.value,
            Request.foreman_informed_at.is_(None),
            Request.resolved_at < uninformed_cutoff(now),
        )
        .order_by(Request.resolved_at, Request.ref)
    ).all()
    return [
        UninformedRow(
            ref=request.ref_display,
            foreman=f"{foreman.first_name} {foreman.last_name}",
            job=job_name,
            job_spoken=request.job_spoken,
            need=request.need,
            outcome=_set(request.outcome),
            resolved_at=_set(request.resolved_at),
        )
        for request, foreman, job_name in rows
    ]


def _set[T](value: T | None) -> T:
    """A Resolved Request always has an Outcome and a resolved time (CHECK resolved_has_outcome)."""
    if value is None:
        raise ValueError("Resolved Request without its Outcome or resolved time")
    return value
