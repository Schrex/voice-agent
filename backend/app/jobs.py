"""Scheduled jobs (architecture §6): APScheduler in-process, 1-minute tick.

Each job is idempotent through the `alerts` table, so a restart (or a tick that runs late)
never sends twice. Started and stopped by the app's lifespan (`app/main.py`).
"""

import logging
from collections.abc import Callable
from functools import cache

import httpx
from apscheduler.schedulers.background import (  # type: ignore[import-untyped]
    BackgroundScheduler,
)
from sqlalchemy.orm import Session

from app.clock import Clock, utc_now
from app.config import postmark_api_base, postmark_from, postmark_server_token
from app.db.session import new_session
from app.integrations.postmark import EmailSender, PostmarkEmail
from app.services.eod_summary import send_end_of_day_summary

log = logging.getLogger(__name__)


@cache
def _postmark_client(base_url: str) -> httpx.Client:
    return httpx.Client(base_url=base_url, timeout=httpx.Timeout(10.0, connect=3.0))


def postmark_sender() -> EmailSender:
    return PostmarkEmail(
        _postmark_client(postmark_api_base()), postmark_server_token(), postmark_from()
    )


def end_of_day_summary_tick(
    sessions: Callable[[], Session], email: Callable[[], EmailSender], clock: Clock
) -> None:
    """One tick of the 17:00 end-of-day summary (ticket #23); a no-op before 17:00 or once sent."""
    try:
        with sessions() as session:
            send_end_of_day_summary(session, email(), now=clock())
    except Exception:
        log.exception("end-of-day summary tick failed")


_scheduler: BackgroundScheduler | None = None


def running_scheduler() -> BackgroundScheduler | None:
    return _scheduler


def start_scheduler() -> None:
    global _scheduler
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        end_of_day_summary_tick,
        "interval",
        minutes=1,
        args=(new_session, postmark_sender, utc_now),
        id="end_of_day_summary",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
