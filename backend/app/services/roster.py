"""Roster and job list loading (seed). Idempotent: re-running a file changes nothing.

Matching keys: a Job by its name, a Foreman by any of their phone numbers (numbers are unique),
a Staff member by their Supabase Auth user id, an Owner by their name.
Rows are created or updated from the file; nothing absent from the file is removed. An Owner's
`default_for` categories make them that category's default Owner (one Owner per category).
"""

import json
import uuid
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    CATEGORIES,
    CategoryOwnerDefault,
    Foreman,
    ForemanPhone,
    Job,
    JobAlias,
    Owner,
    Staff,
)


class JobEntry(BaseModel):
    name: str = Field(min_length=1)
    active: bool = True
    aliases: list[str] = []


class ForemanEntry(BaseModel):
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    active: bool = True
    phones: list[str] = Field(min_length=1)


class StaffEntry(BaseModel):
    """A dashboard user; `id` is their Supabase Auth user id (created in Supabase first)."""

    id: uuid.UUID
    name: str = Field(min_length=1)
    email: str = Field(min_length=3)
    role: Literal["coordinator", "admin"]


class OwnerEntry(BaseModel):
    name: str = Field(min_length=1)
    phone_e164: str | None = None
    email: str | None = None
    default_for: list[str] = []

    @model_validator(mode="after")
    def _known_categories(self) -> Self:
        unknown = [c for c in self.default_for if c not in CATEGORIES]
        if unknown:
            raise ValueError(f"Unknown categories: {unknown}")
        return self


class RosterFile(BaseModel):
    jobs: list[JobEntry] = []
    foremen: list[ForemanEntry] = []
    staff: list[StaffEntry] = []
    owners: list[OwnerEntry] = []

    @model_validator(mode="after")
    def _one_default_owner_per_category(self) -> Self:
        categories = [c for o in self.owners for c in o.default_for]
        twice = sorted({c for c in categories if categories.count(c) > 1})
        if twice:
            raise ValueError(f"Categories with more than one default Owner: {twice}")
        return self


def load_roster_file(path: Path) -> RosterFile:
    return RosterFile.model_validate(json.loads(path.read_text()))


def seed_roster(session: Session, roster: RosterFile) -> None:
    """Upsert jobs (with aliases), foremen (with phones), staff and owners, then commit."""
    for job_entry in roster.jobs:
        _upsert_job(session, job_entry)
    for foreman_entry in roster.foremen:
        _upsert_foreman(session, foreman_entry)
    for staff_entry in roster.staff:
        _upsert_staff(session, staff_entry)
    for owner_entry in roster.owners:
        _upsert_owner(session, owner_entry)
    session.commit()


def _upsert_owner(session: Session, entry: OwnerEntry) -> None:
    owner = session.scalars(select(Owner).where(Owner.name == entry.name)).first()
    if owner is None:
        owner = Owner(name=entry.name)
        session.add(owner)
    owner.phone_e164 = entry.phone_e164
    owner.email = entry.email
    session.flush()
    for category in entry.default_for:
        default = session.get(CategoryOwnerDefault, category)
        if default is None:
            session.add(CategoryOwnerDefault(category=category, owner_id=owner.id))
        else:
            default.owner_id = owner.id


def _upsert_staff(session: Session, entry: StaffEntry) -> None:
    staff = session.get(Staff, entry.id)
    if staff is None:
        staff = Staff(id=entry.id)
        session.add(staff)
    staff.name = entry.name
    staff.email = entry.email
    staff.role = entry.role


def _upsert_job(session: Session, entry: JobEntry) -> None:
    job = session.scalars(select(Job).where(Job.name == entry.name)).first()
    if job is None:
        job = Job(name=entry.name)
        session.add(job)
    job.active = entry.active
    existing = {a.alias for a in job.aliases}
    for alias in entry.aliases:
        if alias not in existing:
            job.aliases.append(JobAlias(alias=alias))
            existing.add(alias)


def _upsert_foreman(session: Session, entry: ForemanEntry) -> None:
    owners = set(
        session.scalars(
            select(ForemanPhone.foreman_id).where(ForemanPhone.e164.in_(entry.phones))
        ).all()
    )
    if len(owners) > 1:
        raise ValueError(
            f"Phones of {entry.first_name} {entry.last_name} belong to different foremen"
        )
    foreman = session.get(Foreman, owners.pop()) if owners else None
    if foreman is None:
        foreman = Foreman(first_name=entry.first_name, last_name=entry.last_name)
        session.add(foreman)
    foreman.first_name = entry.first_name
    foreman.last_name = entry.last_name
    foreman.active = entry.active
    existing = {p.e164 for p in foreman.phones}
    for e164 in entry.phones:
        if e164 not in existing:
            foreman.phones.append(ForemanPhone(e164=e164))
            existing.add(e164)
