"""Dashboard API (`/api/*`, architecture §4.3). Every route requires a staff token."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.http.auth import CurrentStaff
from app.services.queue import open_requests
from app.services.request_detail import request_detail

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
    needed_by: str | None
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
                needed_by=row.needed_by,
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


class RequestDetailOut(BaseModel):
    ref: str
    foreman: str
    job: str | None  # null = Unmatched
    job_spoken: str
    category: str
    need: str
    quantity: str | None
    unit: str | None
    needed_by: str | None
    urgency: str | None
    status: str
    source: str
    recorded_at: str | None  # null while the Request is a Draft
    events: list[EventOut]  # oldest first


@router.get("/requests/{ref}")
def detail(
    ref: str, staff: CurrentStaff, session: Annotated[Session, Depends(get_session)]
) -> RequestDetailOut:
    """One Request's fields and its full audit history (who, when, what changed)."""
    found = request_detail(session, ref)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such request")
    return RequestDetailOut(
        ref=found.ref,
        foreman=found.foreman,
        job=found.job,
        job_spoken=found.job_spoken,
        category=found.category,
        need=found.need,
        quantity=found.quantity,
        unit=found.unit,
        needed_by=found.needed_by,
        urgency=found.urgency,
        status=found.status,
        source=found.source,
        recorded_at=None if found.recorded_at is None else _utc(found.recorded_at),
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
    )


def _utc(at: datetime) -> str:
    return at.astimezone(UTC).isoformat().replace("+00:00", "Z")
