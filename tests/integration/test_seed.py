from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Base, Foreman, ForemanPhone, Job, JobAlias
from app.services.roster import load_roster_file, seed_roster

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
