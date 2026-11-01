"""The app runs the scheduled jobs while it is up (architecture §6; ticket #23)."""

from datetime import timedelta

from fastapi.testclient import TestClient

from app import jobs
from app.main import app


def test_the_app_runs_the_end_of_day_summary_every_minute_while_up() -> None:
    with TestClient(app):
        scheduler = jobs.running_scheduler()
        assert scheduler is not None and scheduler.running
        job = scheduler.get_job("end_of_day_summary")
        assert job is not None
        assert job.trigger.interval == timedelta(minutes=1)
    assert jobs.running_scheduler() is None
