"""Office-wide settings (architecture §5 `settings`, singleton row id = 1, created by #21)."""

from datetime import timedelta

from sqlalchemy.orm import Session

from app.db.models import Settings
from app.domain.sla import UNINFORMED_AFTER


def office_line(session: Session) -> str | None:
    """The Office Line (`settings.office_line_e164`) that Transfers dial; None if not set."""
    row = session.get(Settings, 1)
    return None if row is None else row.office_line_e164


def uninformed_after(session: Session) -> timedelta:
    """The Uninformed threshold (`settings.uninformed_after_min`); 2 h if the row is missing."""
    row = session.get(Settings, 1)
    if row is None:
        return UNINFORMED_AFTER
    return timedelta(minutes=row.uninformed_after_min)
