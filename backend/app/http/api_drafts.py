"""Dashboard API for Drafts (ticket #28): the Drafts list, kept apart from the queue, and
promoting a Draft to Recorded. Every route requires a staff token.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.clock import Clock, get_clock
from app.db.session import get_session
from app.domain.lifecycle import TransitionNotAllowed
from app.http.auth import CurrentStaff
from app.services.drafts import DraftWithoutJob, RequestNotFound, list_drafts, record_draft

router = APIRouter(prefix="/api")


class DraftOut(BaseModel):
    ref: str
    foreman: str
    job: str | None  # null: the Job as spoken matched no active Job
    job_spoken: str | None
    category: str
    need: str
    quantity: str | None
    unit: str | None
    needed_by_spoken: str | None
    call_started_at: str | None  # UTC, ISO 8601 with "Z"; shown in America/New_York
    call_summary: str | None


class DraftsOut(BaseModel):
    drafts: list[DraftOut]


def _utc(at: datetime | None) -> str | None:
    return None if at is None else at.astimezone(UTC).isoformat().replace("+00:00", "Z")


@router.get("/drafts")
def drafts(staff: CurrentStaff, session: Annotated[Session, Depends(get_session)]) -> DraftsOut:
    """Requests the Foreman did not confirm, newest call first. Never part of the queue."""
    return DraftsOut(
        drafts=[
            DraftOut(
                ref=row.ref,
                foreman=row.foreman,
                job=row.job,
                job_spoken=row.job_spoken,
                category=row.category,
                need=row.need,
                quantity=None if row.quantity is None else format(row.quantity.normalize(), "f"),
                unit=row.unit,
                needed_by_spoken=row.needed_by_spoken,
                call_started_at=_utc(row.call_started_at),
                call_summary=row.call_summary,
            )
            for row in list_drafts(session)
        ]
    )


class RecordedOut(BaseModel):
    ref: str
    status: str


@router.post("/requests/{ref}/record")
def record(
    ref: str,
    staff: CurrentStaff,
    session: Annotated[Session, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> RecordedOut:
    """Promote a Draft to Recorded. 404 unknown ref; 422 if it is not a Draft or has no Job."""
    try:
        request = record_draft(session, ref=ref, staff_id=staff.id, now=clock())
    except RequestNotFound as exc:
        session.rollback()
        raise HTTPException(404, "No such request") from exc
    except TransitionNotAllowed as exc:
        session.rollback()
        raise HTTPException(422, "Only a Draft can be recorded") from exc
    except DraftWithoutJob as exc:
        session.rollback()
        raise HTTPException(422, "The Job is not known; set it before recording") from exc
    return RecordedOut(ref=request.ref_display, status=request.status)
