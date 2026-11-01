"""Who is calling the dashboard API: Supabase access token -> Staff row.

The token is verified here, never trusted as-is (ADR 0005). Supabase signs access tokens with
the project's JWT secret (HS256); `sub` is the auth user id, which is `staff.id`.
"""

import uuid

import jwt
from sqlalchemy.orm import Session

from app.db.models import Staff

AUDIENCE = "authenticated"


class NotAuthenticated(Exception):
    """No token, or a token that is malformed, forged, expired or not for this project."""


class NotStaff(Exception):
    """A valid Supabase user who is not in the staff table."""


def staff_for_token(session: Session, token: str | None, secret: str) -> Staff:
    user_id = _verified_user_id(token, secret)
    staff = session.get(Staff, user_id)
    if staff is None:
        raise NotStaff
    return staff


def _verified_user_id(token: str | None, secret: str) -> uuid.UUID:
    if not token:
        raise NotAuthenticated
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=AUDIENCE,
            options={"require": ["exp", "sub", "aud"]},
        )
        return uuid.UUID(str(claims["sub"]))
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise NotAuthenticated from exc
