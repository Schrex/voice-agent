"""Edit fields / fix the Job (ticket #31; spec J9, architecture §4.3 `PATCH /api/requests/{ref}`).

A coordinator corrects what was recorded, or assigns a real Job to an Unmatched Request. The
change and an `edited` event (changed fields only, before and after) are committed together.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CATEGORIES, Job, Request
from app.domain.lifecycle import Status, edit
from app.domain.request_edit import changed_fields
from app.services.queue import as_said
from app.services.requests import _locked, _staff_event


class InvalidEdit(ValueError):
    pass


@dataclass(frozen=True)
class ActiveJob:
    id: int
    name: str


def active_jobs(session: Session) -> list[ActiveJob]:
    """Every active Job, sorted by name: the Jobs a coordinator can fix a Request to."""
    rows = session.execute(select(Job.id, Job.name).where(Job.active).order_by(Job.name, Job.id))
    return [ActiveJob(id=job_id, name=name) for job_id, name in rows]


def edit_request(
    session: Session,
    *,
    ref: str,
    changes: Mapping[str, object],
    staff_id: uuid.UUID,
    now: datetime,
) -> None:
    """Apply `changes` to the Request rendered `ref`.

    Editable: job_id, category, need, quantity, unit. Status, Owner and Outcome have their own
    actions; what the Foreman said (`job_spoken`, `needed_by_spoken`) is kept as said.

    Resolved Requests are not editable (`domain.lifecycle.edit`). The Job must be an active Job
    (an edit cannot make a Request Unmatched again); the category one of the glossary's; the
    need not blank. Writes one `edited` event by the staff member with the fields that changed,
    in the same transaction; an edit that changes nothing writes nothing. A refused edit raises
    and writes nothing.
    """
    request = _locked(session, ref)
    edit(Status(request.status))
    proposed = {name: _checked(session, name, value) for name, value in changes.items()}
    before, after = changed_fields(_current(request), proposed)
    if not after:
        session.rollback()  # release the row lock
        return
    for name, value in after.items():
        stored = Decimal(str(value)) if name == "quantity" and value is not None else value
        setattr(request, name, stored)
    _staff_event(session, request, staff_id, now, "edited", before, after)
    session.commit()


def _current(request: Request) -> dict[str, object]:
    return {
        "job_id": request.job_id,
        "category": request.category,
        "need": request.need,
        "quantity": as_said(request.quantity),
        "unit": request.unit,
    }


def _checked(session: Session, name: str, value: object) -> object:
    """The value as stored and recorded in the event; InvalidEdit if it is not allowed."""
    if name == "job_id":
        job = session.get(Job, value) if isinstance(value, int) else None
        if job is None or not job.active:
            raise InvalidEdit("Choose an active Job")
        return job.id
    if name == "category":
        if value not in CATEGORIES:
            raise InvalidEdit("Choose a category")
        return value
    if name == "need":
        if not isinstance(value, str) or not value.strip():
            raise InvalidEdit("The need cannot be blank")
        return value.strip()
    if name == "quantity":
        if value is None:
            return None
        if not isinstance(value, Decimal) or not value.is_finite():
            raise InvalidEdit("The quantity must be a number")
        return as_said(value)
    if name == "unit":
        if value is None:
            return None
        if not isinstance(value, str):
            raise InvalidEdit("The unit must be text")
        return value.strip() or None
    raise InvalidEdit(f"{name} cannot be edited")
