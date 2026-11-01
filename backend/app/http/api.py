"""Dashboard API (`/api/*`, architecture §4.3). Every route requires a staff token."""

import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from app.http.auth import CurrentStaff

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
