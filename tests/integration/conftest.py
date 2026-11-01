"""Shared fixtures for I-tests (real Postgres).

Pattern every later ticket follows:
- `TEST_DATABASE_URL` names a database the tests own; it is wiped and migrated once per run.
- `db_session`: a Session bound to one outer transaction that is rolled back after the test,
  so code under test may `commit()` freely without leaking rows into the next test.
- `client`: a TestClient whose `get_session` dependency yields `db_session`.
"""

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from app.db.migrate import upgrade
from app.db.session import get_session
from app.main import app


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail("TEST_DATABASE_URL is not set; I-tests need a disposable Postgres database.")
    return url


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    """Fresh schema: drop everything in `public`, then `alembic upgrade head`."""
    engine = create_engine(database_url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    upgrade(database_url, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(engine: Engine) -> Iterator[Session]:
    connection = engine.connect()
    outer = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        connection.close()


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_session] = lambda: db_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
