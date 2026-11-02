"""Who is calling the dashboard API: Supabase access token -> Staff row.

The token is verified here, never trusted as-is (ADR 0005). Supabase signs access tokens one of
two ways, and the token's header says which:

- HS256 with the project's shared JWT secret (older projects; `SUPABASE_JWT_SECRET`);
- ES256 or RS256 with an asymmetric signing key, whose public half Supabase publishes at
  `<project URL>/auth/v1/.well-known/jwks.json` (newer projects; `SUPABASE_URL`).

Each algorithm is checked only against its own kind of key, so a token can never pick the key it
is checked with. `sub` is the auth user id, which is `staff.id`.
"""

import logging
import uuid
from dataclasses import dataclass
from functools import lru_cache

import jwt
from sqlalchemy.orm import Session

from app.db.models import Staff

log = logging.getLogger(__name__)

AUDIENCE = "authenticated"
ASYMMETRIC = ("ES256", "RS256")


class NotAuthenticated(Exception):
    """No token, or a token that is malformed, forged, expired or not for this project."""


class NotStaff(Exception):
    """A valid Supabase user who is not in the staff table."""


@dataclass(frozen=True)
class TokenKeys:
    """What the backend can check a token with; either may be absent, not both."""

    jwt_secret: str | None
    jwks_url: str | None


@lru_cache(maxsize=4)
def _jwks_client(url: str) -> jwt.PyJWKClient:
    # One client per URL for the process: it caches the keys and refetches on an unknown `kid`.
    return jwt.PyJWKClient(url, cache_keys=True, lifespan=3600, timeout=5)


def staff_for_token(session: Session, token: str | None, keys: TokenKeys) -> Staff:
    user_id = _verified_user_id(token, keys)
    staff = session.get(Staff, user_id)
    if staff is None:
        raise NotStaff
    return staff


def _verified_user_id(token: str | None, keys: TokenKeys) -> uuid.UUID:
    if not token:
        raise NotAuthenticated
    try:
        algorithm = jwt.get_unverified_header(token).get("alg")
        key: object
        if algorithm == "HS256" and keys.jwt_secret:
            key = keys.jwt_secret
        elif algorithm in ASYMMETRIC and keys.jwks_url:
            key = _jwks_client(keys.jwks_url).get_signing_key_from_jwt(token).key
        else:
            raise NotAuthenticated
        claims = jwt.decode(
            token,
            key,  # type: ignore[arg-type]
            algorithms=[algorithm],
            audience=AUDIENCE,
            options={"require": ["exp", "sub", "aud"]},
        )
        return uuid.UUID(str(claims["sub"]))
    except jwt.PyJWKClientConnectionError as exc:
        # Supabase's key endpoint is unreachable: every new-key login fails until it is back.
        log.exception("supabase_jwks_unreachable")
        raise NotAuthenticated from exc
    except (jwt.InvalidTokenError, jwt.PyJWKClientError, ValueError) as exc:
        raise NotAuthenticated from exc
