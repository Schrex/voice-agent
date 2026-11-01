"""Office-wide settings (architecture §5 `settings`, singleton row id = 1, created by #21)."""

from datetime import timedelta

from sqlalchemy.orm import Session

from app.db.models import Settings
from app.domain.sla import UNINFORMED_AFTER


def uninformed_after(session: Session) -> timedelta:
    """The Uninformed threshold (`settings.uninformed_after_min`); 2 h if the row is missing."""
    row = session.get(Settings, 1)
    if row is None:
        return UNINFORMED_AFTER
    return timedelta(minutes=row.uninformed_after_min)
