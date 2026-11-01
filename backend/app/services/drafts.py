"""Drafts: Requests the Foreman did not confirm (spec §5, AC1.8, AC5.2; architecture §3.4).

A Draft is saved by post-call processing and linked to its call. It never enters the queue.
A coordinator can promote it to Recorded. Every write adds a `request_events` row in the same
transaction; nothing is deleted.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.db.models import Call, CallRequest, Foreman, Job, JobAlias, Request
from app.db.models import RequestEvent as Event
from app.domain.draft import DraftItem, exact_job_match
from app.domain.lifecycle import Status, transition


def _active_job_names(session: Session) -> list[tuple[int, list[str]]]:
    names: dict[int, list[str]] = {}
    for job_id, name in session.execute(select(Job.id, Job.name).where(Job.active)):
        names[job_id] = [name]
    for job_id, alias in session.execute(
        select(JobAlias.job_id, JobAlias.alias).join(Job).where(Job.active)
    ):
        names[job_id].append(alias)
    return list(names.items())


def save_draft(
    session: Session, *, call_id: int, foreman_id: int, item: DraftItem, now: datetime
) -> Request:
    """Add the Draft, its `drafted` event (by the agent) and its link to the call.

    Does not commit: the caller (post-call processing) commits it with the call record.
    """
    draft = Request(
        foreman_id=foreman_id,
        job_id=exact_job_match(item.job_spoken, _active_job_names(session)),
        job_spoken=item.job_spoken,
        category=item.category,
        need=item.need,
        quantity=item.quantity,
        unit=item.unit,
        needed_by_spoken=item.needed_by_spoken,
        status=Status.DRAFT.value,
        source="ai_call",
        recorded_at=None,
    )
    session.add(draft)
    session.flush()
    session.add(
        Event(
            request_id=draft.id,
            at=now,
            actor_type="agent",
            actor_id=None,
            kind="drafted",
            before=None,
            after={
                "ref": draft.ref_display,
                "foreman_id": draft.foreman_id,
                "job_id": draft.job_id,
                "job_spoken": draft.job_spoken,
                "category": draft.category,
                "need": draft.need,
                "quantity": None if draft.quantity is None else str(draft.quantity),
                "unit": draft.unit,
                "needed_by_spoken": draft.needed_by_spoken,
                "status": draft.status,
                "source": draft.source,
            },
        )
    )
    session.add(CallRequest(call_id=call_id, request_id=draft.id, relation="created"))
    return draft


@dataclass(frozen=True)
class DraftRow:
    ref: str
    foreman: str
    job: str | None
    job_spoken: str | None
    category: str
    need: str
    quantity: Decimal | None
    unit: str | None
    needed_by_spoken: str | None
    call_started_at: datetime | None
    call_summary: str | None


def list_drafts(session: Session) -> list[DraftRow]:
    """Every Draft, newest call first, with the call it came from."""
    link = aliased(CallRequest)
    rows = session.execute(
        select(Request, Foreman, Job.name, Call.started_at, Call.summary)
        .join(Foreman, Foreman.id == Request.foreman_id)
        .outerjoin(Job, Job.id == Request.job_id)
        .outerjoin(link, (link.request_id == Request.id) & (link.relation == "created"))
        .outerjoin(Call, Call.id == link.call_id)
        .where(Request.status == Status.DRAFT.value)
        .order_by(Call.started_at.desc().nulls_last(), Request.ref.desc())
    ).all()
    return [
        DraftRow(
            ref=request.ref_display,
            foreman=f"{foreman.first_name} {foreman.last_name}",
            job=job_name,
            job_spoken=request.job_spoken,
            category=request.category,
            need=request.need,
            quantity=request.quantity,
            unit=request.unit,
            needed_by_spoken=request.needed_by_spoken,
            call_started_at=started_at,
            call_summary=summary,
        )
        for request, foreman, job_name, started_at, summary in rows
    ]


class RequestNotFound(LookupError):
    pass


def parse_ref(ref: str) -> int | None:
    """ "R-1042" → 1042; anything else → None."""
    prefix, _, number = ref.partition("-")
    if prefix != "R" or not number.isdigit():
        return None
    return int(number)


def record_draft(session: Session, *, ref: str, staff_id: uuid.UUID, now: datetime) -> Request:
    """A coordinator promotes a Draft to Recorded (Draft → Recorded guard).

    Raises RequestNotFound for an unknown ref and TransitionNotAllowed when the Request is not
    a Draft; either way nothing is written.
    """
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
    status = transition(Status(request.status), Status.RECORDED)
    before = {
        "status": request.status,
        "recorded_at": None if request.recorded_at is None else request.recorded_at.isoformat(),
    }
    request.status = status.value
    request.recorded_at = now
    session.add(
        Event(
            request_id=request.id,
            at=now,
            actor_type="staff",
            actor_id=str(staff_id),
            kind="recorded",
            before=before,
            after={"status": request.status, "recorded_at": now.isoformat()},
        )
    )
    session.commit()
    return request
