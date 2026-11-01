"""Dashboard API auth dependency: 401 without a valid Supabase token, 403 if not staff."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import supabase_jwt_secret
from app.db.models import Staff
from app.db.session import get_session
from app.services.staff import NotAuthenticated, NotStaff, staff_for_token

_bearer = HTTPBearer(auto_error=False)


def current_staff(
    session: Annotated[Session, Depends(get_session)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Staff:
    token = credentials.credentials if credentials else None
    try:
        return staff_for_token(session, token, supabase_jwt_secret())
    except NotAuthenticated as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Not signed in",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except NotStaff as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a staff account") from exc


CurrentStaff = Annotated[Staff, Depends(current_staff)]
