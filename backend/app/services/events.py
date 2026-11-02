"""The `request_events` audit row every Request write adds in its own transaction (AGENTS.md).

Services build events only through these helpers; the caller commits.
"""

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models import Request, RequestEvent


def add_event(
    session: Session,
    request: Request,
    *,
    actor_type: str,
    actor_id: str | None,
    now: datetime,
    kind: str,
    before: Mapping[str, object] | None,
    after: Mapping[str, object] | None,
) -> None:
    """Add one event for `request`. `before`/`after` hold the changed fields only."""
    session.add(
        RequestEvent(
            request_id=request.id,
            at=now,
            actor_type=actor_type,
            actor_id=actor_id,
            kind=kind,
            before=None if before is None else dict(before),
            after=None if after is None else dict(after),
        )
    )


def agent_event(
    session: Session,
    request: Request,
    now: datetime,
    kind: str,
    before: Mapping[str, object] | None,
    after: Mapping[str, object] | None,
) -> None:
    """An event by the voice agent (the Foreman is on the Request)."""
    add_event(
        session,
        request,
        actor_type="agent",
        actor_id=None,
        now=now,
        kind=kind,
        before=before,
        after=after,
    )


def staff_event(
    session: Session,
    request: Request,
    staff_id: uuid.UUID,
    now: datetime,
    kind: str,
    before: Mapping[str, object] | None,
    after: Mapping[str, object] | None,
) -> None:
    """An event by a signed-in staff member."""
    add_event(
        session,
        request,
        actor_type="staff",
        actor_id=str(staff_id),
        now=now,
        kind=kind,
        before=before,
        after=after,
    )


def iso(at: datetime | None) -> str | None:
    """A time as stored in event JSON: UTC ISO 8601 with "Z"."""
    return None if at is None else at.astimezone(UTC).isoformat().replace("+00:00", "Z")
