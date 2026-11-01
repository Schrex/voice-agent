"""Admin upkeep of Owners, category defaults, staff and the duty roster (spec §3 Admin, #35).

Owners and staff are never deleted (Requests, alerts and duty days point at them); the admin
edits them instead. A duty day can be removed. Each function commits its own change; a rule
violation raises `NotFound`, `Conflict` or `Invalid` and writes nothing.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CATEGORIES, CategoryOwnerDefault, DutyRoster, Owner, Staff
from app.services.roster_admin import Conflict, NotFound


class Invalid(Exception):
    """The change names something that does not exist; the message says what."""


# --- Owners ------------------------------------------------------------------------------


class OwnerChanges(TypedDict, total=False):
    name: str
    phone_e164: str | None
    email: str | None


def list_owners(session: Session) -> list[Owner]:
    return list(session.scalars(select(Owner).order_by(Owner.name, Owner.id)))


def add_owner(session: Session, *, name: str, phone_e164: str | None, email: str | None) -> Owner:
    _ensure_owner_name_free(session, name)
    owner = Owner(name=name, phone_e164=phone_e164, email=email)
    session.add(owner)
    session.commit()
    return owner


def update_owner(session: Session, owner_id: int, changes: OwnerChanges) -> Owner:
    owner = session.get(Owner, owner_id)
    if owner is None:
        raise NotFound
    if "name" in changes and changes["name"] != owner.name:
        _ensure_owner_name_free(session, changes["name"])
        owner.name = changes["name"]
    if "phone_e164" in changes:
        owner.phone_e164 = changes["phone_e164"]
    if "email" in changes:
        owner.email = changes["email"]
    session.commit()
    return owner


def _ensure_owner_name_free(session: Session, name: str) -> None:
    """The Owner's name is what the agent says (J3), so two Owners may not share one."""
    if session.scalar(select(Owner.id).where(Owner.name == name)) is not None:
        raise Conflict(f"An Owner named {name} already exists.")


# --- Category defaults -------------------------------------------------------------------


@dataclass(frozen=True)
class CategoryDefault:
    category: str
    owner_id: int | None


def category_defaults(session: Session) -> list[CategoryDefault]:
    """Every Category in spec order, with its default Owner (None if not set)."""
    set_ = dict(
        session.execute(select(CategoryOwnerDefault.category, CategoryOwnerDefault.owner_id)).all()
    )
    return [CategoryDefault(category=c, owner_id=set_.get(c)) for c in CATEGORIES]


def set_category_default(session: Session, category: str, owner_id: int | None) -> CategoryDefault:
    """Make `owner_id` the Category's default Owner; None removes the default."""
    if category not in CATEGORIES:
        raise NotFound
    if owner_id is not None and session.get(Owner, owner_id) is None:
        raise Invalid("No such Owner.")
    default = session.get(CategoryOwnerDefault, category)
    if owner_id is None:
        if default is not None:
            session.delete(default)
    elif default is None:
        session.add(CategoryOwnerDefault(category=category, owner_id=owner_id))
    else:
        default.owner_id = owner_id
    session.commit()
    return CategoryDefault(category=category, owner_id=owner_id)


# --- Staff -------------------------------------------------------------------------------


class StaffChanges(TypedDict, total=False):
    name: str
    email: str
    role: str
    phone_e164: str | None


def list_staff(session: Session) -> list[Staff]:
    return list(session.scalars(select(Staff).order_by(Staff.name, Staff.id)))


def add_staff(
    session: Session,
    *,
    staff_id: uuid.UUID,
    name: str,
    email: str,
    role: str,
    phone_e164: str | None,
) -> Staff:
    """Put a Supabase Auth user (`staff_id`) on the staff list, so they can use the dashboard."""
    if session.get(Staff, staff_id) is not None:
        raise Conflict("That user is already on the staff list.")
    staff = Staff(id=staff_id, name=name, email=email, role=role, phone_e164=phone_e164)
    session.add(staff)
    session.commit()
    return staff


def update_staff(session: Session, staff_id: uuid.UUID, changes: StaffChanges) -> Staff:
    staff = session.get(Staff, staff_id)
    if staff is None:
        raise NotFound
    if "name" in changes:
        staff.name = changes["name"]
    if "email" in changes:
        staff.email = changes["email"]
    if "role" in changes:
        staff.role = changes["role"]
    if "phone_e164" in changes:
        staff.phone_e164 = changes["phone_e164"]
    session.commit()
    return staff


# --- Duty roster -------------------------------------------------------------------------


def duty_days(session: Session, *, start: date) -> list[DutyRoster]:
    """Duty days from `start` on, by date."""
    return list(
        session.scalars(select(DutyRoster).where(DutyRoster.day >= start).order_by(DutyRoster.day))
    )


def set_duty_day(
    session: Session, day: date, *, on_duty: uuid.UUID, backup: uuid.UUID | None
) -> DutyRoster:
    """Name the on-duty Coordinator (and backup) for a New York date, replacing any before."""
    for staff_id in (on_duty, backup):
        if staff_id is not None and session.get(Staff, staff_id) is None:
            raise Invalid("No such staff member.")
    duty = session.get(DutyRoster, day)
    if duty is None:
        duty = DutyRoster(day=day, on_duty_staff_id=on_duty)
        session.add(duty)
    duty.on_duty_staff_id = on_duty
    duty.backup_staff_id = backup
    session.commit()
    session.refresh(duty)
    return duty


def remove_duty_day(session: Session, day: date) -> None:
    duty = session.get(DutyRoster, day)
    if duty is None:
        raise NotFound
    session.delete(duty)
    session.commit()
