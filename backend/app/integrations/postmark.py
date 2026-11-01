"""Postmark: send one plain-text email (`POST /email`).

Services depend on the `EmailSender` protocol, so tests use a fake and no Postmark account.
The request/response shape is from memory (postmarkapp.com was unreachable when built);
verify it on staging (ticket #23 L item).
"""

from typing import Protocol

import httpx


class EmailNotSent(Exception):
    """The email was not accepted (not configured, unreachable, or Postmark refused it)."""


class EmailSender(Protocol):
    def send(self, to: str, subject: str, text_body: str) -> str:
        """Send a plain-text email to `to`; return the provider's message id.

        Raises EmailNotSent when the provider did not accept it.
        """
        ...


class PostmarkEmail:
    def __init__(
        self, client: httpx.Client, server_token: str | None, from_address: str | None
    ) -> None:
        self._client = client
        self._token = server_token
        self._from = from_address

    def send(self, to: str, subject: str, text_body: str) -> str:
        if not (self._token and self._from):
            raise EmailNotSent("Postmark is not configured")
        try:
            response = self._client.post(
                "/email",
                json={
                    "From": self._from,
                    "To": to,
                    "Subject": subject,
                    "TextBody": text_body,
                    "MessageStream": "outbound",
                },
                headers={"Accept": "application/json", "X-Postmark-Server-Token": self._token},
            )
        except httpx.HTTPError as exc:
            raise EmailNotSent(f"Postmark not reached ({type(exc).__name__})") from exc
        if response.is_error:
            raise EmailNotSent(f"Postmark answered {response.status_code}")
        try:
            message_id = response.json()["MessageID"]
        except (ValueError, KeyError, TypeError) as exc:
            raise EmailNotSent("Postmark answered without a message id") from exc
        return str(message_id)
