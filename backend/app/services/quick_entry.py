"""What the quick-entry form offers a coordinator (spec J7, ticket #30). Read-only."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Foreman, Job
from app.services.owners import OwnerChoice, list_owners


@dataclass(frozen=True)
class Choice:
    id: int
    name: str


@dataclass(frozen=True)
class QuickEntryChoices:
    foremen: list[Choice]
    jobs: list[Choice]
    owners: list[OwnerChoice]


def quick_entry_choices(session: Session) -> QuickEntryChoices:
    """Active Foremen (by last, first name), active Jobs (by name) and every Owner (by name)."""
    foremen = session.scalars(
        select(Foreman).where(Foreman.active).order_by(Foreman.last_name, Foreman.first_name)
    )
    jobs = session.scalars(select(Job).where(Job.active).order_by(Job.name, Job.id))
    return QuickEntryChoices(
        foremen=[Choice(id=f.id, name=f"{f.first_name} {f.last_name}") for f in foremen],
        jobs=[Choice(id=j.id, name=j.name) for j in jobs],
        owners=list_owners(session),
    )
