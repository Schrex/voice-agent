"""Scheduled jobs (architecture §6): APScheduler in-process, started with the app (`main.py`).

Jobs are idempotent: the alerts table records what was sent, so a restart (or a second
process) never sends twice.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session

from app.clock import Clock, utc_now
from app.db.session import new_session
from app.http.sms import get_sms_sender
from app.integrations.twilio_sms import SmsSender
from app.services.overdue import sweep_overdue


def overdue_sweep(
    *,
    sessions: Callable[[], AbstractContextManager[Session]] = new_session,
    sms: Callable[[], SmsSender] = get_sms_sender,
    clock: Clock = utc_now,
) -> None:
    """Every minute: text the backup Coordinator for each newly Overdue Request (#22)."""
    with sessions() as session:
        sweep_overdue(session, sms(), now=clock())


def build_scheduler() -> BackgroundScheduler:
    """The app's scheduler with every job registered; the caller starts and stops it."""
    scheduler = BackgroundScheduler(timezone=UTC)
    scheduler.add_job(
        overdue_sweep,
        IntervalTrigger(minutes=1),
        id="overdue_sweep",
        max_instances=1,
        coalesce=True,
    )
    return scheduler
