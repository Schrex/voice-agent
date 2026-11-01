"""Settings read from the environment. Every variable is listed in the root `.env.example`."""

import os


def database_url() -> str:
    """SQLAlchemy URL of the app database, e.g. postgresql+psycopg://user:pw@host:5432/db."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def app_env() -> str:
    """Deployment name: local, staging or prod. Tags Sentry events."""
    return os.environ.get("APP_ENV") or "local"


def sentry_dsn() -> str | None:
    """Sentry project DSN; unset or empty disables error reporting."""
    return os.environ.get("SENTRY_DSN") or None
