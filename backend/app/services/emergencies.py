"""Emergency (ticket #26; spec J6, AC6.2; architecture §3.3, §4.2 `start_emergency`).

The agent has already said the safety line. Before it transfers to the Office Line, the backend
records an Emergency Request, raises a dashboard pop-up and texts every Coordinator (spec §4:
at any hour, no duty roster needed). The agent transfers whatever this returns.
"""

from dataclasses import dataclass
from datetime import datetime
from functools import partial

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Alert, Call, CallRequest, Foreman, Job, Request, Staff
from app.domain.lifecycle import Status, transition
from app.domain.sms_text import emergency_text
from app.domain.urgency import Urgency
from app.integrations.twilio_sms import SmsSender
from app.services.ack_window import set_ack_due_at
from app.services.alerts import deliver
from app.services.calls import Caller
from app.services.events import agent_event
from app.services.requests import recorded_fields

# The spec gives an Emergency no Category of its own (open question on #26); none of the
# others fits, so it is Other, the glossary's catch-all.
EMERGENCY_CATEGORY = "Other"
NO_COORDINATOR = "No Coordinator on the staff list"


@dataclass(frozen=True)
class EmergencyReport:
    summary: str
    """What happened, in the Foreman's words."""
    job_id: int | None = None
    """From `find_jobs`, if the Job was already known on the call."""
    job_spoken: str | None = None
    """The Job in the Foreman's words, if he named one."""


def start_emergency(
    session: Session, sms: SmsSender, *, caller: Caller, report: EmergencyReport, now: datetime
) -> str:
    """Record the Emergency Request and alert the office; returns its ref ("R-1042").

    In one transaction: the Request (urgency Emergency, Recorded, by the agent), its `recorded`
    event, its `created` link to the call, the pop-up and one `emergency` SMS alert per staff
    member (one Staff role, ADR 0006: everyone on the staff list is a Coordinator). Committed
    before any SMS is sent, then each SMS is sent and marked sent or failed. Once per call:
    asking again returns the same ref and writes and sends nothing (the Call row is locked).
    """
    session.execute(select(Call.id).where(Call.id == caller.call_id).with_for_update())
    already = session.scalar(
        select(Request)
        .join(Alert, Alert.request_id == Request.id)
        .where(Alert.call_id == caller.call_id, Alert.kind == "emergency")
        .limit(1)
    )
    if already is not None:
        session.commit()  # releases the lock; nothing was changed
        return already.ref_display

    job = None
    if report.job_id is not None:
        job = session.scalar(select(Job).where(Job.id == report.job_id, Job.active))
    request = Request(
        foreman_id=caller.foreman_id,
        job_id=None if job is None else job.id,
        job_spoken=(report.job_spoken or "").strip(),
        category=EMERGENCY_CATEGORY,
        need=report.summary.strip(),
        urgency=Urgency.EMERGENCY.value,
        status=transition(Status.DRAFT, Status.RECORDED).value,
        source="ai_call",
        recorded_at=now,
    )
    set_ack_due_at(session, request)  # none for Emergency (#22)
    session.add(request)
    session.flush()
    agent_event(session, request, now, "recorded", None, recorded_fields(request))
    session.add(CallRequest(call_id=caller.call_id, request_id=request.id, relation="created"))

    foreman = session.get_one(Foreman, caller.foreman_id)
    text = emergency_text(
        foreman=f"{foreman.first_name} {foreman.last_name}",
        job=None if job is None else job.name,
        job_spoken=report.job_spoken,
        summary=report.summary,
    )

    def alert(**fields: object) -> Alert:
        row = Alert(
            request_id=request.id, call_id=caller.call_id, kind="emergency", sent_at=now, **fields
        )
        session.add(row)
        return row

    alert(channel="popup", status="sent", detail=text)
    coordinators = session.scalars(
        select(Staff).where(Staff.removed_at.is_(None)).order_by(Staff.name, Staff.id)
    ).all()
    to_send: list[tuple[Alert, str]] = []
    if not coordinators:
        alert(channel="sms", status="failed", detail=NO_COORDINATOR)
    for staff in coordinators:
        if staff.phone_e164 is None:
            alert(
                channel="sms",
                to_staff_id=staff.id,
                status="failed",
                detail=f"{staff.name} has no phone number",
            )
        else:
            to_send.append(
                (alert(channel="sms", to_staff_id=staff.id, status="pending"), staff.phone_e164)
            )
    ref = request.ref_display
    session.commit()

    for row, phone in to_send:
        deliver(session, row, partial(sms.send, phone, text))
    return ref
