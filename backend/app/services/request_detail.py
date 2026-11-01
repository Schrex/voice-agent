"""One Request with its audit history (ticket #10). Read-only; writes stay in `requests.py`."""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CategoryOwnerDefault, Foreman, Job, Owner, Request, RequestEvent, Staff
from app.services.queue import as_said

_REF = re.compile(r"^R-(\d{1,18})$")


@dataclass(frozen=True)
class Actor:
    """Who made a change: the agent, a staff member (`id`, `name`) or the system."""

    type: str
    id: str | None
    name: str | None


@dataclass(frozen=True)
class Event:
    at: datetime
    actor: Actor
    kind: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None


@dataclass(frozen=True)
class OwnerRef:
    id: int
    name: str


@dataclass(frozen=True)
class RequestDetail:
    ref: str
    foreman: str
    job: str
    category: str
    need: str
    quantity: str | None
    unit: str | None
    needed_by: str | None
    urgency: str | None
    status: str
    source: str
    recorded_at: datetime
    owner: OwnerRef | None
    acknowledged_at: datetime | None
    # The category's default Owner, offered first when acknowledging (null if none is set).
    default_owner_id: int | None
    events: list[Event]


def request_detail(session: Session, ref: str) -> RequestDetail | None:
    """The Request rendered `ref` ("R-1000") and its events, oldest first; None if unknown."""
    match = _REF.match(ref)
    if match is None:
        return None
    row = session.execute(
        select(Request, Foreman, Job.name)
        .join(Foreman, Request.foreman_id == Foreman.id)
        .join(Job, Request.job_id == Job.id)
        .where(Request.ref == int(match.group(1)))
    ).one_or_none()
    if row is None:
        return None
    request, foreman, job_name = row
    return RequestDetail(
        ref=request.ref_display,
        foreman=f"{foreman.first_name} {foreman.last_name}",
        job=job_name,
        category=request.category,
        need=request.need,
        quantity=as_said(request.quantity),
        unit=request.unit,
        needed_by=request.needed_by_spoken,
        urgency=request.urgency,
        status=request.status,
        source=request.source,
        recorded_at=request.recorded_at,
        owner=_owner(session, request.owner_id),
        acknowledged_at=request.acknowledged_at,
        default_owner_id=session.scalar(
            select(CategoryOwnerDefault.owner_id).where(
                CategoryOwnerDefault.category == request.category
            )
        ),
        events=_events(session, request.id),
    )


def _owner(session: Session, owner_id: int | None) -> OwnerRef | None:
    owner = session.get(Owner, owner_id) if owner_id is not None else None
    return OwnerRef(id=owner.id, name=owner.name) if owner else None


def _events(session: Session, request_id: int) -> list[Event]:
    events = session.scalars(
        select(RequestEvent)
        .where(RequestEvent.request_id == request_id)
        .order_by(RequestEvent.at, RequestEvent.id)
    ).all()
    staff_ids = {i for e in events if e.actor_type == "staff" and (i := _uuid(e.actor_id))}
    names: dict[str, str] = {}
    if staff_ids:
        rows = session.execute(select(Staff.id, Staff.name).where(Staff.id.in_(staff_ids)))
        names = {str(staff_id): name for staff_id, name in rows.tuples()}
    return [
        Event(
            at=e.at,
            actor=Actor(
                type=e.actor_type,
                id=e.actor_id,
                name=names.get(str(_uuid(e.actor_id))) if e.actor_type == "staff" else None,
            ),
            kind=e.kind,
            before=e.before,
            after=e.after,
        )
        for e in events
    ]


def _uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None
