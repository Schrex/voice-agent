"""Alerts to staff (spec §6 J1 step 8, J9 "Alerts"). The `alerts` table records each one.

An alert is recorded before it is sent and at most once per Request and kind, so a retried
trigger (or a restart) never texts twice. When it cannot be sent (nobody on duty, no phone,
provider error) it is recorded as failed with the reason, for the dashboard to show.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from functools import partial

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import Alert, Call, CallRequest, DutyRoster, Foreman, Job, Request, Staff
from app.domain.lifecycle import OPEN_STATUSES
from app.domain.local_time import LOCAL_TZ
from app.domain.ref import parse_ref
from app.domain.sms_text import (
    TodayRequestFacts,
    callback_request_text,
    short_date,
    today_request_text,
    transfer_text,
)
from app.domain.urgency import Urgency
from app.integrations.postmark import EmailNotSent
from app.integrations.twilio_sms import SmsNotSent, SmsSender
from app.services.queue import as_said


def deliver(session: Session, alert: Alert, send: Callable[[], str]) -> None:
    """Send a recorded alert and commit how it went: `sent` with the provider's id, or
    `failed` with the provider's reason. `send` texts or emails and returns the provider id."""
    try:
        alert.provider_id = send()
        alert.status = "sent"
    except SmsNotSent as exc:
        alert.status = "failed"
        alert.detail = f"SMS not sent: {exc}"
    except EmailNotSent as exc:
        alert.status = "failed"
        alert.detail = f"Email not sent: {exc}"
    session.commit()


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
    phone = staff.phone_e164
    deliver(
        session,
        session.get_one(Alert, alert_id),
        partial(sms.send, phone, today_request_text(facts)),
    )


