"""Dashboard API for editing fields and fixing the Job (ticket #31). Requires a staff token."""

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.clock import Clock, get_clock
from app.db.session import get_session
from app.domain.lifecycle import NotEditable
from app.http.api import RequestDetailOut, _updated
from app.http.auth import CurrentStaff
from app.services.request_edit import InvalidEdit, active_jobs, edit_request
from app.services.requests import RequestNotFound

router = APIRouter(prefix="/api")


class EditIn(BaseModel):
    """Only the fields sent are changed. Any other field (status, Owner, …) is refused."""

    model_config = ConfigDict(extra="forbid")

    job_id: int | None = None
    category: str | None = None
    need: str | None = None
    quantity: Decimal | None = None
    unit: str | None = None


@router.patch("/requests/{ref}")
def edit(
    ref: str,
    body: EditIn,
    staff: CurrentStaff,
    session: Annotated[Session, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> RequestDetailOut:
    """Edit fields / fix the Job; returns the updated Request. 422 when Resolved or invalid."""
    changes = {name: getattr(body, name) for name in body.model_fields_set}
    try:
        edit_request(session, ref=ref, changes=changes, staff_id=staff.id, now=clock())
    except RequestNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such request") from exc
    except (NotEditable, InvalidEdit) as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return _updated(session, ref)


class JobOut(BaseModel):
    id: int
    name: str


class JobsOut(BaseModel):
    jobs: list[JobOut]


@router.get("/jobs")
def jobs(staff: CurrentStaff, session: Annotated[Session, Depends(get_session)]) -> JobsOut:
    """Active Jobs by name, for fixing a Request's Job."""
    return JobsOut(jobs=[JobOut(id=j.id, name=j.name) for j in active_jobs(session)])
