"""Roster and job list loading (seed). Idempotent: re-running a file changes nothing.

Matching keys: a Job by its name, a Foreman by any of their phone numbers (numbers are unique).
Rows are created or updated from the file; nothing absent from the file is removed.
"""

import json
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Foreman, ForemanPhone, Job, JobAlias


class JobEntry(BaseModel):
    name: str = Field(min_length=1)
    active: bool = True
    aliases: list[str] = []


class ForemanEntry(BaseModel):
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    active: bool = True
    phones: list[str] = Field(min_length=1)


class RosterFile(BaseModel):
    jobs: list[JobEntry] = []
    foremen: list[ForemanEntry] = []


def load_roster_file(path: Path) -> RosterFile:
    return RosterFile.model_validate(json.loads(path.read_text()))


def seed_roster(session: Session, roster: RosterFile) -> None:
    """Upsert jobs (with aliases) and foremen (with phones), then commit."""
    for job_entry in roster.jobs:
        _upsert_job(session, job_entry)
    for foreman_entry in roster.foremen:
        _upsert_foreman(session, foreman_entry)
    session.commit()


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
