"""Admin API for Owners, category defaults, staff, the duty roster and settings (#35).

`/api/admin/{owners,category-defaults,staff,duty,settings}`, open to every staff member (one
Staff role, ADR 0006), following #34's `/api/admin/{foremen,jobs}`. Owners and staff have no DELETE.
"""

import datetime
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy.orm import Session

from app.clock import Clock, get_clock
from app.db.models import DutyRoster, Owner, Settings, Staff
from app.db.session import get_session
from app.http.auth import CurrentStaff, current_staff
from app.services import office_admin
from app.services.office_admin import Invalid
from app.services.roster_admin import Conflict, NotFound
from app.services.settings import SettingsChanges, office_settings, update_office_settings

router = APIRouter(prefix="/api/admin", dependencies=[Depends(current_staff)])

DbSession = Annotated[Session, Depends(get_session)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
E164 = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\+[1-9][0-9]{1,14}$")]
Email = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
]
# An acknowledgment window in minutes: at least 1 minute, at most a week.
Minutes = Annotated[int, Field(ge=1, le=7 * 24 * 60)]


@contextmanager
def _http_errors() -> Iterator[None]:
    try:
        yield
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found") from exc
    except Conflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except Invalid as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


def _sent(patch: BaseModel) -> dict[str, Any]:
    """The fields the PATCH body actually sent (an absent field stays as it is).

    PATCH models give non-nullable fields a placeholder default only so they may be left out;
    a value that is sent is validated, and an explicit null for them is a 422.
    """
    return patch.model_dump(include=patch.model_fields_set)


# --- Owners ------------------------------------------------------------------------------


class OwnerOut(BaseModel):
    id: int
    name: str
    phone_e164: str | None
    email: str | None

    @classmethod
    def of(cls, owner: Owner) -> "OwnerOut":
        return cls(id=owner.id, name=owner.name, phone_e164=owner.phone_e164, email=owner.email)


class OwnerIn(BaseModel):
    name: Name
    phone_e164: E164 | None = None
    email: Email | None = None


class OwnerPatch(BaseModel):
    name: Name = ""
    phone_e164: E164 | None = None
    email: Email | None = None


@router.get("/owners")
def list_owners(session: DbSession) -> list[OwnerOut]:
    return [OwnerOut.of(o) for o in office_admin.list_owners(session)]


@router.post("/owners", status_code=status.HTTP_201_CREATED)
def add_owner(body: OwnerIn, session: DbSession) -> OwnerOut:
    with _http_errors():
        owner = office_admin.add_owner(
            session, name=body.name, phone_e164=body.phone_e164, email=body.email
        )
    return OwnerOut.of(owner)


@router.patch("/owners/{owner_id}")
def update_owner(owner_id: int, body: OwnerPatch, session: DbSession) -> OwnerOut:
    changes = cast(office_admin.OwnerChanges, _sent(body))
    with _http_errors():
        owner = office_admin.update_owner(session, owner_id, changes)
    return OwnerOut.of(owner)


# --- Category defaults -------------------------------------------------------------------


class CategoryDefaultOut(BaseModel):
    category: str
    owner_id: int | None


class CategoryDefaultIn(BaseModel):
    owner_id: int | None


@router.get("/category-defaults")
def list_category_defaults(session: DbSession) -> list[CategoryDefaultOut]:
    return [
        CategoryDefaultOut(category=d.category, owner_id=d.owner_id)
        for d in office_admin.category_defaults(session)
    ]


@router.put("/category-defaults/{category}")
def set_category_default(
    category: str, body: CategoryDefaultIn, session: DbSession
) -> CategoryDefaultOut:
    with _http_errors():
        default = office_admin.set_category_default(session, category, body.owner_id)
    return CategoryDefaultOut(category=default.category, owner_id=default.owner_id)


# --- Staff -------------------------------------------------------------------------------


