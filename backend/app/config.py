"""Settings read from the environment (see docs/agents/cloud-sessions.md for local values)."""

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
