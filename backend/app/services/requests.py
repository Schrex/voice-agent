"""Request use cases. Each commits the Request change and its `request_events` row together.

Requests are never deleted.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CallRequest, Foreman, Job, Owner, Request
from app.domain.lifecycle import (
    Outcome,
    Status,
    acknowledge,
    mark_informed,
    resolve,
    start,
    transition,
)
from app.domain.ref import parse_ref
from app.domain.timeparse import NeededBy, parse_needed_by, speakable, urgency_for
from app.domain.urgency import infer_urgency
from app.services.ack_window import set_ack_due_at
from app.services.calls import Caller
from app.services.events import agent_event, iso, staff_event


@dataclass(frozen=True)
class NewItem:
    """One need the Foreman confirmed on the call, as the agent gathered it."""

    job_id: int | None
    """None when the spoken Job matched no active Job (Unmatched)."""
    job_spoken: str
    category: str
    need: str
    quantity: Decimal | None = None
    unit: str | None = None
    needed_by_spoken: str | None = None


@dataclass(frozen=True)
class ResolvedNeededBy:
    """A spoken needed-by as the agent reads it back, and the Urgency it gives."""

    needed_by_resolved: str | None
    """E.g. "Monday, November 2 at 7:00 AM"; None when unknown or not understood."""
    urgency: str | None


@dataclass(frozen=True)
class Recorded:
    ref: str
    needed_by: ResolvedNeededBy


def resolve_needed_by(spoken: str | None, now: datetime, need: str = "") -> ResolvedNeededBy:
    """What the backend makes of a spoken needed-by at `now` (America/New_York; ADR 0004), and
    the Urgency it gives with the need's work-stopped keywords (spec §5)."""
    return _readback(_parse(spoken, now), now, need, spoken)


def submit_requests(
    session: Session, *, caller: Caller, items: list[NewItem], now: datetime
) -> list[Recorded]:
    """Record the confirmed items as Requests of the caller's Foreman.

    The Foreman comes from the call (ADR 0004), never from the agent's input. The spoken
    needed-by is resolved to a time and sets the Urgency; without one, work-stopped keywords in
    the need make it Today (`domain.urgency.infer_urgency`). A missing needed-by is stored as
    unknown (null) and does not block the Request (spec J1 step 7). Everything is written in one
    transaction: each Request with a `recorded` event by the agent and a `created` link to
    the call.
    """
    status = transition(Status.DRAFT, Status.RECORDED)
    resolved = [_parse(item.needed_by_spoken, now) for item in items]
    requests = [
        Request(
            foreman_id=caller.foreman_id,
            job_id=item.job_id,
            job_spoken=item.job_spoken,
            category=item.category,
            need=item.need,
            quantity=item.quantity,
            unit=item.unit,
            needed_by_spoken=item.needed_by_spoken,
            needed_by=None if needed_by is None else needed_by.at,
            urgency=_urgency(needed_by, now, item.need, item.needed_by_spoken),
            status=status.value,
            source="ai_call",
            recorded_at=now,
        )
        for item, needed_by in zip(items, resolved, strict=True)
    ]
    for request in requests:
        set_ack_due_at(session, request)
    session.add_all(requests)
    session.flush()
    for request in requests:
        agent_event(session, request, now, "recorded", None, recorded_fields(request))
        session.add(CallRequest(call_id=caller.call_id, request_id=request.id, relation="created"))
    session.commit()
    return [
        Recorded(
            ref=request.ref_display,
            needed_by=_readback(needed_by, now, item.need, item.needed_by_spoken),
        )
        for request, item, needed_by in zip(requests, items, resolved, strict=True)
    ]


def _parse(spoken: str | None, now: datetime) -> NeededBy | None:
    return None if spoken is None else parse_needed_by(spoken, now)


def _urgency(
    needed_by: NeededBy | None, now: datetime, need: str, spoken: str | None
) -> str | None:
    """The Urgency stored and read back: from the needed-by, else from the Foreman's words."""
    from_needed_by = None if needed_by is None else urgency_for(needed_by, now)
    urgency = infer_urgency(from_needed_by, f"{need} {spoken or ''}")
    return None if urgency is None else urgency.value


