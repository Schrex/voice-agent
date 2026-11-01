"""Time-based flags on Requests (architecture §5: derived, not stored). Pure; `now` is explicit.

Uninformed (ticket #32; spec §5 flags, AC9.4): Resolved, not marked Foreman Informed, and more
than `UNINFORMED_AFTER` since it was Resolved. Dashboard only (ADR 0002): nothing is sent.
"""

from datetime import datetime, timedelta

from app.domain.lifecycle import Status

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
) -> bool:
    """Resolved, not marked Foreman Informed, and `now > resolved_at + after`."""
    return (
        status is Status.RESOLVED
        and foreman_informed_at is None
        and resolved_at is not None
        and resolved_at < uninformed_cutoff(now, after)
    )