def _today_request(session: Session, ref: str) -> tuple[Request, TodayRequestFacts] | None:
    number = parse_ref(ref)
    if number is None:
        return None
    row = session.execute(
        select(Request, Foreman, Job.name)
        .join(Foreman, Foreman.id == Request.foreman_id)
        .outerjoin(Job, Job.id == Request.job_id)
        .where(Request.ref == number)
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


def alert_transfer(
    session: Session,
    sms: SmsSender,
    *,
    call_id: int,
    job_id: int | None,
    job_spoken: str | None,
    about: str | None,
    now: datetime,
) -> None:
    """Tell the office who is being transferred (spec J5 step 2, AC5.3), before the transfer.

    Records a dashboard pop-up (`detail` holds its text; `seen_at` set = dismissed) and texts
    the on-duty Coordinator the same words. Once per call: a repeated call does nothing.
    `job_id` names the Job only when it is an active Job; else the Job is quoted as said.
    """
    call = session.execute(select(Call).where(Call.id == call_id).with_for_update()).scalar_one()
    already = session.scalar(
        select(Alert.id).where(Alert.call_id == call_id, Alert.kind == "transfer").limit(1)
    )
    if already is not None or call.foreman is None:
        session.rollback()
        return
    job = None
    if job_id is not None:
        job = session.scalar(select(Job.name).where(Job.id == job_id, Job.active))
    foreman = call.foreman
    text = transfer_text(
        foreman=f"{foreman.first_name} {foreman.last_name}",
        job=job,
        job_spoken=job_spoken,
        about=about,
    )
    staff, reason = on_duty_coordinator(session, now)
    if staff is not None and not staff.phone_e164:
        reason = f"{staff.name} has no phone number"
    can_send = staff is not None and staff.phone_e164 is not None
    session.add(
        Alert(
            call_id=call_id,
            kind="transfer",
            channel="popup",
            sent_at=now,
            status="sent",
            detail=text,
        )
    )
    texted = Alert(
        call_id=call_id,
        kind="transfer",
        channel="sms",
        to_staff_id=None if staff is None else staff.id,
        sent_at=now,
        status="pending" if can_send else "failed",
        detail=None if can_send else reason,
    )
    session.add(texted)
    session.commit()
    if not can_send:
        return
    assert staff is not None and staff.phone_e164 is not None
    phone = staff.phone_e164
    deliver(session, texted, partial(sms.send, phone, text))


@dataclass(frozen=True)
class Popup:
    id: int
    kind: str
    text: str
    at: datetime


def open_popups(session: Session, since: datetime | None = None) -> list[Popup]:
    """Dashboard pop-ups nobody has dismissed (after `since`, if given); newest first."""
    query = select(Alert).where(Alert.channel == "popup", Alert.seen_at.is_(None))
    if since is not None:
        query = query.where(Alert.sent_at > since)
    rows = session.scalars(query.order_by(Alert.sent_at.desc(), Alert.id.desc()))
    return [Popup(id=a.id, kind=a.kind, text=a.detail or "", at=a.sent_at) for a in rows]


class PopupNotFound(Exception):
    pass


def dismiss_popup(session: Session, popup_id: int, *, now: datetime) -> None:
    """Hide the pop-up for everybody; dismissing it again keeps the first time."""
    alert = session.get(Alert, popup_id, with_for_update=True)
    if alert is None or alert.channel != "popup":
        raise PopupNotFound(popup_id)
    if alert.seen_at is None:
        alert.seen_at = now
    session.commit()


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


# --- Callback Request (ticket #24) ---


def alert_callback(session: Session, sms: SmsSender, *, ref: str, now: datetime) -> None:
    """Text the on-duty and the backup Coordinator that the Callback Request `ref` was Recorded
    (spec J5 "Callback Request", AC5.4).

    One `callback` alert per Coordinator of `now`'s New York date, recorded before sending and
    committed together, so a retried trigger sends nothing more. One person who is both on duty
    and backup is texted once. A missing Coordinator or phone is a failed alert with the reason.
    Does nothing for a Request that is not a Recorded Callback Request.
    """
    number = parse_ref(ref)
    if number is None:
        return
    request = session.scalars(
        select(Request).where(Request.ref == number).with_for_update()
    ).one_or_none()
    if request is None or request.category != "Callback" or request.recorded_at is None:
        return
    already = session.scalar(
        select(Alert.id).where(Alert.request_id == request.id, Alert.kind == "callback").limit(1)
    )
    if already is not None:
        session.commit()  # releases the lock; nothing was changed
        return
    foreman = session.get_one(Foreman, request.foreman_id)
    call = session.execute(
        select(Call.id, Call.caller_e164)
        .join(CallRequest, CallRequest.call_id == Call.id)
        .where(CallRequest.request_id == request.id, CallRequest.relation == "created")
    ).first()
    text_body = callback_request_text(
        ref=request.ref_display,
        foreman=f"{foreman.first_name} {foreman.last_name}",
        caller_e164=None if call is None else call.caller_e164,
        reason=request.need,
    )
    to_send: list[tuple[Alert, str]] = []
    for staff, reason in _on_duty_and_backup(session, now):
        phone = None if staff is None else staff.phone_e164
        if staff is not None and phone is None:
            reason = f"{staff.name} has no phone number"
        alert = Alert(
            request_id=request.id,
            call_id=None if call is None else call.id,
            kind="callback",
            channel="sms",
            to_staff_id=None if staff is None else staff.id,
            sent_at=now,
            status="pending" if phone else "failed",
            detail=None if phone else reason,
        )
        session.add(alert)
        if phone:
            to_send.append((alert, phone))
    session.commit()
    for alert, phone in to_send:
        deliver(session, alert, partial(sms.send, phone, text_body))


def _on_duty_and_backup(session: Session, now: datetime) -> list[tuple[Staff | None, str]]:
    """The on-duty then the backup Coordinator for `now`'s New York date, each with why not
    when missing; the same person once."""
    day = now.astimezone(LOCAL_TZ).date()
    duty = session.get(DutyRoster, day)
    on_duty = None if duty is None else duty.on_duty
    backup = (
        None
        if duty is None or duty.backup_staff_id is None
        else session.get(Staff, duty.backup_staff_id)
    )
    found: list[tuple[Staff | None, str]] = [
        (on_duty, f"No on-duty Coordinator for {short_date(day)}")
    ]
    if backup is None or on_duty is None or backup.id != on_duty.id:
        found.append((backup, f"No backup Coordinator for {short_date(day)}"))
    return found