def _readback(
    needed_by: NeededBy | None, now: datetime, need: str, spoken: str | None
) -> ResolvedNeededBy:
    return ResolvedNeededBy(
        needed_by_resolved=None if needed_by is None else speakable(needed_by),
        urgency=_urgency(needed_by, now, need, spoken),
    )


def recorded_fields(request: Request) -> dict[str, object]:
    return {
        "ref": request.ref_display,
        "foreman_id": request.foreman_id,
        "job_id": request.job_id,
        "job_spoken": request.job_spoken,
        "category": request.category,
        "need": request.need,
        "quantity": None if request.quantity is None else str(request.quantity),
        "unit": request.unit,
        "needed_by_spoken": request.needed_by_spoken,
        "needed_by": iso(request.needed_by),
        "urgency": request.urgency,
        "status": request.status,
        "source": request.source,
        "ack_due_at": iso(request.ack_due_at),
    }


class RequestNotFound(LookupError):
    pass


class UnknownOwner(ValueError):
    def __init__(self) -> None:
        super().__init__("No such Owner")


def acknowledge_request(
    session: Session, *, ref: str, owner_id: int | None, staff_id: uuid.UUID, now: datetime
) -> None:
    """A coordinator accepts the Request rendered `ref` and sets its Owner (spec J9, AC9.1).

    Recorded only, Owner required (`domain.lifecycle.acknowledge`); the Owner must exist.
    Sets status, owner and acknowledged time and writes an `acknowledged` event by the staff
    member in the same transaction. A refused acknowledge raises and writes nothing.
    """
    request = locked_request(session, ref)
    status = acknowledge(Status(request.status), owner_id)
    if owner_id is None or session.get(Owner, owner_id) is None:
        raise UnknownOwner()
    before = {
        "status": request.status,
        "owner_id": request.owner_id,
        "acknowledged_at": iso(request.acknowledged_at),
    }
    request.status = status.value
    request.owner_id = owner_id
    request.acknowledged_at = now
    after = {"status": status.value, "owner_id": owner_id, "acknowledged_at": iso(now)}
    staff_event(session, request, staff_id, now, "acknowledged", before, after)
    session.commit()


def start_request(session: Session, *, ref: str, staff_id: uuid.UUID, now: datetime) -> None:
    """A coordinator marks the Request rendered `ref` In Progress: its Owner is acting (spec J9).

    Acknowledged only (`domain.lifecycle.start`). Writes an `in_progress` event by the staff
    member in the same transaction; a refused move raises and writes nothing.
    """
    request = locked_request(session, ref)
    status = start(Status(request.status))
    before = {"status": request.status}
    request.status = status.value
    staff_event(session, request, staff_id, now, "in_progress", before, {"status": status.value})
    session.commit()


def resolve_request(
    session: Session,
    *,
    ref: str,
    outcome: Outcome | None,
    explanation: str | None,
    staff_id: uuid.UUID,
    now: datetime,
) -> None:
    """A coordinator resolves the Request rendered `ref` with an Outcome (spec J9, AC9.2).

    Any status but Resolved; Outcome and a non-blank explanation required
    (`domain.lifecycle.resolve`). Sets status, outcome, explanation (as typed) and resolved time
    and writes a `resolved` event by the staff member in the same transaction. A refused resolve
    raises and writes nothing. The Request is kept: Resolved leaves the queue, never the database.
    """
    request = locked_request(session, ref)
    status = resolve(Status(request.status), outcome, explanation)
    assert outcome is not None and explanation is not None  # guaranteed by the guard
    before = {
        "status": request.status,
        "outcome": request.outcome,
        "explanation": request.explanation,
        "resolved_at": iso(request.resolved_at),
    }
    request.status = status.value
    request.outcome = outcome.value
    request.explanation = explanation
    request.resolved_at = now
    after = {
        "status": status.value,
        "outcome": outcome.value,
        "explanation": explanation,
        "resolved_at": iso(now),
    }
    staff_event(session, request, staff_id, now, "resolved", before, after)
    session.commit()


