"""Request use cases. Each commits the Request change and its `request_events` row together.

Requests are never deleted.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import CallRequest, Request, RequestEvent
from app.domain.lifecycle import Status, transition
from app.domain.timeparse import NeededBy, parse_needed_by, speakable, urgency_for
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


def resolve_needed_by(spoken: str | None, now: datetime) -> ResolvedNeededBy:
    """What the backend makes of a spoken needed-by at `now` (America/New_York; ADR 0004)."""
    return _readback(_parse(spoken, now), now)


def submit_requests(
    session: Session, *, caller: Caller, items: list[NewItem], now: datetime
) -> list[Recorded]:
    """Record the confirmed items as Requests of the caller's Foreman.

    The Foreman comes from the call (ADR 0004), never from the agent's input. The spoken
    needed-by is resolved to a time and sets the Urgency; a missing one is stored as unknown
    (null) and does not block the Request (spec J1 step 7). Everything is written in one
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
            urgency=None if needed_by is None else urgency_for(needed_by, now).value,
            status=status.value,
            source="ai_call",
            recorded_at=now,
        )
        for item, needed_by in zip(items, resolved, strict=True)
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
    return [
        Recorded(ref=request.ref_display, needed_by=_readback(needed_by, now))
        for request, needed_by in zip(requests, resolved, strict=True)
    ]


def _parse(spoken: str | None, now: datetime) -> NeededBy | None:
    return None if spoken is None else parse_needed_by(spoken, now)


def _readback(needed_by: NeededBy | None, now: datetime) -> ResolvedNeededBy:
    if needed_by is None:
        return ResolvedNeededBy(needed_by_resolved=None, urgency=None)
    return ResolvedNeededBy(
        needed_by_resolved=speakable(needed_by), urgency=urgency_for(needed_by, now).value
    )


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
        "needed_by": _utc_iso(request.needed_by),
        "urgency": request.urgency,
        "status": request.status,
        "source": request.source,
    }


def _utc_iso(at: datetime | None) -> str | None:
    return None if at is None else at.astimezone(UTC).isoformat().replace("+00:00", "Z")
