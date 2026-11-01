"""Postmark email client against a mocked Postmark (no account): request shape and failures.

The Postmark API shape is from memory (postmarkapp.com was unreachable); verify on staging.
"""

import json

import httpx
import pytest

from app.integrations.postmark import EmailNotSent, PostmarkEmail


def _email(
    handler: httpx.MockTransport,
    *,
    token: str | None = "server-token",
    sender: str | None = "office@example.com",
) -> PostmarkEmail:
    client = httpx.Client(base_url="https://api.postmarkapp.com", transport=handler)
    return PostmarkEmail(client, token, sender)


def test_send_posts_the_email_with_the_server_token_and_returns_the_message_id() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ErrorCode": 0, "Message": "OK", "MessageID": "m-1"})

    message_id = _email(httpx.MockTransport(handle)).send("pat@example.com", "Subject", "Body\n")

    assert message_id == "m-1"
    [request] = seen
    assert request.method == "POST"
    assert str(request.url) == "https://api.postmarkapp.com/email"
    assert request.headers["X-Postmark-Server-Token"] == "server-token"
    assert request.headers["Accept"] == "application/json"
    assert json.loads(request.content) == {
        "From": "office@example.com",
        "To": "pat@example.com",
        "Subject": "Subject",
        "TextBody": "Body\n",
        "MessageStream": "outbound",
    }


def test_a_postmark_error_is_not_sent() -> None:
    email = _email(
        httpx.MockTransport(lambda r: httpx.Response(422, json={"ErrorCode": 300, "Message": "x"}))
    )
    with pytest.raises(EmailNotSent, match="Postmark answered 422"):
        email.send("pat@example.com", "s", "b")


def test_postmark_unreachable_is_not_sent() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(EmailNotSent, match="Postmark not reached"):
        _email(httpx.MockTransport(handle)).send("pat@example.com", "s", "b")


def test_unconfigured_postmark_is_not_sent_and_makes_no_request() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    for email in (
        _email(httpx.MockTransport(handle), token=None),
        _email(httpx.MockTransport(handle), sender=None),
    ):
        with pytest.raises(EmailNotSent, match="Postmark is not configured"):
            email.send("pat@example.com", "s", "b")


def test_an_answer_without_a_message_id_is_not_sent() -> None:
    email = _email(httpx.MockTransport(lambda r: httpx.Response(200, json={"ErrorCode": 0})))
    with pytest.raises(EmailNotSent, match="without a message id"):
        email.send("pat@example.com", "s", "b")
