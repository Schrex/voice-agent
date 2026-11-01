"""Request use cases. Each commits the Request change and its `request_events` row together.

Requests are never deleted.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import CallRequest, Request, RequestEvent
from app.domain.lifecycle import Status, transition
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
