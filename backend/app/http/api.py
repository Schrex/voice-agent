"""Dashboard API (`/api/*`, architecture §4.3). Every route requires a staff token."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.clock import Clock, get_clock
from app.db.session import get_session
from app.domain.lifecycle import (
    AlreadyInformed,
    ExplanationRequired,
    MergeIntoItself,
    NotResolved,
    Outcome,
    OutcomeRequired,
    OwnerRequired,
    Status,
    TransitionNotAllowed,
)
from app.domain.sla import is_uninformed
from app.http.auth import CurrentStaff
from app.services.merges import merge_request
from app.services.owners import list_owners
from app.services.queue import open_requests
from app.services.request_detail import RequestDetail, request_detail
from app.services.requests import (
    RequestNotFound,
    UnknownOwner,
    acknowledge_request,
    mark_foreman_informed,
    resolve_request,
    start_request,
)
from app.services.settings import uninformed_after
from app.services.uninformed import uninformed_requests

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
    overdue: bool  # still Recorded after its ack window (ticket #22)


class QueueOut(BaseModel):
    requests: list[QueueRequestOut]


class UninformedRequestOut(BaseModel):
    ref: str
    foreman: str  # full name: who to tell
    job: str | None  # null = Unmatched
    job_spoken: str
    need: str
    outcome: str
    resolved_at: str  # UTC, ISO 8601 with "Z"


class UninformedOut(BaseModel):
    requests: list[UninformedRequestOut]


@router.get("/requests")
def queue(
    staff: CurrentStaff,
    session: Annotated[Session, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
    flag: Literal["uninformed"] | None = None,
) -> QueueOut | UninformedOut:
    """Open Requests, sorted urgency then age (spec J9), each flagged Overdue or not (#22).

    `?flag=uninformed`: instead, the Uninformed Requests (Resolved, not marked Foreman Informed
    within the threshold), oldest Resolved first (ticket #32, AC9.4).
    """
    if flag == "uninformed":
        return UninformedOut(
            requests=[
                UninformedRequestOut(
                    ref=row.ref,
                    foreman=row.foreman,
                    job=row.job,
                    job_spoken=row.job_spoken,
                    need=row.need,
                    outcome=row.outcome,
                    resolved_at=_utc(row.resolved_at),
                )
                for row in uninformed_requests(session, clock())
            ]
        )
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
                overdue=row.overdue,
            )
            for row in open_requests(session, clock())
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


class NoteOut(BaseModel):
    at: str  # UTC, ISO 8601 with "Z"
    author_type: str  # agent | staff | system
    author: str | None  # the staff member's name; null for the agent
    text: str
    urgent: bool


class RequestDetailOut(BaseModel):
    ref: str
    foreman: str
    job: str | None  # null = Unmatched
    job_id: int | None  # null = Unmatched
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
    outcome: str | None  # Fulfilled | Partially Fulfilled | Denied | Withdrawn; null until Resolved
    explanation: str | None  # as the coordinator wrote it; null until Resolved
    resolved_at: str | None  # UTC, ISO 8601 with "Z"; null until Resolved
    merged_into: str | None  # ref of the Request this one was merged into; null if not merged
    foreman_informed_at: str | None  # UTC, ISO 8601 with "Z"; null until marked Foreman Informed
    uninformed: bool  # Resolved, not marked Foreman Informed within the threshold (now)
    default_owner_id: int | None  # the category's default Owner, offered when acknowledging
    events: list[EventOut]  # oldest first
    calls: list[LinkedCallOut]  # oldest first
    notes: list[NoteOut]  # oldest first (ticket #17)


@router.get("/requests/{ref}")
def detail(
    ref: str,
    staff: CurrentStaff,
    session: Annotated[Session, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> RequestDetailOut:
    """One Request's fields and its full audit history (who, when, what changed)."""
    found = request_detail(session, ref)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such request")
    return _detail_out(found, clock(), uninformed_after(session))


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
    now = clock()
    try:
        acknowledge_request(session, ref=ref, owner_id=body.owner_id, staff_id=staff.id, now=now)
    except RequestNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such request") from exc
    except (OwnerRequired, TransitionNotAllowed, UnknownOwner) as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return _updated(session, ref, now)


@router.post("/requests/{ref}/start")
def start(
    ref: str,
    staff: CurrentStaff,
    session: Annotated[Session, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> RequestDetailOut:
    """Acknowledged → In Progress ("Move to In Progress"); returns the updated Request."""
    now = clock()
    try:
        start_request(session, ref=ref, staff_id=staff.id, now=now)
    except RequestNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such request") from exc
    except TransitionNotAllowed as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return _updated(session, ref, now)


class ResolveIn(BaseModel):
    # Optional here so a missing Outcome or explanation reaches the lifecycle guard (AC9.2);
    # an Outcome outside the glossary's four is refused by validation. Either way: 422.
    outcome: Outcome | None = None
    explanation: str | None = None


@router.post("/requests/{ref}/resolve")
def resolve(
    ref: str,
    body: ResolveIn,
    staff: CurrentStaff,
    session: Annotated[Session, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> RequestDetailOut:
    """Any open status → Resolved with an Outcome and explanation; returns the updated Request."""
    now = clock()
    try:
        resolve_request(
            session,
            ref=ref,
            outcome=body.outcome,
            explanation=body.explanation,
            staff_id=staff.id,
            now=now,
        )
    except RequestNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such request") from exc
    except (OutcomeRequired, ExplanationRequired, TransitionNotAllowed) as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return _updated(session, ref, now)


class MergeIn(BaseModel):
    into: str  # ref of the Request to merge into ("R-1042")
    # Optional, as in ResolveIn, so a missing one reaches the lifecycle guard: 422 either way.
    outcome: Outcome | None = None
    explanation: str | None = None


@router.post("/requests/{ref}/merge")
def merge(
    ref: str,
    body: MergeIn,
    staff: CurrentStaff,
    session: Annotated[Session, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> RequestDetailOut:
    """Merge this duplicate into another Request: this one is Resolved with a pointer to it."""
    now = clock()
    try:
        merge_request(
            session,
            ref=ref,
            into=body.into,
            outcome=body.outcome,
            explanation=body.explanation,
            staff_id=staff.id,
            now=now,
        )
    except RequestNotFound as exc:
        session.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such request") from exc
    except (
        OutcomeRequired,
        ExplanationRequired,
        TransitionNotAllowed,
        MergeIntoItself,
    ) as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return _updated(session, ref, now)


@router.post("/requests/{ref}/informed")
def informed(
    ref: str,
    staff: CurrentStaff,
    session: Annotated[Session, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> RequestDetailOut:
    """Mark Foreman Informed on a Resolved Request (once); returns the updated Request."""
    now = clock()
    try:
        mark_foreman_informed(session, ref=ref, staff_id=staff.id, now=now)
    except RequestNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such request") from exc
    except (NotResolved, AlreadyInformed) as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return _updated(session, ref, now)


def _updated(session: Session, ref: str, now: datetime) -> RequestDetailOut:
    found = request_detail(session, ref)
    assert found is not None
    return _detail_out(found, now, uninformed_after(session))


class OwnersOut(BaseModel):
    owners: list[OwnerOut]


@router.get("/owners")
def owners(staff: CurrentStaff, session: Annotated[Session, Depends(get_session)]) -> OwnersOut:
    """Every Owner by name, for the Acknowledge picker."""
    return OwnersOut(owners=[OwnerOut(id=o.id, name=o.name) for o in list_owners(session)])


def _detail_out(found: RequestDetail, now: datetime, after: timedelta) -> RequestDetailOut:
    return RequestDetailOut(
        ref=found.ref,
        foreman=found.foreman,
        job=found.job,
        job_id=found.job_id,
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
        outcome=found.outcome,
        explanation=found.explanation,
        resolved_at=_utc(found.resolved_at) if found.resolved_at else None,
        merged_into=found.merged_into,
        foreman_informed_at=_utc_or_none(found.foreman_informed_at),
        uninformed=is_uninformed(
            Status(found.status),
            resolved_at=found.resolved_at,
            foreman_informed_at=found.foreman_informed_at,
            now=now,
            after=after,
        ),
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
        notes=[
            NoteOut(
                at=_utc(n.at),
                author_type=n.author_type,
                author=n.author,
                text=n.text,
                urgent=n.urgent,
            )
            for n in found.notes
        ],
    )


def _utc(at: datetime) -> str:
    return at.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _utc_or_none(at: datetime | None) -> str | None:
    return None if at is None else _utc(at)
