"""Alerts on the dashboard (`/api/alerts/*`): alerts that could not be sent."""

from datetime import UTC
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.http.auth import CurrentStaff
from app.services.alerts import failed_alerts

router = APIRouter(prefix="/api/alerts")


class FailedAlertOut(BaseModel):
    ref: str | None
    kind: str  # today_new, ...
    channel: str  # sms | email | popup
    at: str  # when it was attempted; UTC, ISO 8601 with "Z"
    detail: str | None  # why it was not sent


class FailedAlertsOut(BaseModel):
    alerts: list[FailedAlertOut]


@router.get("/failed")
def failed(
    staff: CurrentStaff, session: Annotated[Session, Depends(get_session)]
) -> FailedAlertsOut:
    """Alerts not sent for Requests that are still open, newest first."""
    return FailedAlertsOut(
        alerts=[
            FailedAlertOut(
                ref=a.ref,
                kind=a.kind,
                channel=a.channel,
                at=a.at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                detail=a.detail,
            )
            for a in failed_alerts(session)
        ]
    )
