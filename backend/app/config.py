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


def elevenlabs_webhook_secret() -> str | None:
    """HMAC secret ElevenLabs signs the post-call webhook with (`ElevenLabs-Signature`).

    None when unset; every post-call delivery is then rejected (fails closed).
    """
    return os.environ.get("ELEVENLABS_WEBHOOK_SECRET") or None


def elevenlabs_api_key() -> str | None:
    """ElevenLabs API key; the backend uses it to stream call recordings to the dashboard.

    None when unset; recordings then cannot be played (502). Nothing else depends on it.
    """
    return os.environ.get("ELEVENLABS_API_KEY") or None


def elevenlabs_api_base() -> str:
    """ElevenLabs API base URL; `ELEVENLABS_API_BASE` overrides it (e2e stub)."""
    return os.environ.get("ELEVENLABS_API_BASE") or "https://api.elevenlabs.io"


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


def twilio_account_sid() -> str | None:
    """Twilio account SID for alert SMS. Unset: every alert SMS is recorded as failed."""
    return os.environ.get("TWILIO_ACCOUNT_SID") or None


def twilio_auth_token() -> str | None:
    """Twilio auth token for alert SMS. Unset: every alert SMS is recorded as failed."""
    return os.environ.get("TWILIO_AUTH_TOKEN") or None


def twilio_from_e164() -> str | None:
    """Number alert SMS are sent from (E.164). Unset: every alert SMS is recorded as failed."""
    return os.environ.get("TWILIO_FROM_E164") or None


def twilio_api_base() -> str:
    """Twilio API base URL; `TWILIO_API_BASE` overrides it (tests, stubs)."""
    return os.environ.get("TWILIO_API_BASE") or "https://api.twilio.com"


def postmark_server_token() -> str | None:
    """Postmark server API token for the end-of-day email. Unset: each email is recorded failed."""
    return os.environ.get("POSTMARK_SERVER_TOKEN") or None


def postmark_from() -> str | None:
    """Sender address of the end-of-day email (a verified Postmark sender). Unset: not sent."""
    return os.environ.get("POSTMARK_FROM") or None


def postmark_api_base() -> str:
    """Postmark API base URL; `POSTMARK_API_BASE` overrides it (tests, stubs)."""
    return os.environ.get("POSTMARK_API_BASE") or "https://api.postmarkapp.com"


_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def scheduler_enabled() -> bool:
    """Whether the app runs its scheduled jobs (architecture §6) while up. Default true (prod).

    `SCHEDULER_ENABLED=false` turns them off where a clock-driven job would interfere, e.g. the
    Playwright backend (the 17:00 end-of-day email). Any other value is a typo: refuse to start.
    """
    raw = (os.environ.get("SCHEDULER_ENABLED") or "true").strip().lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    raise RuntimeError(f"SCHEDULER_ENABLED must be true or false, not {raw!r}")


def frontend_dist() -> Path:
    """Built dashboard (`npm run build` output) served at `/`; defaults to `frontend/dist`."""
    configured = os.environ.get("FRONTEND_DIST")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"
