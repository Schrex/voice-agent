"""Error reporting: Sentry runs only where SENTRY_DSN is set (staging, prod), not locally or in CI.

`uv run python -m app.observability` sends one test exception to prove a DSN works
(docs/staging.md).
"""

import sentry_sdk
from sentry_sdk.transport import Transport

from app import config


def init_sentry(dsn: str | None, environment: str, transport: Transport | None = None) -> bool:
    """Start the Sentry SDK; returns False (and does nothing) when no DSN is given.

    The SDK's default integrations report unhandled FastAPI/Starlette exceptions.
    `transport` replaces the HTTP sender (tests).
    """
    if not dsn:
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        transport=transport,
        traces_sample_rate=0.0,
    )
    return True


def init_from_env() -> bool:
    return init_sentry(config.sentry_dsn(), config.app_env())


def _send_test_exception() -> None:
    if not init_from_env():
        raise SystemExit("SENTRY_DSN is not set")
    try:
        raise RuntimeError(f"Sentry test exception from {config.app_env()}")
    except RuntimeError as exc:
        event_id = sentry_sdk.capture_exception(exc)
    sentry_sdk.flush()
    print(f"Sent test exception to Sentry, event id {event_id}")


if __name__ == "__main__":
    _send_test_exception()
