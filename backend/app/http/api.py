"""Dashboard API (`/api/*`, architecture §4.3). Every route requires a staff token."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.clock import Clock, get_clock
from app.db.session import get_session
from app.domain.lifecycle import OwnerRequired, TransitionNotAllowed
from app.http.auth import CurrentStaff
from app.services.owners import list_owners
from app.services.queue import open_requests
from app.services.request_detail import RequestDetail, request_detail
from app.services.requests import RequestNotFound, UnknownOwner, acknowledge_request

router = APIRouter(prefix="/api")


class StaffOut(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    role: str


@router.get("/me")
def me(staff: CurrentStaff) -> StaffOut:
    """The signed-in staff member; the dashboard calls it after login to check access."""
    return StaffOut(id=staff.id, name=staff.name, email=staff.email, role=staff.role)


class QueueRequestOut(BaseModel):
    ref: str
    job: str | None  # null = Unmatched (no confident match for what the Foreman said)
    job_spoken: str  # the Job as the Foreman said it
    need: str
    quantity: str | None
    unit: str | None
    needed_by: str | None  # UTC ISO 8601 "Z"; null = unknown, not understood, or day only
    needed_by_spoken: str | None  # as the Foreman said it; null = they could not say
    urgency: str | None
    status: str
    recorded_at: str  # UTC, ISO 8601 with "Z"; the dashboard shows it in America/New_York


class QueueOut(BaseModel):
    requests: list[QueueRequestOut]


@router.get("/requests")
def queue(staff: CurrentStaff, session: Annotated[Session, Depends(get_session)]) -> QueueOut:
    """Open Requests, sorted urgency then age (spec J9)."""
    return QueueOut(
        requests=[
            QueueRequestOut(
                ref=row.ref,
                job=row.job,
                job_spoken=row.job_spoken,
                need=row.need,
                quantity=row.quantity,
                unit=row.unit,
                needed_by=_utc_or_none(row.needed_by),
                needed_by_spoken=row.needed_by_spoken,
                urgency=row.urgency,
                status=row.status,
                recorded_at=_utc(row.recorded_at),
            )
            for row in open_requests(session)
        ]
    )


class ActorOut(BaseModel):
    type: str  # agent | staff | system
    id: str | None
    name: str | None  # the staff member's name; null for the agent and the system


class EventOut(BaseModel):
    at: str  # UTC, ISO 8601 with "Z"
    actor: ActorOut
    kind: str
    before: dict[str, Any] | None  # changed fields only; null when the Request was created
    after: dict[str, Any] | None


class LinkedCallOut(BaseModel):
    id: int  # transcript at GET /api/calls/{id}, recording at GET /api/calls/{id}/audio
    started_at: str  # UTC, ISO 8601 with "Z"
    relation: str  # created | looked_up | amended


class OwnerOut(BaseModel):
    id: int
    name: str


class RequestDetailOut(BaseModel):
    ref: str
    foreman: str
    job: str | None  # null = Unmatched
    job_spoken: str
    category: str
    need: str
    quantity: str | None
    unit: str | None
    needed_by: str | None  # UTC ISO 8601 "Z"; null = unknown, not understood, or day only
    needed_by_spoken: str | None  # as the Foreman said it; null = they could not say
    urgency: str | None
    status: str
    source: str
    recorded_at: str | None  # null while the Request is a Draft
    owner: OwnerOut | None
    acknowledged_at: str | None  # UTC, ISO 8601 with "Z"; null until Acknowledged
    default_owner_id: int | None  # the category's default Owner, offered when acknowledging
    events: list[EventOut]  # oldest first
    calls: list[LinkedCallOut]  # oldest first


@router.get("/requests/{ref}")
def detail(
    ref: str, staff: CurrentStaff, session: Annotated[Session, Depends(get_session)]
) -> RequestDetailOut:
    """One Request's fields and its full audit history (who, when, what changed)."""
    found = request_detail(session, ref)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such request")
    return _detail_out(found)


class AcknowledgeIn(BaseModel):
    # Optional here so a missing Owner reaches the lifecycle guard (AC9.1) rather than
    # FastAPI's validation; either way the answer is 422 and nothing is written.
    owner_id: int | None = None


@router.post("/requests/{ref}/acknowledge")
def acknowledge(
    ref: str,
    body: AcknowledgeIn,
    staff: CurrentStaff,
    session: Annotated[Session, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> RequestDetailOut:
    """Recorded → Acknowledged with an Owner; returns the updated Request."""
    try:
        acknowledge_request(
            session, ref=ref, owner_id=body.owner_id, staff_id=staff.id, now=clock()
        )
    except RequestNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such request") from exc
    except (OwnerRequired, TransitionNotAllowed, UnknownOwner) as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    found = request_detail(session, ref)
    assert found is not None
    return _detail_out(found)


class OwnersOut(BaseModel):
    owners: list[OwnerOut]


@router.get("/owners")
def owners(staff: CurrentStaff, session: Annotated[Session, Depends(get_session)]) -> OwnersOut:
    """Every Owner by name, for the Acknowledge picker."""
    return OwnersOut(owners=[OwnerOut(id=o.id, name=o.name) for o in list_owners(session)])


def _detail_out(found: RequestDetail) -> RequestDetailOut:
    return RequestDetailOut(
        ref=found.ref,
        foreman=found.foreman,
        job=found.job,
        job_spoken=found.job_spoken,
        category=found.category,
        need=found.need,
        quantity=found.quantity,
        unit=found.unit,
        needed_by=_utc_or_none(found.needed_by),
        needed_by_spoken=found.needed_by_spoken,
        urgency=found.urgency,
        status=found.status,
        source=found.source,
        recorded_at=None if found.recorded_at is None else _utc(found.recorded_at),
        owner=OwnerOut(id=found.owner.id, name=found.owner.name) if found.owner else None,
        acknowledged_at=_utc(found.acknowledged_at) if found.acknowledged_at else None,
        default_owner_id=found.default_owner_id,
        events=[
            EventOut(
                at=_utc(e.at),
                actor=ActorOut(type=e.actor.type, id=e.actor.id, name=e.actor.name),
                kind=e.kind,
                before=e.before,
                after=e.after,
            )
            for e in found.events
        ],
        calls=[
            LinkedCallOut(id=c.id, started_at=_utc(c.started_at), relation=c.relation)
            for c in found.calls
        ],
    )


def _utc(at: datetime) -> str:
    return at.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _utc_or_none(at: datetime | None) -> str | None:
    return None if at is None else _utc(at)
