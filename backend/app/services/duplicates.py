"""Duplicate check during intake (ticket #18, spec J2, AC2.1/AC2.2).

The agent asks, before the read-back, whether a new need duplicates one of the caller's open
Requests. The rule is `domain.dedupe` (same Foreman + Job + Category, not Resolved); the
Foreman comes from the call, never from the agent (ADR 0004). Nothing is written here: a yes
goes through `add_note`, a no through `submit_requests`.

Call start also gives the agent the caller's open Requests (`open_requests_for_call_start`),
so it knows from the first turn what it may be asked about.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.db.models import Job, Request
from app.domain.dedupe import ExistingRequest, NewNeed, duplicates_of
from app.domain.lifecycle import OPEN_STATUSES, Status
from app.domain.timeparse import speakable_at

_OPEN = tuple(s.value for s in OPEN_STATUSES)


@dataclass(frozen=True)
class Duplicate:
    ref: str
    job: str
    category: str
    need: str
    quantity: Decimal | None
    unit: str | None
    needed_by: str | None
    """As the read-back said it ("Monday, November 2 at 7:00 AM"); None when not resolved."""
    recorded_at: str
    """When the Foreman made it, as the agent says it ("Saturday, October 31 at 6:45 AM")."""


def find_duplicates(
    session: Session, *, foreman_id: int, job_id: int, category: str
) -> list[Duplicate]:
    """The calling Foreman's open Requests that a new need on this Job and Category duplicates.

    Newest first. A merged Request is Resolved (#33), so only the Request it was merged into
    can come back.
    """
    rows = session.scalars(_open_requests_of(foreman_id)).all()
    new = NewNeed(foreman_id=foreman_id, job_id=job_id, category=category)
    by_ref = {r.ref_display: r for r in rows}
    duplicates = duplicates_of(new, (_existing(r) for r in rows))
    return [_duplicate(session, by_ref[d.ref]) for d in duplicates]


def open_requests_for_call_start(session: Session, foreman_id: int) -> str:
    """The Foreman's open Requests, newest first, one per line, for the call-start variable.

    E.g. "R-1042: Trucking at Route 104 Widening, 3 trucks tri-axle dump trucks, recorded
    Saturday, October 31 at 6:45 AM". Empty when there are none.
    """
    rows = session.scalars(_open_requests_of(foreman_id)).all()
    return "\n".join(_line(_duplicate(session, r)) for r in rows)


def _open_requests_of(foreman_id: int) -> Select[Request]:
    return (
        select(Request)
        .where(Request.foreman_id == foreman_id, Request.status.in_(_OPEN))
        .order_by(Request.recorded_at.desc(), Request.ref.desc())
    )


def _existing(request: Request) -> ExistingRequest:
    return ExistingRequest(
        ref=request.ref_display,
        foreman_id=request.foreman_id,
        job_id=request.job_id,
        category=request.category,
        status=Status(request.status),
    )


def _duplicate(session: Session, request: Request) -> Duplicate:
    job = session.get(Job, request.job_id) if request.job_id is not None else None
    assert request.recorded_at is not None  # every open Request was Recorded
    return Duplicate(
        ref=request.ref_display,
        job=job.name if job is not None else request.job_spoken,
        category=request.category,
        need=request.need,
        quantity=request.quantity,
        unit=request.unit,
        needed_by=_speakable_at(request.needed_by),
        recorded_at=_speakable_at(request.recorded_at) or "",
    )


def _line(d: Duplicate) -> str:
    amount = " ".join(
        part for part in (_quantity(d.quantity), d.unit) if part is not None and part != ""
    )
    need = f"{amount} {d.need}" if amount else d.need
    line = f"{d.ref}: {d.category} at {d.job}, {need}"
    if d.needed_by is not None:
        line += f", needed by {d.needed_by}"
    return f"{line}, recorded {d.recorded_at}"


def _quantity(quantity: Decimal | None) -> str | None:
    if quantity is None:
        return None
    return str(int(quantity)) if quantity == quantity.to_integral_value() else str(quantity)


def _speakable_at(at: datetime | None) -> str | None:
    return None if at is None else speakable_at(at)
