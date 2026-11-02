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

from app.db.models import Call, CallRequest, Foreman, Job, Request
from app.domain.draft import DraftItem
from app.domain.lifecycle import Status, transition
from app.domain.ref import parse_ref
from app.services.ack_window import set_ack_due_at
from app.services.events import agent_event, staff_event
from app.services.jobs import find_jobs


def _matched_job_id(session: Session, spoken: str | None) -> int | None:
    """The Job only when `find_jobs` (#13) gives exactly one match; else None (Unmatched).

    A Draft gets no read-back, so a spoken Job that fits several Jobs is never picked.
    """
    matches = find_jobs(session, spoken) if spoken else []
    return matches[0].job_id if len(matches) == 1 else None


def save_draft(
    session: Session, *, call_id: int, foreman_id: int, item: DraftItem, now: datetime
) -> Request:
    """Add the Draft, its `drafted` event (by the agent) and its link to the call.

    Does not commit: the caller (post-call processing) commits it with the call record.
    """
    draft = Request(
        foreman_id=foreman_id,
        job_id=_matched_job_id(session, item.job_spoken),
        job_spoken=item.job_spoken or "",  # "" = no Job was said
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
    agent_event(
        session,
        draft,
        now,
        "drafted",
        None,
        {
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
    session.add(CallRequest(call_id=call_id, request_id=draft.id, relation="created"))
    return draft


@dataclass(frozen=True)
class DraftRow:
    ref: str
    foreman: str
    job: str | None
    job_spoken: str
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


def record_draft(session: Session, *, ref: str, staff_id: uuid.UUID, now: datetime) -> Request:
    """A coordinator promotes a Draft to Recorded (Draft → Recorded guard).

    A Draft with no matched Job becomes an Unmatched Recorded Request (spec AC1.4).
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
    before: dict[str, object] = {
        "status": request.status,
        "recorded_at": None if request.recorded_at is None else request.recorded_at.isoformat(),
    }
    request.status = status.value
    request.recorded_at = now
    set_ack_due_at(session, request)
    after: dict[str, object] = {"status": request.status, "recorded_at": now.isoformat()}
    if request.ack_due_at is not None:  # changed fields only: a Draft has no ack window
        before["ack_due_at"] = None
        after["ack_due_at"] = request.ack_due_at.isoformat()
    staff_event(session, request, staff_id, now, "recorded", before, after)
    session.commit()
    return request
