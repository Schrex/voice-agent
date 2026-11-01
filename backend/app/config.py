"""Settings read from the environment. Every variable is listed in the root `.env.example`."""

import os


def database_url() -> str:
    """SQLAlchemy URL of the app database, e.g. postgresql+psycopg://user:pw@host:5432/db."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def hook_secret() -> str | None:
    """Shared secret ElevenLabs sends as `X-Hook-Secret` on the call-start webhook.

    None when unset; the webhook then rejects every request (fails closed).
    """
    return os.environ.get("HOOK_SECRET") or None


def office_main_number() -> str:
    """Main office number spoken to unrostered callers (spec J8), inserted as written."""
    number = os.environ.get("OFFICE_MAIN_NUMBER")
    if not number:
        raise RuntimeError("OFFICE_MAIN_NUMBER is not set")
    return number


def app_env() -> str:
    """Deployment name: local, staging or prod. Tags Sentry events."""
    return os.environ.get("APP_ENV") or "local"


def sentry_dsn() -> str | None:
    """Sentry project DSN; unset or empty disables error reporting."""
    return os.environ.get("SENTRY_DSN") or None
