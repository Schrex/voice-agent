"""ElevenLabs webhook signature check (`ElevenLabs-Signature: t=<unix secs>,v0=<hex>`).

hex = HMAC-SHA256(secret, "<t>.<raw body>"). Same scheme as the ElevenLabs SDK's
`construct_event`, written here because the SDK answers a bad signature with 400 and the
post-call webhook must answer 401 (ticket #27).
"""

import hashlib
import hmac
from datetime import datetime, timedelta

# Deliveries signed longer ago than this are rejected (the SDK's tolerance).
TOLERANCE = timedelta(minutes=30)


def signature_is_valid(raw_body: bytes, header: str | None, secret: str, now: datetime) -> bool:
    if not header or not secret:
        return False
    timestamp = signature = None
    for part in header.split(","):
        part = part.strip()
        if part.startswith("t="):
            timestamp = part[2:]
        elif part.startswith("v0="):
            signature = part
    if timestamp is None or signature is None or not timestamp.isdigit():
        return False
    if int(timestamp) < (now - TOLERANCE).timestamp():
        return False
    digest = hmac.new(secret.encode(), timestamp.encode() + b"." + raw_body, hashlib.sha256)
    return hmac.compare_digest(signature.encode(), b"v0=" + digest.hexdigest().encode())
