"""Admin upkeep of the Roster and the Job list (spec §3 Admin role, ticket #34).

Foremen and Jobs are never deleted: they are deactivated (`active = false`), because Calls and
Requests point at them. A deactivated Foreman's numbers are refused at call start; a deactivated
Job is not offered to the agent. Phone numbers and Job aliases can be removed outright.

Each function commits its own change. A rule violation raises `NotFound` or `Conflict` and
writes nothing.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Foreman, ForemanPhone, Job, JobAlias


class NotFound(Exception):
    """No such Foreman, Job, phone or alias (or it belongs to another Foreman/Job)."""


class Conflict(Exception):
    """The change would break a uniqueness rule; the message says which."""


# --- Foremen -----------------------------------------------------------------------------


def list_foremen(session: Session) -> list[Foreman]:
    return list(
        session.scalars(
            select(Foreman)
            .options(selectinload(Foreman.phones))
            .order_by(Foreman.last_name, Foreman.first_name, Foreman.id)
        )
    )


def add_foreman(session: Session, *, first_name: str, last_name: str, phones: list[str]) -> Foreman:
    _ensure_numbers_free(session, phones)
    foreman = Foreman(first_name=first_name, last_name=last_name, active=True)
    foreman.phones = [ForemanPhone(e164=e164) for e164 in dict.fromkeys(phones)]
    session.add(foreman)
    session.commit()
    return foreman


def update_foreman(
    session: Session,
    foreman_id: int,
    *,
    first_name: str | None = None,
    last_name: str | None = None,
    active: bool | None = None,
) -> Foreman:
    foreman = _foreman(session, foreman_id)
    if first_name is not None:
        foreman.first_name = first_name
    if last_name is not None:
        foreman.last_name = last_name
    if active is not None:
        foreman.active = active
    session.commit()
    return foreman


def add_phone(session: Session, foreman_id: int, e164: str) -> Foreman:
    foreman = _foreman(session, foreman_id)
    _ensure_numbers_free(session, [e164])
    foreman.phones.append(ForemanPhone(e164=e164))
    session.commit()
    return foreman


def remove_phone(session: Session, foreman_id: int, phone_id: int) -> Foreman:
    foreman = _foreman(session, foreman_id)
    phone = next((p for p in foreman.phones if p.id == phone_id), None)
    if phone is None:
        raise NotFound
    foreman.phones.remove(phone)
    session.delete(phone)
    session.commit()
    return foreman


def _foreman(session: Session, foreman_id: int) -> Foreman:
    foreman = session.get(Foreman, foreman_id)
    if foreman is None:
        raise NotFound
    return foreman


def _ensure_numbers_free(session: Session, numbers: list[str]) -> None:
    """A number identifies one Foreman, so it may be on the roster only once."""
    taken = session.scalars(select(ForemanPhone.e164).where(ForemanPhone.e164.in_(numbers))).all()
    if taken:
        raise Conflict(f"{taken[0]} is already on the roster.")


# --- Jobs --------------------------------------------------------------------------------


def list_jobs(session: Session) -> list[Job]:
    return list(
        session.scalars(select(Job).options(selectinload(Job.aliases)).order_by(Job.name, Job.id))
    )


def add_job(session: Session, *, name: str, aliases: list[str]) -> Job:
    _ensure_name_free(session, name)
    job = Job(name=name, active=True)
    job.aliases = [JobAlias(alias=alias) for alias in dict.fromkeys(aliases)]
    session.add(job)
    session.commit()
    return job


def update_job(
    session: Session, job_id: int, *, name: str | None = None, active: bool | None = None
) -> Job:
    job = _job(session, job_id)
    if name is not None and name != job.name:
        _ensure_name_free(session, name)
        job.name = name
    if active is not None:
        job.active = active
    session.commit()
    return job


def add_alias(session: Session, job_id: int, alias: str) -> Job:
    job = _job(session, job_id)
    if alias in {a.alias for a in job.aliases}:
        raise Conflict(f"{job.name} already has the alias {alias}.")
    job.aliases.append(JobAlias(alias=alias))
    session.commit()
    return job


def remove_alias(session: Session, job_id: int, alias_id: int) -> Job:
    job = _job(session, job_id)
    alias = next((a for a in job.aliases if a.id == alias_id), None)
    if alias is None:
        raise NotFound
    job.aliases.remove(alias)
    session.delete(alias)
    session.commit()
    return job


def _job(session: Session, job_id: int) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise NotFound
    return job


def _ensure_name_free(session: Session, name: str) -> None:
    """Job names are what the agent reads back, so two Jobs may not share one."""
    if session.scalar(select(Job.id).where(Job.name == name)) is not None:
        raise Conflict(f"A Job named {name} already exists.")
