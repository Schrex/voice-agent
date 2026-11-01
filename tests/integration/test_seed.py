import uuid
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    CategoryOwnerDefault,
    DutyRoster,
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


def test_seed_loads_staff_phones_and_the_duty_roster(db_session: Session) -> None:
    pat, sam = uuid.uuid4(), uuid.uuid4()
    roster = RosterFile.model_validate(
        {
            "staff": [
                {
                    "id": str(pat),
                    "name": "Pat Lee",
                    "email": "pat@example.com",
                    "role": "coordinator",
                    "phone_e164": "+15855550199",
                },
                {"id": str(sam), "name": "Sam Ortiz", "email": "s@example.com", "role": "admin"},
            ],
            "duty": [
                {"date": "2026-11-02", "on_duty": str(pat), "backup": str(sam)},
                {"date": "2026-11-03", "on_duty": str(sam)},
            ],
        }
    )
    seed_roster(db_session, roster)
    seed_roster(db_session, roster)

    assert db_session.get_one(Staff, pat).phone_e164 == "+15855550199"
    assert db_session.get_one(Staff, sam).phone_e164 is None
    duty = db_session.scalars(select(DutyRoster).order_by(DutyRoster.day)).all()
    assert [(d.day, d.on_duty_staff_id, d.backup_staff_id) for d in duty] == [
        (date(2026, 11, 2), pat, sam),
        (date(2026, 11, 3), sam, None),
    ]


def test_seed_rejects_a_duty_day_naming_unknown_staff() -> None:
    with pytest.raises(ValidationError):
        RosterFile.model_validate({"duty": [{"date": "2026-11-02", "on_duty": str(uuid.uuid4())}]})


def test_seed_rejects_a_staff_phone_not_in_e164() -> None:
    entry = {
        "id": str(uuid.uuid4()),
        "name": "X",
        "email": "x@example.com",
        "role": "coordinator",
        "phone_e164": "585-555-0199",
    }
    with pytest.raises(ValidationError):
        RosterFile.model_validate({"staff": [entry]})


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
