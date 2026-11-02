"""Notes on a Request (ticket #17, spec J3 step 4): appended, optionally urgent, never edited.

A note never changes the Request's fields and never creates a Request (AC3.5). Each note writes
a `note_added` event in the same transaction. #18/#19 reuse `add_note`.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Request, RequestNote
from app.domain.lifecycle import Status
from app.domain.ref import parse_ref
from app.services.calls import Caller
from app.services.events import add_event
from app.services.merges import final_target


class NoteRequestNotFound(Exception):
    """No Request of the caller's has this ref (unknown, a Draft, or another Foreman's)."""


@dataclass(frozen=True)
class Note:
    at: datetime
    author_type: str
    author_id: str | None
    text: str
    urgent: bool


def add_note_for_caller(
    session: Session, *, caller: Caller, ref: str, text: str, urgent: bool, now: datetime
) -> None:
    """The agent appends the Foreman's note to one of his own Requests.

    A Draft is not his to note (the lookup never returns one), and a Request merged into
    another (#33) takes the note on its final target, as the lookup reports it. Anything else,
    including another Foreman's Request, raises `NoteRequestNotFound` and writes nothing.
    """
    request = own_request(session, caller, ref)
    add_note(
        session,
        request=request,
        author_type="agent",
        author_id=None,
        text=text,
        urgent=urgent,
        now=now,
    )
    session.commit()


def add_note(
    session: Session,
    *,
    request: Request,
    author_type: str,
    author_id: str | None,
    text: str,
    urgent: bool,
    now: datetime,
) -> None:
    """Append the note and its `note_added` event; the caller commits."""
    session.add(
        RequestNote(
            request_id=request.id,
            at=now,
            author_type=author_type,
            author_id=author_id,
            text=text,
            urgent=urgent,
        )
    )
    add_event(
        session,
        request,
        actor_type=author_type,
        actor_id=author_id,
        now=now,
        kind="note_added",
        before=None,
        after={"text": text, "urgent": urgent},
    )


def notes_of(session: Session, request_id: int) -> list[Note]:
    """The Request's notes, oldest first."""
    rows = session.scalars(
        select(RequestNote)
        .where(RequestNote.request_id == request_id)
        .order_by(RequestNote.at, RequestNote.id)
    )
    return [
        Note(
            at=n.at, author_type=n.author_type, author_id=n.author_id, text=n.text, urgent=n.urgent
        )
        for n in rows
    ]


def own_request(session: Session, caller: Caller, ref: str) -> Request:
    number = parse_ref(ref)
    request = (
        session.scalars(
            select(Request).where(Request.ref == number).with_for_update()
        ).one_or_none()
        if number is not None
        else None
    )
    if (
        request is None
        or request.foreman_id != caller.foreman_id
        or request.status == Status.DRAFT.value
    ):
        raise NoteRequestNotFound(ref)
    target = final_target(session, request)
    if target.foreman_id != caller.foreman_id:
        raise NoteRequestNotFound(ref)
    return target
