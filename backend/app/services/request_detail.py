"""One Request with its audit history (ticket #10). Read-only; writes stay in `requests.py`."""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Call,
    CallRequest,
    CategoryOwnerDefault,
    Foreman,
    Job,
    Owner,
    Request,
    RequestEvent,
    Staff,
)
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
class LinkedCall:
    """A Call that created, looked up or amended the Request (`call_requests.relation`)."""

    id: int
    started_at: datetime
    relation: str


@dataclass(frozen=True)
class OwnerRef:
    id: int
    name: str


@dataclass(frozen=True)
class RequestDetail:
    ref: str
    foreman: str
    job: str | None
    """The Job's name; None when Unmatched."""
    job_id: int | None
    job_spoken: str
    category: str
    need: str
    quantity: str | None
    unit: str | None
    needed_by: datetime | None
    """The resolved needed-by; None when unknown, not understood, or only a day was said."""
    needed_by_spoken: str | None
    urgency: str | None
    status: str
    source: str
    recorded_at: datetime | None  # null while the Request is a Draft
    owner: OwnerRef | None
    acknowledged_at: datetime | None
    outcome: str | None  # set with explanation and resolved_at when Resolved
    explanation: str | None
    resolved_at: datetime | None
    merged_into: str | None  # ref of the Request this one was merged into (ticket #33)
    foreman_informed_at: datetime | None  # null until a coordinator marks Foreman Informed
    # The category's default Owner, offered first when acknowledging (null if none is set).
    default_owner_id: int | None
    events: list[Event]
    calls: list[LinkedCall]  # oldest first


def request_detail(session: Session, ref: str) -> RequestDetail | None:
    """The Request rendered `ref` ("R-1000") and its events, oldest first; None if unknown."""
    match = _REF.match(ref)
    if match is None:
        return None
    row = session.execute(
        select(Request, Foreman, Job.name)
        .join(Foreman, Request.foreman_id == Foreman.id)
        .outerjoin(Job, Request.job_id == Job.id)
        .where(Request.ref == int(match.group(1)))
    ).one_or_none()
    if row is None:
        return None
    request, foreman, job_name = row
    return RequestDetail(
        ref=request.ref_display,
        foreman=f"{foreman.first_name} {foreman.last_name}",
        job=job_name,
        job_id=request.job_id,
        job_spoken=request.job_spoken,
        category=request.category,
        need=request.need,
        quantity=as_said(request.quantity),
        unit=request.unit,
        needed_by=request.needed_by,
        needed_by_spoken=request.needed_by_spoken,
        urgency=request.urgency,
        status=request.status,
        source=request.source,
        recorded_at=request.recorded_at,
        owner=_owner(session, request.owner_id),
        acknowledged_at=request.acknowledged_at,
        outcome=request.outcome,
        explanation=request.explanation,
        resolved_at=request.resolved_at,
        merged_into=_ref_of(session, request.merged_into_id),
        foreman_informed_at=request.foreman_informed_at,
        default_owner_id=session.scalar(
            select(CategoryOwnerDefault.owner_id).where(
                CategoryOwnerDefault.category == request.category
            )
        ),
        events=_events(session, request.id),
        calls=_linked_calls(session, request.id),
    )


def _ref_of(session: Session, request_id: int | None) -> str | None:
    other = session.get(Request, request_id) if request_id is not None else None
    return other.ref_display if other else None


def _linked_calls(session: Session, request_id: int) -> list[LinkedCall]:
    rows = session.execute(
        select(Call.id, Call.started_at, CallRequest.relation)
        .join(CallRequest, CallRequest.call_id == Call.id)
        .where(CallRequest.request_id == request_id)
        .order_by(Call.started_at, Call.id, CallRequest.relation)
    )
    return [LinkedCall(id=i, started_at=at, relation=rel) for i, at, rel in rows.tuples()]


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
