from sqlalchemy import Engine, inspect

from app.db.migrate import downgrade, upgrade

ALL_TABLES = {
    "foremen",
    "foreman_phones",
    "jobs",
    "job_aliases",
    "calls",
    "requests",
    "request_events",
    "call_requests",
    "staff",
}


def _tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names()) - {"alembic_version"}


def test_migration_applies_on_empty_db_and_rolls_back_cleanly(
    engine: Engine, database_url: str
) -> None:
    downgrade(database_url, "base")
    assert _tables(engine) == set()

    upgrade(database_url, "head")
    assert _tables(engine) == ALL_TABLES

    downgrade(database_url, "base")
    assert _tables(engine) == set()

    upgrade(database_url, "head")  # leave the session-scoped schema as other tests expect it
