"""Twilio SMS client against a mocked Twilio (no account): request shape and failures."""

import base64
from urllib.parse import parse_qs

import httpx
import pytest

from app.integrations.twilio_sms import SmsNotSent, TwilioSms

SID = "AC0123456789abcdef0123456789abcdef"


def _sms(handler: httpx.MockTransport, *, from_e164: str | None = "+15855550100") -> TwilioSms:
    client = httpx.Client(base_url="https://api.twilio.com", transport=handler)
    return TwilioSms(client, SID, "token", from_e164)


def test_send_posts_the_message_form_with_basic_auth_and_returns_the_sid() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"sid": "SM123", "status": "queued"})

    sid = _sms(httpx.MockTransport(handle)).send("+15855550199", "Today request R-1000")

    assert sid == "SM123"
    [request] = seen
    assert request.method == "POST"
    assert str(request.url) == f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages.json"
    assert parse_qs(request.content.decode()) == {
        "To": ["+15855550199"],
        "From": ["+15855550100"],
        "Body": ["Today request R-1000"],
    }
    expected = base64.b64encode(f"{SID}:token".encode()).decode()
    assert request.headers["Authorization"] == f"Basic {expected}"


def test_a_twilio_error_is_not_sent() -> None:
    sms = _sms(httpx.MockTransport(lambda r: httpx.Response(400, json={"code": 21211})))

    with pytest.raises(SmsNotSent, match="Twilio answered 400"):
        sms.send("+15855550199", "x")


def test_twilio_unreachable_is_not_sent() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(SmsNotSent, match="not reached"):
        _sms(httpx.MockTransport(handle)).send("+15855550199", "x")


def test_not_configured_is_not_sent_and_calls_nothing() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    with pytest.raises(SmsNotSent, match="not configured"):
        _sms(httpx.MockTransport(handle), from_e164=None).send("+15855550199", "x")