class StaffOut(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    phone_e164: str | None

    @classmethod
    def of(cls, staff: Staff) -> "StaffOut":
        return cls(
            id=staff.id,
            name=staff.name,
            email=staff.email,
            phone_e164=staff.phone_e164,
        )


class StaffIn(BaseModel):
    id: uuid.UUID
    """The person's Supabase Auth user id (the account is created in Supabase first)."""
    name: Name
    email: Email
    phone_e164: E164 | None = None


class StaffPatch(BaseModel):
    name: Name = ""
    email: Email = ""
    phone_e164: E164 | None = None


@router.get("/staff")
def list_staff(session: DbSession) -> list[StaffOut]:
    return [StaffOut.of(s) for s in office_admin.list_staff(session)]


@router.post("/staff", status_code=status.HTTP_201_CREATED)
def add_staff(body: StaffIn, session: DbSession) -> StaffOut:
    with _http_errors():
        staff = office_admin.add_staff(
            session,
            staff_id=body.id,
            name=body.name,
            email=body.email,
            phone_e164=body.phone_e164,
        )
    return StaffOut.of(staff)


@router.patch("/staff/{staff_id}")
def update_staff(staff_id: uuid.UUID, body: StaffPatch, session: DbSession) -> StaffOut:
    changes = cast(office_admin.StaffChanges, _sent(body))
    with _http_errors():
        staff = office_admin.update_staff(session, staff_id, changes)
    return StaffOut.of(staff)


@router.delete("/staff/{staff_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_staff(
    staff_id: uuid.UUID,
    me: CurrentStaff,
    session: DbSession,
    clock: Annotated[Clock, Depends(get_clock)],
) -> Response:
    """Take a person off the staff list (they lose access at once); 409 for yourself or for
    someone still on the duty roster. Adding them again (`POST /staff`) restores them."""
    with _http_errors():
        office_admin.remove_staff(session, staff_id, by=me.id, now=clock())
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Duty roster -------------------------------------------------------------------------


class StaffRef(BaseModel):
    id: uuid.UUID
    name: str


class DutyOut(BaseModel):
    date: datetime.date
    on_duty: StaffRef
    backup: StaffRef | None

    @classmethod
    def of(cls, duty: DutyRoster) -> "DutyOut":
        backup = duty.backup
        return cls(
            date=duty.day,
            on_duty=StaffRef(id=duty.on_duty.id, name=duty.on_duty.name),
            backup=StaffRef(id=backup.id, name=backup.name) if backup else None,
        )


class DutyIn(BaseModel):
    on_duty_staff_id: uuid.UUID
    backup_staff_id: uuid.UUID | None = None


@router.get("/duty")
def list_duty(
    session: DbSession,
    clock: Annotated[Clock, Depends(get_clock)],
    start: Annotated[datetime.date | None, Query(alias="from")] = None,
) -> list[DutyOut]:
    """Duty days from `from` (default: today in New York) on."""
    return [DutyOut.of(d) for d in office_admin.duty_days(session, start=start, now=clock())]


@router.put("/duty/{day}")
def set_duty(day: datetime.date, body: DutyIn, session: DbSession) -> DutyOut:
    with _http_errors():
        duty = office_admin.set_duty_day(
            session, day, on_duty=body.on_duty_staff_id, backup=body.backup_staff_id
        )
    return DutyOut.of(duty)


@router.delete("/duty/{day}", status_code=status.HTTP_204_NO_CONTENT)
def remove_duty(day: datetime.date, session: DbSession) -> Response:
    with _http_errors():
        office_admin.remove_duty_day(session, day)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Settings ----------------------------------------------------------------------------


class SettingsOut(BaseModel):
    office_line_e164: str | None
    ack_window_today_min: int
    ack_window_planned_min: int

    @classmethod
    def of(cls, row: Settings) -> "SettingsOut":
        return cls(
            office_line_e164=row.office_line_e164,
            ack_window_today_min=row.ack_window_today_min,
            ack_window_planned_min=row.ack_window_planned_min,
        )


class SettingsPatch(BaseModel):
    office_line_e164: E164 | None = None
    ack_window_today_min: Minutes = 15
    ack_window_planned_min: Minutes = 120


@router.get("/settings")
def get_settings(session: DbSession) -> SettingsOut:
    return SettingsOut.of(office_settings(session))


@router.patch("/settings")
def update_settings(body: SettingsPatch, session: DbSession) -> SettingsOut:
    changes = cast(SettingsChanges, _sent(body))
    return SettingsOut.of(update_office_settings(session, changes))
