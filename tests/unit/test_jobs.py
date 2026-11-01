"""The app runs the scheduled jobs while it is up (architecture §6; ticket #23)."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import jobs
from app.config import scheduler_enabled
from app.main import app


def test_the_app_runs_the_end_of_day_summary_every_minute_while_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SCHEDULER_ENABLED", raising=False)
    with TestClient(app):
        scheduler = jobs.running_scheduler()
        assert scheduler is not None and scheduler.running
        job = scheduler.get_job("end_of_day_summary")
        assert job is not None
        assert job.trigger.interval == timedelta(minutes=1)
    assert jobs.running_scheduler() is None


def test_scheduler_enabled_false_keeps_the_jobs_off_while_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    with TestClient(app):  # lifespan has run: the app is up
        assert jobs.running_scheduler() is None


@pytest.mark.parametrize(
    ("raw", "enabled"),
    [(None, True), ("", True), ("true", True), ("1", True), (" TRUE ", True), ("on", True)]
    + [("false", False), ("0", False), ("False", False), ("off", False), ("no", False)],
)
def test_scheduler_enabled_is_true_unless_set_false(
    monkeypatch: pytest.MonkeyPatch, raw: str | None, enabled: bool
) -> None:
    if raw is None:
        monkeypatch.delenv("SCHEDULER_ENABLED", raising=False)
    else:
        monkeypatch.setenv("SCHEDULER_ENABLED", raw)
    assert scheduler_enabled() is enabled


def test_scheduler_enabled_refuses_a_typo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCHEDULER_ENABLED", "flase")
    with pytest.raises(RuntimeError, match="SCHEDULER_ENABLED"):
        scheduler_enabled()
