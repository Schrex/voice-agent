"""Engine and Session wiring. HTTP handlers take a Session via `Depends(get_session)`."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import database_url


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(database_url(), pool_pre_ping=True)


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def new_session() -> Session:
    """A Session on the app database; caller commits and closes (use as a context manager)."""
    return _session_factory()()


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one Session per request, closed afterwards. Tests override it."""
    with new_session() as session:
        yield session
