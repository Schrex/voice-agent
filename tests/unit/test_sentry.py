from collections.abc import Iterator
from typing import Any

import pytest
import sentry_sdk
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sentry_sdk.envelope import Envelope
from sentry_sdk.transport import Transport

from app.observability import init_from_env, init_sentry


class CapturingTransport(Transport):
    """Stands in for Sentry's HTTP transport: keeps every event instead of sending it."""

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        super().__init__(options)
        self.events: list[dict[str, Any]] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        event = envelope.get_event()
        if event is not None:
            self.events.append(dict(event))


@pytest.fixture(autouse=True)
def reset_sentry() -> Iterator[None]:
    yield
    sentry_sdk.get_client().close()
    sentry_sdk.get_global_scope().set_client(None)


def test_init_is_a_no_op_without_dsn() -> None:
    assert init_sentry(dsn=None, environment="staging") is False
    assert init_sentry(dsn="", environment="staging") is False
    assert sentry_sdk.get_client().is_active() is False


def test_unhandled_route_error_reaches_sentry() -> None:
    transport = CapturingTransport()
    assert init_sentry(
        dsn="https://public@o0.ingest.sentry.io/0", environment="staging", transport=transport
    )

    app = FastAPI()

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("staging test exception")

    response = TestClient(app, raise_server_exceptions=False).get("/boom")
    sentry_sdk.flush()

    assert response.status_code == 500
    [event] = transport.events
    assert event["environment"] == "staging"
    [exception] = event["exception"]["values"]
    assert exception["type"] == "RuntimeError"
    assert exception["value"] == "staging test exception"


def test_env_without_dsn_leaves_sentry_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENTRY_DSN", "")
    monkeypatch.setenv("APP_ENV", "staging")

    assert init_from_env() is False
    assert sentry_sdk.get_client().is_active() is False


def test_env_with_dsn_tags_events_with_app_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENTRY_DSN", "https://public@o0.ingest.sentry.io/0")
    monkeypatch.setenv("APP_ENV", "staging")

    assert init_from_env() is True
    assert sentry_sdk.get_client().options["environment"] == "staging"
