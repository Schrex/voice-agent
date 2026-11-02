"""Callback Request (ticket #24; spec J5 "Callback Request", architecture §4.2).

The Foreman asks to be called back. The agent may ask one optional question ("What's it
about?"); the backend records the Callback Request. Texting the Coordinators is
`app.services.alerts.alert_callback`, after this commit.
"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import CallRequest, Request
from app.domain.lifecycle import Status, transition
from app.domain.urgency import Urgency
from app.services.ack_window import set_ack_due_at
from app.services.calls import Caller
from app.services.events import agent_event
from app.services.requests import recorded_fields

CALLBACK = "Callback"


def create_callback_request(
    session: Session, *, caller: Caller, reason: str | None, now: datetime
) -> str:
    """Record a Callback Request of the caller's Foreman; returns its ref (e.g. "R-1042").

    Category Callback, urgency Today, Recorded (spec J5). The reason, as the Foreman said it, is
    the need; none given is stored as "" (not stated). No Job is asked for, so it has none
    (`job_spoken` ""). Writes the Request, its `recorded` event by the agent and a `created`
    link to the call in one transaction.
    """
    request = Request(
        foreman_id=caller.foreman_id,
        job_id=None,
        job_spoken="",
        category=CALLBACK,
        need=(reason or "").strip(),
        urgency=Urgency.TODAY.value,
        status=transition(Status.DRAFT, Status.RECORDED).value,
        source="ai_call",
        recorded_at=now,
    )
    set_ack_due_at(session, request)  # Today: the 15-min window (spec J5, ticket #22)
    session.add(request)
    session.flush()
    agent_event(session, request, now, "recorded", None, recorded_fields(request))
    session.add(CallRequest(call_id=caller.call_id, request_id=request.id, relation="created"))
    session.commit()
    return request.ref_display
