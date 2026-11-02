"""End-of-day summary email to Coordinators (ticket #23; spec J1 step 8, J9 "Alerts").

From 17:00 New York time each Coordinator gets one email a day: the Planned Requests Recorded
since the previous 17:00, and the open counts. Each email is recorded as an `eod_summary`
alert (one per Coordinator per day) before it is sent, so a scheduler tick after a restart, or
a second instance, never sends it twice; a failed send is recorded with the reason and not
retried (as #21's SMS).
"""

from datetime import datetime
from functools import partial

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import Alert, Foreman, Job, Request, Staff
from app.domain.eod_summary import (
    OpenCounts,
    is_due,
    summary_day,
    summary_subject,
    summary_text,
    summary_window,
)
from app.domain.lifecycle import Status
from app.domain.sms_text import TodayRequestFacts
from app.domain.urgency import Urgency
from app.integrations.postmark import EmailSender
from app.services.alerts import deliver
from app.services.queue import as_said


def send_end_of_day_summary(session: Session, email: EmailSender, *, now: datetime) -> None:
    """Email today's summary to every Coordinator who has not had it yet; nothing before 17:00."""
    if not is_due(now):
        return
    day = summary_day(now)
    coordinators = session.scalars(
        select(Staff).where(Staff.role == "coordinator").order_by(Staff.name, Staff.id)
    ).all()
    pending: list[tuple[int, str]] = []
    for staff in coordinators:
        alert_id = session.scalar(
            insert(Alert)
            .values(
                kind="eod_summary",
                channel="email",
                to_staff_id=staff.id,
                summary_date=day,
                sent_at=now,
                status="pending",
            )
            .on_conflict_do_nothing(
                index_elements=["to_staff_id", "summary_date"],
                index_where=text("kind = 'eod_summary'"),
            )
            .returning(Alert.id)
        )
        if alert_id is not None:
            pending.append((alert_id, staff.email))
    session.commit()
    if not pending:
        return
    subject = summary_subject(day)
    body = summary_text(day, _new_planned(session, now), _open_counts(session))
    for alert_id, address in pending:
        deliver(
            session,
            session.get_one(Alert, alert_id),
            partial(email.send, address, subject, body),
        )


def _new_planned(session: Session, now: datetime) -> list[tuple[TodayRequestFacts, str]]:
    start, end = summary_window(summary_day(now))
    rows = session.execute(
        select(Request, Foreman, Job.name)
        .join(Foreman, Foreman.id == Request.foreman_id)
        .outerjoin(Job, Job.id == Request.job_id)
        .where(Request.urgency == Urgency.PLANNED.value)
        .where(Request.recorded_at > start, Request.recorded_at <= end)
        .order_by(Request.recorded_at, Request.ref)
    ).all()
    return [
        (
            TodayRequestFacts(
                ref=request.ref_display,
                foreman=f"{foreman.first_name} {foreman.last_name}",
                job=job_name,
                job_spoken=request.job_spoken,
                need=request.need,
                quantity=as_said(request.quantity),
                unit=request.unit,
                needed_by=request.needed_by,
                needed_by_spoken=request.needed_by_spoken,
            ),
            request.status,
        )
        for request, foreman, job_name in rows
    ]


def _open_counts(session: Session) -> OpenCounts:
    rows = session.execute(select(Request.status, func.count()).group_by(Request.status))
    counts: dict[str, int] = {status: count for status, count in rows}
    return OpenCounts(
        recorded=counts.get(Status.RECORDED.value, 0),
        acknowledged=counts.get(Status.ACKNOWLEDGED.value, 0),
        in_progress=counts.get(Status.IN_PROGRESS.value, 0),
    )
