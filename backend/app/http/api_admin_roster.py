"""Admin API for the Roster and Job list: `/api/admin/foremen`, `/api/admin/jobs` (#34).

Open to every staff member (one Staff role, ADR 0006). Foremen and Jobs have no DELETE: they
are deactivated with `PATCH {"active": false}`.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, StringConstraints
from sqlalchemy.orm import Session

from app.db.models import Foreman, Job
from app.db.session import get_session
from app.http.auth import current_staff
from app.services import roster_admin
from app.services.roster_admin import Conflict, NotFound

router = APIRouter(prefix="/api/admin", dependencies=[Depends(current_staff)])

DbSession = Annotated[Session, Depends(get_session)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
JobName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
E164 = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\+[1-9][0-9]{1,14}$")]


@contextmanager
def _http_errors() -> Iterator[None]:
    try:
        yield
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found") from exc
    except Conflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


# --- Foremen -----------------------------------------------------------------------------


class PhoneOut(BaseModel):
    id: int
    e164: str


class ForemanOut(BaseModel):
    id: int
    first_name: str
    last_name: str
    active: bool
    phones: list[PhoneOut]

    @classmethod
    def of(cls, foreman: Foreman) -> "ForemanOut":
        return cls(
            id=foreman.id,
            first_name=foreman.first_name,
            last_name=foreman.last_name,
            active=foreman.active,
            phones=[
                PhoneOut(id=p.id, e164=p.e164) for p in sorted(foreman.phones, key=lambda p: p.id)
            ],
        )


class ForemanIn(BaseModel):
    first_name: Name
    last_name: Name
    phones: list[E164] = []


class ForemanPatch(BaseModel):
    first_name: Name | None = None
    last_name: Name | None = None
    active: bool | None = None


class PhoneIn(BaseModel):
    e164: E164


@router.get("/foremen")
def list_foremen(session: DbSession) -> list[ForemanOut]:
    return [ForemanOut.of(f) for f in roster_admin.list_foremen(session)]


@router.post("/foremen", status_code=status.HTTP_201_CREATED)
def add_foreman(body: ForemanIn, session: DbSession) -> ForemanOut:
    with _http_errors():
        foreman = roster_admin.add_foreman(
            session, first_name=body.first_name, last_name=body.last_name, phones=body.phones
        )
    return ForemanOut.of(foreman)


@router.patch("/foremen/{foreman_id}")
def update_foreman(foreman_id: int, body: ForemanPatch, session: DbSession) -> ForemanOut:
    with _http_errors():
        foreman = roster_admin.update_foreman(
            session,
            foreman_id,
            first_name=body.first_name,
            last_name=body.last_name,
            active=body.active,
        )
    return ForemanOut.of(foreman)


@router.post("/foremen/{foreman_id}/phones", status_code=status.HTTP_201_CREATED)
def add_phone(foreman_id: int, body: PhoneIn, session: DbSession) -> ForemanOut:
    with _http_errors():
        foreman = roster_admin.add_phone(session, foreman_id, body.e164)
    return ForemanOut.of(foreman)


@router.delete("/foremen/{foreman_id}/phones/{phone_id}")
def remove_phone(foreman_id: int, phone_id: int, session: DbSession) -> ForemanOut:
    with _http_errors():
        foreman = roster_admin.remove_phone(session, foreman_id, phone_id)
    return ForemanOut.of(foreman)


# --- Jobs --------------------------------------------------------------------------------


class AliasOut(BaseModel):
    id: int
    alias: str


class JobOut(BaseModel):
    id: int
    name: str
    active: bool
    aliases: list[AliasOut]

    @classmethod
    def of(cls, job: Job) -> "JobOut":
        return cls(
            id=job.id,
            name=job.name,
            active=job.active,
            aliases=[
                AliasOut(id=a.id, alias=a.alias) for a in sorted(job.aliases, key=lambda a: a.id)
            ],
        )


class JobIn(BaseModel):
    name: JobName
    aliases: list[JobName] = []


class JobPatch(BaseModel):
    name: JobName | None = None
    active: bool | None = None


class AliasIn(BaseModel):
    alias: JobName


@router.get("/jobs")
def list_jobs(session: DbSession) -> list[JobOut]:
    return [JobOut.of(j) for j in roster_admin.list_jobs(session)]


@router.post("/jobs", status_code=status.HTTP_201_CREATED)
def add_job(body: JobIn, session: DbSession) -> JobOut:
    with _http_errors():
        job = roster_admin.add_job(session, name=body.name, aliases=body.aliases)
    return JobOut.of(job)


@router.patch("/jobs/{job_id}")
def update_job(job_id: int, body: JobPatch, session: DbSession) -> JobOut:
    with _http_errors():
        job = roster_admin.update_job(session, job_id, name=body.name, active=body.active)
    return JobOut.of(job)


@router.post("/jobs/{job_id}/aliases", status_code=status.HTTP_201_CREATED)
def add_alias(job_id: int, body: AliasIn, session: DbSession) -> JobOut:
    with _http_errors():
        job = roster_admin.add_alias(session, job_id, body.alias)
    return JobOut.of(job)


@router.delete("/jobs/{job_id}/aliases/{alias_id}")
def remove_alias(job_id: int, alias_id: int, session: DbSession) -> JobOut:
    with _http_errors():
        job = roster_admin.remove_alias(session, job_id, alias_id)
    return JobOut.of(job)
