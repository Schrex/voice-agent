"""Office-wide settings (architecture §5 `settings`, singleton row id = 1, created by #21)."""

from datetime import timedelta

from sqlalchemy.orm import Session

from app.db.models import Settings
from app.domain.sla import UNINFORMED_AFTER, AckWindows


def ack_windows(session: Session) -> AckWindows:
    """The ack windows (`settings.ack_window_today_min` / `ack_window_planned_min`); the spec
    §4 defaults if the row is missing."""
    row = session.get(Settings, 1)
    if row is None:
        return AckWindows()
    return AckWindows(
        today=timedelta(minutes=row.ack_window_today_min),
        planned=timedelta(minutes=row.ack_window_planned_min),
    )


def uninformed_after(session: Session) -> timedelta:
    """The Uninformed threshold (`settings.uninformed_after_min`); 2 h if the row is missing."""
    row = session.get(Settings, 1)
    if row is None:
        return UNINFORMED_AFTER
    return timedelta(minutes=row.uninformed_after_min)
