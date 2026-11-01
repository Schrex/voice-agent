"""Alerts to staff (spec §6 J1 step 8, J9 "Alerts"). The `alerts` table records each one.

An alert is recorded before it is sent and at most once per Request and kind, so a retried
trigger (or a restart) never texts twice. When it cannot be sent (nobody on duty, no phone,
provider error) it is recorded as failed with the reason, for the dashboard to show.
"""

import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import Alert, DutyRoster, Foreman, Job, Request, Staff
from app.domain.lifecycle import OPEN_STATUSES
from app.domain.local_time import LOCAL_TZ
from app.domain.sms_text import TodayRequestFacts, short_date, today_request_text
from app.domain.urgency import Urgency
from app.integrations.twilio_sms import SmsNotSent, SmsSender
from app.services.queue import as_said

_REF = re.compile(r"^R-(\d{1,18})$")


def on_duty_coordinator(session: Session, now: datetime) -> tuple[Staff | None, str]:
    """The on-duty Coordinator for `now`'s New York date, or None and why not."""
    day = now.astimezone(LOCAL_TZ).date()
    duty = session.get(DutyRoster, day)
    if duty is None:
        return None, f"No on-duty Coordinator for {short_date(day)}"
    return duty.on_duty, ""


def alert_new_today(session: Session, sms: SmsSender, *, ref: str, now: datetime) -> None:
    """Text the on-duty Coordinator that the Today Request rendered `ref` was Recorded (AC1.9).

    Does nothing for a Request that is not Today, and nothing if its alert was already
    recorded (sent, failed or being sent).
    """
    found = _today_request(session, ref)
    if found is None:
        return
    request, facts = found
    staff, reason = on_duty_coordinator(session, now)
    if staff is not None and not staff.phone_e164:
        reason = f"{staff.name} has no phone number"
    can_send = staff is not None and staff.phone_e164 is not None
    alert_id = session.scalar(
        insert(Alert)
        .values(
            request_id=request.id,
            kind="today_new",
            channel="sms",
            to_staff_id=None if staff is None else staff.id,
            sent_at=now,
            status="pending" if can_send else "failed",
            detail=None if can_send else reason,
        )
        .on_conflict_do_nothing(
            index_elements=["request_id"], index_where=text("kind = 'today_new'")
        )
        .returning(Alert.id)
    )
    session.commit()
    if alert_id is None or not can_send:
        return
    assert staff is not None and staff.phone_e164 is not None
    alert = session.get_one(Alert, alert_id)
    try:
        alert.provider_id = sms.send(staff.phone_e164, today_request_text(facts))
        alert.status = "sent"
    except SmsNotSent as exc:
        alert.status = "failed"
        alert.detail = f"SMS not sent: {exc}"
    session.commit()


def _today_request(session: Session, ref: str) -> tuple[Request, TodayRequestFacts] | None:
    match = _REF.match(ref)
    if match is None:
        return None
    row = session.execute(
        select(Request, Foreman, Job.name)
        .join(Foreman, Foreman.id == Request.foreman_id)
        .outerjoin(Job, Job.id == Request.job_id)
        .where(Request.ref == int(match.group(1)))
    ).one_or_none()
    if row is None:
        return None
    request, foreman, job_name = row
    if request.urgency != Urgency.TODAY.value or request.recorded_at is None:
        return None
    return request, TodayRequestFacts(
        ref=request.ref_display,
        foreman=f"{foreman.first_name} {foreman.last_name}",
        job=job_name,
        job_spoken=request.job_spoken,
        need=request.need,
        quantity=as_said(request.quantity),
        unit=request.unit,
        needed_by=request.needed_by,
        needed_by_spoken=request.needed_by_spoken,
    )


@dataclass(frozen=True)
class FailedAlert:
    ref: str | None
    kind: str
    channel: str
    at: datetime
    detail: str | None


def failed_alerts(session: Session) -> list[FailedAlert]:
    """Alerts that could not be sent, for Requests still open; newest first."""
    rows = session.execute(
        select(Alert, Request)
        .join(Request, Request.id == Alert.request_id)
        .where(Alert.status == "failed")
        .where(Request.status.in_([s.value for s in OPEN_STATUSES]))
        .order_by(Alert.sent_at.desc(), Alert.id.desc())
    ).all()
    return [
        FailedAlert(
            ref=request.ref_display,
            kind=alert.kind,
            channel=alert.channel,
            at=alert.sent_at,
            detail=alert.detail,
        )
        for alert, request in rows
    ]
