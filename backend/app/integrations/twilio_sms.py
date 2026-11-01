"""Twilio Messaging: send one SMS (`POST /2010-04-01/Accounts/{sid}/Messages.json`).

Services depend on the `SmsSender` protocol, so tests use a fake and no Twilio account.
"""

from typing import Protocol
from urllib.parse import quote

import httpx


class SmsNotSent(Exception):
    """The SMS was not accepted (not configured, unreachable, or Twilio refused it)."""


class SmsSender(Protocol):
    def send(self, to: str, body: str) -> str:
        """Send `body` to the E.164 number `to`; return the provider's message id.

        Raises SmsNotSent when the provider did not accept it.
        """
        ...


class TwilioSms:
    def __init__(
        self,
        client: httpx.Client,
        account_sid: str | None,
        auth_token: str | None,
        from_e164: str | None,
    ) -> None:
        self._client = client
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._from = from_e164

    def send(self, to: str, body: str) -> str:
        if not (self._account_sid and self._auth_token and self._from):
            raise SmsNotSent("Twilio is not configured")
        try:
            response = self._client.post(
                f"/2010-04-01/Accounts/{quote(self._account_sid, safe='')}/Messages.json",
                data={"To": to, "From": self._from, "Body": body},
                auth=(self._account_sid, self._auth_token),
            )
        except httpx.HTTPError as exc:
            raise SmsNotSent(f"Twilio not reached ({type(exc).__name__})") from exc
        if response.is_error:
            raise SmsNotSent(f"Twilio answered {response.status_code}")
        try:
            sid = response.json()["sid"]
        except (ValueError, KeyError, TypeError) as exc:
            raise SmsNotSent("Twilio answered without a message id") from exc
        return str(sid)
