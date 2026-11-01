import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    CategoryOwnerDefault,
    Foreman,
    ForemanPhone,
    Job,
    JobAlias,
    Owner,
    Staff,
)
from app.services.roster import RosterFile, load_roster_file, seed_roster

SAMPLE = Path(__file__).resolve().parents[2] / "backend" / "seed" / "sample_roster.json"


def _counts(session: Session) -> dict[str, int]:
    models: list[type[Base]] = [Foreman, ForemanPhone, Job, JobAlias]
    return {
        m.__tablename__: session.scalar(select(func.count()).select_from(m)) or 0 for m in models
    }


def test_seed_loads_the_sample_roster(db_session: Session) -> None:
    seed_roster(db_session, load_roster_file(SAMPLE))

    assert _counts(db_session) == {
        "foremen": 3,
        "foreman_phones": 4,
        "jobs": 3,
        "job_aliases": 4,
    }
    route_104 = db_session.scalars(select(Job).where(Job.name == "Route 104 Widening")).one()
    assert sorted(a.alias for a in route_104.aliases) == ["104 job", "Route 104"]


def test_seed_is_idempotent(db_session: Session) -> None:
    roster = load_roster_file(SAMPLE)
    seed_roster(db_session, roster)
    first = _counts(db_session)

    seed_roster(db_session, roster)

    assert _counts(db_session) == first


def test_seed_upserts_staff_by_supabase_user_id(db_session: Session) -> None:
    user_id = uuid.UUID("7d0b3c1e-2f4a-4b6c-9d8e-0f1a2b3c4d5e")
    entry = {"id": str(user_id), "name": "Pat Lee", "email": "pat@example.com", "role": "admin"}
    seed_roster(db_session, RosterFile.model_validate({"staff": [entry]}))
    seed_roster(
        db_session, RosterFile.model_validate({"staff": [{**entry, "role": "coordinator"}]})
    )

    staff = db_session.scalars(select(Staff)).all()
    assert [(s.id, s.name, s.role) for s in staff] == [(user_id, "Pat Lee", "coordinator")]


def test_seed_rejects_unknown_staff_role() -> None:
    entry = {"id": str(uuid.uuid4()), "name": "X", "email": "x@example.com", "role": "owner"}
    with pytest.raises(ValidationError):
        RosterFile.model_validate({"staff": [entry]})


def test_seed_upserts_owners_by_name_with_their_default_categories(db_session: Session) -> None:
    seed_roster(
        db_session,
        RosterFile.model_validate(
            {
                "owners": [
                    {"name": "Dispatch", "default_for": ["Trucking", "Material"]},
                    {"name": "Shop", "default_for": ["Equipment Repair"]},
                ]
            }
        ),
    )
    seed_roster(
        db_session,
        RosterFile.model_validate(
            {
                "owners": [
                    {"name": "Dispatch", "phone_e164": "+15855550150", "default_for": ["Trucking"]},
                    {"name": "Shop", "default_for": ["Equipment Repair", "Material"]},
                ]
            }
        ),
    )

    owners = {o.name: o for o in db_session.scalars(select(Owner)).all()}
    assert sorted(owners) == ["Dispatch", "Shop"]
    assert owners["Dispatch"].phone_e164 == "+15855550150"
    defaults = {
        d.category: d.owner_id for d in db_session.scalars(select(CategoryOwnerDefault)).all()
    }
    assert defaults == {
        "Trucking": owners["Dispatch"].id,
        "Material": owners["Shop"].id,
        "Equipment Repair": owners["Shop"].id,
    }


def test_seed_rejects_an_owner_default_for_an_unknown_category() -> None:
    with pytest.raises(ValidationError):
        RosterFile.model_validate({"owners": [{"name": "Dispatch", "default_for": ["Gravel"]}]})


def test_seed_rejects_a_category_defaulted_to_two_owners() -> None:
    with pytest.raises(ValidationError):
        RosterFile.model_validate(
            {
                "owners": [
                    {"name": "Dispatch", "default_for": ["Trucking"]},
                    {"name": "Shop", "default_for": ["Trucking"]},
                ]
            }
        )
