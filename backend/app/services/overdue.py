"""Overdue Requests text the backup Coordinator (ticket #22; spec J9 "Alerts", AC9.3).

Overdue = still Recorded after `ack_due_at` (`domain.sla.is_overdue`). The sweep runs every
minute (`app.jobs`). Each Overdue Request gets one `overdue` alert at most: the alert row is
recorded (and committed) before the SMS is sent, under the unique index `uq_alerts_overdue`,
so a repeated sweep, a restart or a second scheduler never texts twice. When it cannot be sent
it is recorded as failed with the reason, for the dashboard's "Alerts not sent".

The backup is the one on the duty roster for the New York date the Request went Overdue
(`ack_due_at`). Overnight Overdue alerts are sent immediately (spec §12 "Default v1").
"""

from datetime import datetime
from functools import partial

from sqlalchemy import exists, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import Alert, DutyRoster, Foreman, Job, Request, Staff
from app.domain.lifecycle import Status
from app.domain.local_time import LOCAL_TZ
from app.domain.sms_text import (
    TodayRequestFacts,
    overdue_callback_text,
    overdue_request_text,
    short_date,
)
from app.integrations.twilio_sms import SmsSender
from app.services.alerts import deliver
from app.services.queue import as_said


def sweep_overdue(session: Session, sms: SmsSender, *, now: datetime) -> None:
    """Alert the backup for every Request that is Overdue at `now` and not yet alerted."""
    already_alerted = exists().where(Alert.request_id == Request.id, Alert.kind == "overdue")
    rows = session.execute(
        select(Request, Foreman, Job.name)
        .join(Foreman, Foreman.id == Request.foreman_id)
        .outerjoin(Job, Job.id == Request.job_id)
        .where(
            Request.status == Status.RECORDED.value,
            Request.ack_due_at < now,
            ~already_alerted,
        )
        .order_by(Request.ack_due_at, Request.ref)
    ).all()
    for request, foreman, job_name in rows:
        _alert_overdue(
            session, sms, request, f"{foreman.first_name} {foreman.last_name}", job_name, now
        )


def backup_coordinator(session: Session, due: datetime) -> tuple[Staff | None, str]:
    """The backup Coordinator for `due`'s New York date, or None and why not."""
    day = due.astimezone(LOCAL_TZ).date()
    duty = session.get(DutyRoster, day)
    backup = (
        None
        if duty is None or duty.backup_staff_id is None
        else session.get(Staff, duty.backup_staff_id)
    )
    if backup is None:
        return None, f"No backup Coordinator for {short_date(day)}"
    return backup, ""


def _alert_overdue(
    session: Session,
    sms: SmsSender,
    request: Request,
    foreman: str,
    job_name: str | None,
    now: datetime,
) -> None:
    assert request.ack_due_at is not None and request.recorded_at is not None
    assert request.urgency is not None
    staff, reason = backup_coordinator(session, request.ack_due_at)
    if staff is not None and not staff.phone_e164:
        reason = f"{staff.name} has no phone number"
    can_send = staff is not None and staff.phone_e164 is not None
    alert_id = session.scalar(
        insert(Alert)
        .values(
            request_id=request.id,
            kind="overdue",
            channel="sms",
            to_staff_id=None if staff is None else staff.id,
            sent_at=now,
            status="pending" if can_send else "failed",
            detail=None if can_send else reason,
        )
        .on_conflict_do_nothing(index_elements=["request_id"], index_where=text("kind = 'overdue'"))
        .returning(Alert.id)
    )
    session.commit()
    if alert_id is None or not can_send:
        return
    assert staff is not None and staff.phone_e164 is not None
    if request.category == "Callback":  # no Job; the reason is the need (#24's wording)
        body = overdue_callback_text(
            ref=request.ref_display,
            foreman=foreman,
            reason=request.need,
            recorded_at=request.recorded_at,
        )
    else:
        body = overdue_request_text(
            TodayRequestFacts(
                ref=request.ref_display,
                foreman=foreman,
                job=job_name,
                job_spoken=request.job_spoken,
                need=request.need,
                quantity=as_said(request.quantity),
                unit=request.unit,
                needed_by=request.needed_by,
                needed_by_spoken=request.needed_by_spoken,
            ),
            urgency=request.urgency,
            recorded_at=request.recorded_at,
        )
    phone = staff.phone_e164
    deliver(session, session.get_one(Alert, alert_id), partial(sms.send, phone, body))
