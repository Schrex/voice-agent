"""The SMS sender as a FastAPI dependency; tests override `get_sms_sender` with a fake."""

from functools import cache

import httpx

from app.config import twilio_account_sid, twilio_api_base, twilio_auth_token, twilio_from_e164
from app.integrations.twilio_sms import SmsSender, TwilioSms


@cache
def _twilio_client(base_url: str) -> httpx.Client:
    # A tool call waits on this send; keep a slow Twilio from stalling the call.
    return httpx.Client(base_url=base_url, timeout=httpx.Timeout(5.0, connect=3.0))


def get_sms_sender() -> SmsSender:
    return TwilioSms(
        _twilio_client(twilio_api_base()),
        twilio_account_sid(),
        twilio_auth_token(),
        twilio_from_e164(),
    )
