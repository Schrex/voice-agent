"""Time-based flags on Requests (architecture §5: derived, not stored). Pure; `now` is explicit.

Overdue (ticket #22; spec §4, §5 flags, AC9.3): still Recorded after its ack window, which
starts when it was Recorded. `ack_due_at` is stored on the Request when it is Recorded; the
flag itself is derived.

Uninformed (ticket #32; spec §5 flags, AC9.4): Resolved, not marked Foreman Informed, and more
than `UNINFORMED_AFTER` since it was Resolved. Dashboard only (ADR 0002): nothing is sent.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.domain.lifecycle import Status
from app.domain.urgency import Urgency

# Spec §4 "Uninformed threshold: 2 h after Resolved" (placeholder pending the baseline). The
# office's value is `settings.uninformed_after_min` (architecture §5, default 120), read by
# `services.settings.uninformed_after`; this is the default when no settings row exists.
UNINFORMED_AFTER = timedelta(hours=2)


def uninformed_cutoff(now: datetime, after: timedelta = UNINFORMED_AFTER) -> datetime:
    """A Resolved, not-informed Request is Uninformed at `now` iff it was Resolved before this."""
    return now - after


def is_uninformed(
    status: Status,
    *,
    resolved_at: datetime | None,
    foreman_informed_at: datetime | None,
    now: datetime,
    after: timedelta = UNINFORMED_AFTER,
    merged: bool = False,
) -> bool:
    """Resolved, not marked Foreman Informed, and `now > resolved_at + after`.

    A Request merged into another never is: the surviving Request carries the flag (product
    owner decision on #32/#33).
    """
    return (
        not merged
        and status is Status.RESOLVED
        and foreman_informed_at is None
        and resolved_at is not None
        and resolved_at < uninformed_cutoff(now, after)
    )


@dataclass(frozen=True)
class AckWindows:
    """Spec §4 "Ack window" (placeholders pending the baseline). The office's values are
    `settings.ack_window_today_min` / `ack_window_planned_min` (`services.settings.ack_windows`);
    these defaults apply when no settings row exists. Callback Requests are Today."""

    today: timedelta = timedelta(minutes=15)
    planned: timedelta = timedelta(hours=2)


def ack_due_at(
    urgency: Urgency | None, recorded_at: datetime, windows: AckWindows
) -> datetime | None:
    """When a Request Recorded at `recorded_at` must be Acknowledged by.

    Emergency and an unknown Urgency use the Today window (product owner decision on #22 and
    #26), so every Recorded Request can go Overdue.
    """
    if urgency in (Urgency.TODAY, Urgency.EMERGENCY, None):
        return recorded_at + windows.today
    if urgency is Urgency.PLANNED:
        return recorded_at + windows.planned
    return None


def is_overdue(status: Status, *, ack_due_at: datetime | None, now: datetime) -> bool:
    """Still Recorded (not Acknowledged) and `now > ack_due_at`."""
    return status is Status.RECORDED and ack_due_at is not None and now > ack_due_at