def mark_foreman_informed(
    session: Session, *, ref: str, staff_id: uuid.UUID, now: datetime
) -> None:
    """A coordinator marks that the Foreman was told the Outcome (spec J9; ticket #32).

    Resolved and not yet marked only (`domain.lifecycle.mark_informed`). Sets the informed time
    and writes a `foreman_informed` event by the staff member in the same transaction; a refused
    mark raises and writes nothing. Once marked, the Request is never Uninformed.
    """
    request = locked_request(session, ref)
    mark_informed(Status(request.status), request.foreman_informed_at)
    request.foreman_informed_at = now
    staff_event(
        session,
        request,
        staff_id,
        now,
        "foreman_informed",
        {"foreman_informed_at": None},
        {"foreman_informed_at": iso(now)},
    )
    session.commit()


def locked_request(session: Session, ref: str) -> Request:
    """The Request rendered `ref`, locked for this transaction; RequestNotFound if unknown."""
    number = parse_ref(ref)
    request = (
        session.scalars(
            select(Request).where(Request.ref == number).with_for_update()
        ).one_or_none()
        if number is not None
        else None
    )
    if request is None:
        raise RequestNotFound(ref)
    return request


@dataclass(frozen=True)
class QuickEntry:
    """A Request a coordinator logs from a call they answered (spec J7)."""

    foreman_id: int
    job_id: int
    category: str
    need: str
    quantity: Decimal | None = None
    unit: str | None = None
    needed_by_spoken: str | None = None
    """As the coordinator typed it; resolved like a spoken one. None = needed-by unknown."""
    owner_id: int | None = None
    """Given → the Request is logged straight to Acknowledged with this Owner."""


class UnknownForeman(ValueError):
    def __init__(self) -> None:
        super().__init__("No such active Foreman")


class UnknownJob(ValueError):
    def __init__(self) -> None:
        super().__init__("No such active Job")


@dataclass(frozen=True)
class Logged:
    ref: str
    status: str


def log_request(
    session: Session, *, entry: QuickEntry, staff_id: uuid.UUID, now: datetime
) -> Logged:
    """Record a coordinator-logged Request (source `coordinator`) for a rostered Foreman.

    It enters the same queue as a called-in Request: Recorded, or directly Acknowledged when an
    Owner is given (spec J7; `domain.lifecycle` guards both moves). The needed-by is resolved
    and sets the Urgency exactly as on the agent's path. Writes a `recorded` event by the staff
    member and, with an Owner, an `acknowledged` event, in one transaction. An unknown or
    inactive Foreman or Job, or an unknown Owner, raises and writes nothing.
    """
    foreman = session.get(Foreman, entry.foreman_id)
    if foreman is None or not foreman.active:
        raise UnknownForeman()
    job = session.get(Job, entry.job_id)
    if job is None or not job.active:
        raise UnknownJob()
    if entry.owner_id is not None and session.get(Owner, entry.owner_id) is None:
        raise UnknownOwner()
    recorded = transition(Status.DRAFT, Status.RECORDED)
    needed_by = _parse(entry.needed_by_spoken, now)
    request = Request(
        foreman_id=foreman.id,
        job_id=job.id,
        job_spoken=job.name,
        category=entry.category,
        need=entry.need,
        quantity=entry.quantity,
        unit=entry.unit,
        needed_by_spoken=entry.needed_by_spoken,
        needed_by=None if needed_by is None else needed_by.at,
        urgency=_urgency(needed_by, now, entry.need, entry.needed_by_spoken),
        status=recorded.value,
        source="coordinator",
        recorded_at=now,
    )
    set_ack_due_at(session, request)
    session.add(request)
    session.flush()
    staff_event(session, request, staff_id, now, "recorded", None, recorded_fields(request))
    if entry.owner_id is not None:
        acknowledged = acknowledge(recorded, entry.owner_id)
        request.status = acknowledged.value
        request.owner_id = entry.owner_id
        request.acknowledged_at = now
        before = {"status": recorded.value, "owner_id": None, "acknowledged_at": None}
        after = {
            "status": acknowledged.value,
            "owner_id": entry.owner_id,
            "acknowledged_at": iso(now),
        }
        staff_event(session, request, staff_id, now, "acknowledged", before, after)
    session.commit()
    return Logged(ref=request.ref_display, status=request.status)
