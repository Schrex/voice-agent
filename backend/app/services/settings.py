"""Office-wide settings (architecture §5 `settings`, singleton row id = 1, created by #21).

Read by the features that use them; the admin edits them (#35).
"""

from datetime import timedelta
from typing import TypedDict

from sqlalchemy.orm import Session

from app.db.models import Settings
from app.domain.sla import UNINFORMED_AFTER, AckWindows


def ack_windows(session: Session) -> AckWindows:
    """The ack windows (`settings.ack_window_today_min` / `ack_window_planned_min`, edited by the
    admin, #35), read when a Request is Recorded to set `ack_due_at` (#22); the spec §4 defaults
    (`domain.sla.AckWindows()`) if the row is missing."""
    row = session.get(Settings, 1)
    if row is None:
        return AckWindows()
    return AckWindows(
        today=timedelta(minutes=row.ack_window_today_min),
        planned=timedelta(minutes=row.ack_window_planned_min),
    )


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


class SettingsChanges(TypedDict, total=False):
    """The settings the admin may change (#35); a key that is absent stays as it is."""

    office_line_e164: str | None
    ack_window_today_min: int
    ack_window_planned_min: int


def office_settings(session: Session) -> Settings:
    """The settings row, created with the architecture §5 defaults if it is missing."""
    row = session.get(Settings, 1)
    if row is None:
        row = Settings(id=1)
        session.add(row)
        session.flush()
        session.refresh(row)
    return row


def update_office_settings(session: Session, changes: SettingsChanges) -> Settings:
    """Apply the admin's changes and commit. Values are validated by the caller."""
    row = office_settings(session)
    if "office_line_e164" in changes:
        row.office_line_e164 = changes["office_line_e164"]
    if "ack_window_today_min" in changes:
        row.ack_window_today_min = changes["ack_window_today_min"]
    if "ack_window_planned_min" in changes:
        row.ack_window_planned_min = changes["ack_window_planned_min"]
    session.commit()
    return row
