"""Incoming-transfer pop-ups on the dashboard (`/api/popups`; spec J5 step 2, AC5.3)."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import AwareDatetime, BaseModel
from sqlalchemy.orm import Session

from app.clock import Clock, get_clock
from app.db.session import get_session
from app.http.auth import CurrentStaff
from app.services.alerts import PopupNotFound, dismiss_popup, open_popups

router = APIRouter(prefix="/api/popups")


class PopupOut(BaseModel):
    id: int
    kind: str  # transfer (emergency from #26)
    text: str  # e.g. "Incoming transfer: Dale Kramer, Route 104 Widening, about: not stated"
    at: str  # UTC, ISO 8601 with "Z"


class PopupsOut(BaseModel):
    popups: list[PopupOut]


def _utc(at: datetime) -> str:
    return at.astimezone(UTC).isoformat().replace("+00:00", "Z")


@router.get("")
def popups(
    staff: CurrentStaff,
    session: Annotated[Session, Depends(get_session)],
    since: AwareDatetime | None = None,
) -> PopupsOut:
    """Pop-ups nobody has dismissed, newest first; with `since`, only those raised after it."""
    return PopupsOut(
        popups=[
            PopupOut(id=p.id, kind=p.kind, text=p.text, at=_utc(p.at))
            for p in open_popups(session, since)
        ]
    )


@router.post("/{popup_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
def dismiss(
    popup_id: int,
    staff: CurrentStaff,
    session: Annotated[Session, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> Response:
    """Hide the pop-up for every Coordinator (`alerts.seen_at`). 404 if it is not a pop-up."""
    try:
        dismiss_popup(session, popup_id, now=clock())
    except PopupNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such pop-up") from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
