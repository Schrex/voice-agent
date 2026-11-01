"""Amend a Request by phone (ticket #19; spec J4, AC4.2; architecture §4.2 `amend_request`).

Before In Progress (Recorded, Acknowledged; `domain.lifecycle.may_amend`) the Foreman's change
is applied and an `amended` event by the agent records the changed fields before and after.
At or after In Progress nothing is changed: a note says what was asked (`notes.add_note`) and
the Request is flagged Change requested, with a `change_requested` event the first time.
Either way the call is linked to the Request (`call_requests` relation `amended`), and it is
all one transaction.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import CallRequest, Request, RequestEvent
from app.domain.lifecycle import Status, may_amend
from app.domain.timeparse import parse_needed_by, speakable, urgency_for
from app.domain.urgency import Urgency
from app.services.ack_window import set_ack_due_at
from app.services.calls import Caller
from app.services.notes import NoteRequestNotFound, _own_request, add_note
from app.services.queue import as_said
from app.services.requests import _iso
from app.services.status_lookup import _speakable

# What a Foreman can change by phone: the details he gave and confirmed on the call.
AMENDABLE_FIELDS = ("need", "quantity", "unit", "needed_by_spoken")


class AmendRequestNotFound(Exception):
    """No Request of the caller's has this ref (unknown, a Draft, or another Foreman's)."""


@dataclass(frozen=True)
class Amended:
    """What the agent reads back. Only `applied` and `status` when nothing was changed."""

    applied: bool
    status: str
    ref: str
    need: str
    quantity: Decimal | None
    unit: str | None
    needed_by_resolved: str | None
    """E.g. "Thursday, November 5 at 7:00 AM"; None when unknown, not understood or day only."""


def amend_request(
    session: Session,
    *,
    caller: Caller,
    ref: str,
    changes: Mapping[str, object],
    now: datetime,
) -> Amended:
    """Apply `changes` (keys from AMENDABLE_FIELDS) to the caller's Request `ref`, or flag it.

    The Request must be the caller's own and not a Draft; a merged one is amended on its final
    target, as the lookup reports it. Otherwise AmendRequestNotFound, with nothing written.
    """
    unknown = set(changes) - set(AMENDABLE_FIELDS)
    if not changes or unknown:
        raise ValueError(f"Not amendable: {sorted(unknown)}")
    try:
        request = _own_request(session, caller, ref)
    except NoteRequestNotFound as e:
        raise AmendRequestNotFound(ref) from e
    applied = may_amend(Status(request.status))
    if applied:
        needed_by_resolved = _apply(session, request, changes, now)
    else:
        _flag(session, request, changes, now)
        needed_by_resolved = None
    session.execute(
        insert(CallRequest)
        .values(call_id=caller.call_id, request_id=request.id, relation="amended")
        .on_conflict_do_nothing()
    )
    session.commit()
    return Amended(
        applied=applied,
        status=request.status,
        ref=request.ref_display,
        need=request.need,
        quantity=request.quantity,
        unit=request.unit,
        needed_by_resolved=needed_by_resolved,
    )


def _apply(
    session: Session, request: Request, changes: Mapping[str, object], now: datetime
) -> str | None:
    """Change the Request and write its `amended` event; returns the needed-by to read back."""
    before = _snapshot(request)
    for name in ("need", "quantity", "unit"):
        if name in changes:
            setattr(request, name, changes[name])
    readback = _speakable(request.needed_by)
    if "needed_by_spoken" in changes:
        spoken = changes["needed_by_spoken"]
        assert isinstance(spoken, str)
        needed_by = parse_needed_by(spoken, now)
        request.needed_by_spoken = spoken
        request.needed_by = None if needed_by is None else needed_by.at
        # Urgency follows the needed-by as on submit; Emergency is about danger, not time.
        if request.urgency != Urgency.EMERGENCY.value:
            request.urgency = None if needed_by is None else urgency_for(needed_by, now).value
        set_ack_due_at(session, request)
        readback = None if needed_by is None else speakable(needed_by)
    after = _snapshot(request)
    changed = [name for name in after if after[name] != before[name]]
    if changed:
        session.add(
            RequestEvent(
                request_id=request.id,
                at=now,
                actor_type="agent",
                actor_id=None,
                kind="amended",
                before={name: before[name] for name in changed},
                after={name: after[name] for name in changed},
            )
        )
    return readback


def _flag(session: Session, request: Request, changes: Mapping[str, object], now: datetime) -> None:
    """Leave the Request as it is: note what was asked and flag it Change requested."""
    add_note(
        session,
        request=request,
        author_type="agent",
        author_id=None,
        text=change_note(changes),
        urgent=False,
        now=now,
    )
    if request.change_requested:
        return
    request.change_requested = True
    session.add(
        RequestEvent(
            request_id=request.id,
            at=now,
            actor_type="agent",
            actor_id=None,
            kind="change_requested",
            before={"change_requested": False},
            after={"change_requested": True},
        )
    )


def change_note(changes: Mapping[str, object]) -> str:
    """'Change requested: needed-by "thursday at seven"; quantity 4' (in AMENDABLE_FIELDS order)."""
    parts = []
    for name in AMENDABLE_FIELDS:
        if name not in changes:
            continue
        value = changes[name]
        label = "needed-by" if name == "needed_by_spoken" else name
        if value is None:
            parts.append(f"no {label}")
        elif isinstance(value, Decimal):
            parts.append(f"{label} {as_said(value)}")
        else:
            parts.append(f'{label} "{value}"')
    return "Change requested: " + "; ".join(parts)


def _snapshot(request: Request) -> dict[str, object]:
    """The amendable fields and what follows from them, as recorded in events."""
    return {
        "need": request.need,
        "quantity": as_said(request.quantity),
        "unit": request.unit,
        "needed_by_spoken": request.needed_by_spoken,
        "needed_by": _iso(request.needed_by),
        "urgency": request.urgency,
        "ack_due_at": _iso(request.ack_due_at),
    }
