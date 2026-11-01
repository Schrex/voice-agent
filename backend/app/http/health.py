from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.services.health import db_reachable

router = APIRouter()


@router.get("/healthz")
def healthz(session: Annotated[Session, Depends(get_session)]) -> JSONResponse:
    """Probe for the uptime monitor: 200 when the database answers, 503 when it does not."""
    if db_reachable(session):
        return JSONResponse({"status": "ok", "db": "ok"})
    return JSONResponse({"status": "error", "db": "unreachable"}, status_code=503)
