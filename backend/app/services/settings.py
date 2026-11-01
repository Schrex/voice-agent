"""Office-wide settings (architecture §5 `settings`, singleton row id = 1, created by #21).

Read by the features that use them; the admin edits them (#35).
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import TypedDict

from sqlalchemy.orm import Session

from app.db.models import Settings
from app.domain.sla import UNINFORMED_AFTER

# Spec §4 "Ack window — Today / Callback 15 min" and "Ack window — Planned 2 h" (placeholders
# pending the baseline); the defaults when no settings row exists.
ACK_WINDOW_TODAY = timedelta(minutes=15)
ACK_WINDOW_PLANNED = timedelta(hours=2)


@dataclass(frozen=True)
class AckWindows:
    """How long a Recorded Request may wait to be Acknowledged before it is Overdue."""

    today: timedelta
    planned: timedelta


def uninformed_after(session: Session) -> timedelta:
    """The Uninformed threshold (`settings.uninformed_after_min`); 2 h if the row is missing."""
    row = session.get(Settings, 1)
    if row is None:
        return UNINFORMED_AFTER
    return timedelta(minutes=row.uninformed_after_min)


def ack_windows(session: Session) -> AckWindows:
    """The office's acknowledgment windows (`settings.ack_window_*_min`)."""
    row = session.get(Settings, 1)
    if row is None:
        return AckWindows(today=ACK_WINDOW_TODAY, planned=ACK_WINDOW_PLANNED)
    return AckWindows(
        today=timedelta(minutes=row.ack_window_today_min),
        planned=timedelta(minutes=row.ack_window_planned_min),
    )


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
