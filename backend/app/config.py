"""Settings read from the environment (see docs/agents/cloud-sessions.md for local values)."""

import os


def database_url() -> str:
    """SQLAlchemy URL of the app database, e.g. postgresql+psycopg://user:pw@host:5432/db."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url
