"""Quick entry (spec J7, ticket #30): a coordinator logs a request from a call they answered."""

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.clock import Clock, get_clock
from app.db.models import CATEGORIES
from app.db.session import get_session
from app.http.auth import CurrentStaff
from app.services.quick_entry import quick_entry_choices
from app.services.requests import (
    QuickEntry,
    UnknownForeman,
    UnknownJob,
    UnknownOwner,
    log_request,
)

router = APIRouter(prefix="/api")


class QuickEntryIn(BaseModel):
    foreman_id: int
    job_id: int
    category: str
    need: str
    quantity: Decimal | None = None
    unit: str | None = None
    needed_by: str | None = None  # as typed; resolved like a spoken needed-by
    owner_id: int | None = None  # given → logged straight to Acknowledged

    @field_validator("category")
    @classmethod
    def _category(cls, value: str) -> str:
        if value not in CATEGORIES:
            raise ValueError("not a Category")
        return value

    @field_validator("need")
    @classmethod
    def _need(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("need is required")
        return value.strip()

    @field_validator("unit", "needed_by")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class LoggedOut(BaseModel):
    ref: str
    status: str  # Recorded, or Acknowledged when an Owner was given


@router.post("/requests", status_code=status.HTTP_201_CREATED)
def log(
    body: QuickEntryIn,
    staff: CurrentStaff,
    session: Annotated[Session, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> LoggedOut:
    """Create a coordinator-logged Request (source `coordinator`); 422 and nothing written if
    the Foreman or Job is unknown or inactive, or the Owner unknown."""
    entry = QuickEntry(
        foreman_id=body.foreman_id,
        job_id=body.job_id,
        category=body.category,
        need=body.need,
        quantity=body.quantity,
        unit=body.unit,
        needed_by_spoken=body.needed_by,
        owner_id=body.owner_id,
    )
    try:
        logged = log_request(session, entry=entry, staff_id=staff.id, now=clock())
    except (UnknownForeman, UnknownJob, UnknownOwner) as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return LoggedOut(ref=logged.ref, status=logged.status)


class ChoiceOut(BaseModel):
    id: int
    name: str


class QuickEntryChoicesOut(BaseModel):
    foremen: list[ChoiceOut]  # active only, by last then first name
    jobs: list[ChoiceOut]  # active only, by name
    categories: list[str]  # glossary order
    owners: list[ChoiceOut]  # by name


@router.get("/quick-entry")
def choices(
    staff: CurrentStaff, session: Annotated[Session, Depends(get_session)]
) -> QuickEntryChoicesOut:
    """What the quick-entry form offers."""
    found = quick_entry_choices(session)
    return QuickEntryChoicesOut(
        foremen=[ChoiceOut(id=c.id, name=c.name) for c in found.foremen],
        jobs=[ChoiceOut(id=c.id, name=c.name) for c in found.jobs],
        categories=list(CATEGORIES),
        owners=[ChoiceOut(id=c.id, name=c.name) for c in found.owners],
    )
