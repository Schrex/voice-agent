"""Merge duplicates (ticket #33; spec J2 "Coordinators can also merge duplicates", J9).

A coordinator merges Request A into Request B: A is Resolved with a pointer to B, and both
Requests get a history event, all in one transaction. Nothing is deleted; A's history (and any
notes) stay on A. A status lookup of A's ref reports B (`status_request`).
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Request
from app.domain.lifecycle import Outcome, Status, merge
from app.domain.ref import parse_ref
from app.services.events import iso, staff_event
from app.services.requests import RequestNotFound, locked_request


def merge_request(
    session: Session,
    *,
    ref: str,
    into: str,
    outcome: Outcome | None,
    explanation: str | None,
    staff_id: uuid.UUID,
    now: datetime,
) -> None:
    """Merge the Request rendered `ref` (A) into the one rendered `into` (B).

    Not into itself, not into a Resolved Request, and A is resolved as Resolve requires: an
    Outcome and a non-blank explanation (`domain.lifecycle.merge`). A gets a `merged` event with
    its resolve fields and `merged_into`; B gets a `merged_in` event naming A. A refused merge
    raises and writes nothing.
    """
    source = locked_request(session, ref)
    target = locked_request(session, into)
    status = merge(
        Status(source.status),
        Status(target.status),
        same=source.id == target.id,
        outcome=outcome,
        explanation=explanation,
    )
    assert outcome is not None and explanation is not None  # guaranteed by the guard
    before = {
        "status": source.status,
        "outcome": source.outcome,
        "explanation": source.explanation,
        "resolved_at": iso(source.resolved_at),
        "merged_into": None,
    }
    source.status = status.value
    source.outcome = outcome.value
    source.explanation = explanation
    source.resolved_at = now
    source.merged_into_id = target.id
    after = {
        "status": status.value,
        "outcome": outcome.value,
        "explanation": explanation,
        "resolved_at": iso(now),
        "merged_into": target.ref_display,
    }
    staff_event(session, source, staff_id, now, "merged", before, after)
    staff_event(
        session,
        target,
        staff_id,
        now,
        "merged_in",
        {"merged_from": None},
        {"merged_from": source.ref_display},
    )
    session.commit()


def status_request(session: Session, ref: str) -> Request:
    """The Request whose status answers a lookup of `ref`: the Request it was merged into
    (following merges of merges), else itself. RequestNotFound if `ref` is unknown.

    For the phone status lookup (`find_open_requests`, ticket #16) to report B for A's ref.
    """
    number = parse_ref(ref)
    request = (
        session.scalars(select(Request).where(Request.ref == number)).one_or_none()
        if number is not None
        else None
    )
    if request is None:
        raise RequestNotFound(ref)
    return final_target(session, request)


def final_target(session: Session, request: Request) -> Request:
    """The Request that `request` was finally merged into (following merges of merges), else
    `request` itself. Merges cannot cycle: a merged Request is Resolved and nothing merges into
    a Resolved Request."""
    while request.merged_into_id is not None:
        merged_into = session.get(Request, request.merged_into_id)
        assert merged_into is not None  # foreign key
        request = merged_into
    return request
