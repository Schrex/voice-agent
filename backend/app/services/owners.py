"""Owners as the dashboard offers them (ticket #11). Maintaining them is the admin's (#35)."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Owner


@dataclass(frozen=True)
class OwnerChoice:
    id: int
    name: str


def list_owners(session: Session) -> list[OwnerChoice]:
    """Every Owner, sorted by name."""
    rows = session.execute(select(Owner.id, Owner.name).order_by(Owner.name, Owner.id))
    return [OwnerChoice(id=owner_id, name=name) for owner_id, name in rows]
