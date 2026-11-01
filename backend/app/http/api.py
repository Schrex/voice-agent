"""Dashboard API (`/api/*`, architecture §4.3). Every route requires a staff token."""

import uuid
from datetime import UTC
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.http.auth import CurrentStaff
from app.services.queue import open_requests

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
    job: str
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
                need=row.need,
                quantity=row.quantity,
                unit=row.unit,
                needed_by=row.needed_by,
                urgency=row.urgency,
                status=row.status,
                recorded_at=row.recorded_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            )
            for row in open_requests(session)
        ]
    )
