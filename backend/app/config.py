"""Settings read from the environment. Every variable is listed in the root `.env.example`."""

import os
from pathlib import Path


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


def tool_secret() -> str | None:
    """Shared secret ElevenLabs sends as `X-Tool-Secret` on every `/tools/*` call.

    None when unset; every tool call is then rejected (fails closed).
    """
    return os.environ.get("TOOL_SECRET") or None


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


def supabase_jwt_secret() -> str:
    """Supabase project's JWT secret (HS256); the backend verifies dashboard tokens with it."""
    secret = os.environ.get("SUPABASE_JWT_SECRET")
    if not secret:
        raise RuntimeError("SUPABASE_JWT_SECRET is not set")
    return secret


def frontend_dist() -> Path:
    """Built dashboard (`npm run build` output) served at `/`; defaults to `frontend/dist`."""
    configured = os.environ.get("FRONTEND_DIST")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"
