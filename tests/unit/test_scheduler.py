"""The scheduler starts and stops with the app (ticket #22; architecture §6)."""

import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import app


def test_the_app_runs_the_overdue_sweep_every_minute_while_it_is_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SCHEDULER_ENABLED", raising=False)
    with TestClient(app):
        scheduler = main.scheduler
        assert scheduler is not None and scheduler.running
        [job] = scheduler.get_jobs()
        assert (job.id, job.trigger.interval.total_seconds()) == ("overdue_sweep", 60)
    assert not scheduler.running
    assert main.scheduler is None


@pytest.mark.parametrize("value", ["false", "0", "off"])
def test_the_scheduler_can_be_turned_off(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("SCHEDULER_ENABLED", value)
    with TestClient(app):
        assert main.scheduler is None
