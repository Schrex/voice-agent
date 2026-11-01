"""Request use cases. Each commits the Request change and its `request_events` row together.

Requests are never deleted.
"""

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CallRequest, Owner, Request, RequestEvent
from app.domain.lifecycle import Outcome, Status, acknowledge, resolve, start, transition
from app.services.calls import Caller


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


def submit_requests(
    session: Session, *, caller: Caller, items: list[NewItem], now: datetime
) -> list[str]:
    """Record the confirmed items as Requests of the caller's Foreman; return their refs.

    The Foreman comes from the call (ADR 0004), never from the agent's input. Everything is
    written in one transaction: each Request with a `recorded` event by the agent and a
    `created` link to the call.
    """
    status = transition(Status.DRAFT, Status.RECORDED)
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
            status=status.value,
            source="ai_call",
            recorded_at=now,
        )
        for item in items
    ]
    session.add_all(requests)
    session.flush()
    for request in requests:
        session.add(
            RequestEvent(
                request_id=request.id,
                at=now,
                actor_type="agent",
                actor_id=None,
                kind="recorded",
                before=None,
                after=_recorded_fields(request),
            )
        )
        session.add(CallRequest(call_id=caller.call_id, request_id=request.id, relation="created"))
    session.commit()
    return [request.ref_display for request in requests]


def _recorded_fields(request: Request) -> dict[str, object]:
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
        "status": request.status,
        "source": request.source,
    }


class RequestNotFound(LookupError):
    pass


class UnknownOwner(ValueError):
    def __init__(self) -> None:
        super().__init__("No such Owner")


_REF = re.compile(r"^R-(\d{1,18})$")


def acknowledge_request(
    session: Session, *, ref: str, owner_id: int | None, staff_id: uuid.UUID, now: datetime
) -> None:
    """A coordinator accepts the Request rendered `ref` and sets its Owner (spec J9, AC9.1).

    Recorded only, Owner required (`domain.lifecycle.acknowledge`); the Owner must exist.
    Sets status, owner and acknowledged time and writes an `acknowledged` event by the staff
    member in the same transaction. A refused acknowledge raises and writes nothing.
    """
    request = _locked(session, ref)
    status = acknowledge(Status(request.status), owner_id)
    if owner_id is None or session.get(Owner, owner_id) is None:
        raise UnknownOwner()
    before = {
        "status": request.status,
        "owner_id": request.owner_id,
        "acknowledged_at": _iso(request.acknowledged_at),
    }
    request.status = status.value
    request.owner_id = owner_id
    request.acknowledged_at = now
    session.add(
        RequestEvent(
            request_id=request.id,
            at=now,
            actor_type="staff",
            actor_id=str(staff_id),
            kind="acknowledged",
            before=before,
            after={"status": status.value, "owner_id": owner_id, "acknowledged_at": _iso(now)},
        )
    )
    session.commit()


def start_request(session: Session, *, ref: str, staff_id: uuid.UUID, now: datetime) -> None:
    """A coordinator marks the Request rendered `ref` In Progress: its Owner is acting (spec J9).

    Acknowledged only (`domain.lifecycle.start`). Writes an `in_progress` event by the staff
    member in the same transaction; a refused move raises and writes nothing.
    """
    request = _locked(session, ref)
    status = start(Status(request.status))
    before = {"status": request.status}
    request.status = status.value
    _staff_event(session, request, staff_id, now, "in_progress", before, {"status": status.value})
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
    request = _locked(session, ref)
    status = resolve(Status(request.status), outcome, explanation)
    assert outcome is not None and explanation is not None  # guaranteed by the guard
    before = {
        "status": request.status,
        "outcome": request.outcome,
        "explanation": request.explanation,
        "resolved_at": _iso(request.resolved_at),
    }
    request.status = status.value
    request.outcome = outcome.value
    request.explanation = explanation
    request.resolved_at = now
    after = {
        "status": status.value,
        "outcome": outcome.value,
        "explanation": explanation,
        "resolved_at": _iso(now),
    }
    _staff_event(session, request, staff_id, now, "resolved", before, after)
    session.commit()


def _locked(session: Session, ref: str) -> Request:
    """The Request rendered `ref`, locked for this transaction; RequestNotFound if unknown."""
    match = _REF.match(ref)
    request = (
        session.scalars(
            select(Request).where(Request.ref == int(match.group(1))).with_for_update()
        ).one_or_none()
        if match
        else None
    )
    if request is None:
        raise RequestNotFound(ref)
    return request


def _staff_event(
    session: Session,
    request: Request,
    staff_id: uuid.UUID,
    now: datetime,
    kind: str,
    before: Mapping[str, object],
    after: Mapping[str, object],
) -> None:
    session.add(
        RequestEvent(
            request_id=request.id,
            at=now,
            actor_type="staff",
            actor_id=str(staff_id),
            kind=kind,
            before=dict(before),
            after=dict(after),
        )
    )


def _iso(at: datetime | None) -> str | None:
    return None if at is None else at.astimezone(UTC).isoformat().replace("+00:00", "Z")
