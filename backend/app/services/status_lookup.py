"""Status lookup for the agent's `find_open_requests` tool (spec J3, architecture §4.2).

Returns the calling Foreman's own Requests with exactly the facts on record; the agent speaks
nothing else (ACX.1). The Foreman comes from the call, never from the agent (ADR 0004).
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import CallRequest, Job, Owner, Request
from app.domain.lifecycle import Status
from app.domain.local_time import LOCAL_TZ
from app.domain.timeparse import NeededBy, speakable
from app.services.calls import Caller


@dataclass(frozen=True)
class FoundRequest:
    ref: str
    job: str
    """The Job's name, or for an Unmatched Request the Job as the Foreman said it."""
    category: str
    need: str
    quantity: Decimal | None
    unit: str | None
    needed_by: str | None
    """As the read-back said it ("Monday, November 2 at 7:00 AM"); None when not resolved."""
    status: str
    owner: str | None
    outcome: str | None
    explanation: str | None


# A Draft was never confirmed by the Foreman (GLOSSARY), so it is not his Request to look up.
LOOKUP_STATUSES = tuple(
    s.value for s in (Status.RECORDED, Status.ACKNOWLEDGED, Status.IN_PROGRESS, Status.RESOLVED)
)


def find_open_requests(
    session: Session, *, caller: Caller, job_id: int | None, category: str | None
) -> list[FoundRequest]:
    """The caller's Requests, newest first, narrowed by Job and Category when given.

    Links the call to each Request returned (`call_requests` relation `looked_up`, once per
    Request), so the call record shows what was looked up. The Requests are not changed.
    """
    query = (
        select(Request, Job.name, Owner.name)
        .outerjoin(Job, Request.job_id == Job.id)
        .outerjoin(Owner, Request.owner_id == Owner.id)
        .where(Request.foreman_id == caller.foreman_id, Request.status.in_(LOOKUP_STATUSES))
        .order_by(Request.recorded_at.desc(), Request.ref.desc())
    )
    if job_id is not None:
        query = query.where(Request.job_id == job_id)
    if category is not None:
        query = query.where(Request.category == category)
    rows = session.execute(query).all()
    found = [
        FoundRequest(
            ref=request.ref_display,
            job=job_name if job_name is not None else request.job_spoken,
            category=request.category,
            need=request.need,
            quantity=request.quantity,
            unit=request.unit,
            needed_by=_speakable(request.needed_by),
            status=request.status,
            owner=owner_name,
            outcome=request.outcome,
            explanation=request.explanation,
        )
        for request, job_name, owner_name in rows
    ]
    if rows:
        links = [
            {"call_id": caller.call_id, "request_id": request.id, "relation": "looked_up"}
            for request, _, _ in rows
        ]
        session.execute(insert(CallRequest).values(links).on_conflict_do_nothing())
        session.commit()
    return found


def _speakable(needed_by: datetime | None) -> str | None:
    if needed_by is None:
        return None
    local = needed_by.astimezone(LOCAL_TZ)
    return speakable(NeededBy(local.date(), local.time().replace(tzinfo=None)))
