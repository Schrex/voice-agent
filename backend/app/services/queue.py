"""The coordinator's queue (spec J9): open Requests, most urgent first, then oldest first.

Read-only; writes stay in `services/requests.py`.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.db.models import Job, Request
from app.domain.lifecycle import OPEN_STATUSES, Status
from app.domain.sla import is_overdue
from app.domain.urgency import Urgency, rank


@dataclass(frozen=True)
class QueueRow:
    ref: str
    job: str | None
    """The Job's name; None when Unmatched."""
    job_spoken: str
    need: str
    quantity: str | None
    unit: str | None
    needed_by: datetime | None
    """The resolved needed-by; None when unknown, not understood, or only a day was said."""
    needed_by_spoken: str | None
    urgency: str | None
    status: str
    recorded_at: datetime
    overdue: bool
    """Still Recorded after its ack window (ticket #22, `domain.sla.is_overdue`)."""


def open_requests(session: Session, now: datetime) -> list[QueueRow]:
    """Recorded, Acknowledged and In Progress Requests (no Draft, no Resolved), flagged Overdue
    as of `now`.

    Sorted by urgency (Emergency, Today, Planned; no urgency yet last), then by age, oldest
    first; ref breaks ties.
    """
    urgency_rank = case(
        {u.value: rank(u) for u in Urgency}, value=Request.urgency, else_=len(Urgency)
    )
    rows = session.execute(
        select(Request, Job.name)
        .outerjoin(Job, Request.job_id == Job.id)
        .where(Request.status.in_([s.value for s in OPEN_STATUSES]))
        .order_by(urgency_rank, Request.recorded_at, Request.ref)
    ).all()
    return [
        QueueRow(
            ref=request.ref_display,
            job=job_name,
            job_spoken=request.job_spoken,
            need=request.need,
            quantity=as_said(request.quantity),
            unit=request.unit,
            needed_by=request.needed_by,
            needed_by_spoken=request.needed_by_spoken,
            urgency=request.urgency,
            status=request.status,
            recorded_at=_recorded_at(request),
            overdue=is_overdue(Status(request.status), ack_due_at=request.ack_due_at, now=now),
        )
        for request, job_name in rows
    ]


def _recorded_at(request: Request) -> datetime:
    """Every open status comes after Recorded, so `recorded_at` is always set here."""
    if request.recorded_at is None:
        raise ValueError(f"{request.ref_display} is open but was never Recorded")
    return request.recorded_at


def as_said(quantity: Decimal | None) -> str | None:
    """3.000 → "3", 2.50 → "2.5"."""
    if quantity is None:
        return None
    return format(quantity.normalize(), "f")
