"""Overdue Requests alert the backup (ticket #22; spec §4, §5 flags, J9 "Alerts", AC9.3).

A Recorded Request not Acknowledged within its ack window (Today 15 min, Planned 2 h, from
`settings`) shows Overdue in the queue, and the every-minute sweep texts the backup Coordinator
once. Twilio is replaced by a fake `SmsSender`; the alerts table records what was sent.
"""

import json
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import jobs
from app.clock import get_clock
from app.db.models import (
    Alert,
    DutyRoster,
    Foreman,
    Job,
    Owner,
    Request,
    RequestEvent,
    Settings,
    Staff,
)
from app.http.sms import get_sms_sender
from app.integrations.twilio_sms import SmsNotSent
from app.main import app
from app.services.roster import load_roster_file, seed_roster

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "elevenlabs"
SAMPLE_ROSTER = ROOT / "backend" / "seed" / "sample_roster.json"

HOOK_SECRET = "test-hook-secret"
TOOL_SECRET = "test-tool-secret"
JWT_SECRET = "test-jwt-secret-at-least-32-bytes-long"
# Sunday, November 1, 2026, 3:04 PM in New York.
NOW = datetime(2026, 11, 1, 20, 4, tzinfo=UTC)
SUNDAY = date(2026, 11, 1)
MONDAY = date(2026, 11, 2)
MINUTE = timedelta(minutes=1)
SECOND = timedelta(seconds=1)

ROSTERED = json.loads((FIXTURES / "call_start_rostered.json").read_text())
CONVERSATION = ROSTERED["conversation_id"]


@dataclass
class FakeSms:
    sent: list[tuple[str, str]] = field(default_factory=list)
    fail: bool = False

    def send(self, to: str, body: str) -> str:
        if self.fail:
            raise SmsNotSent("Twilio answered 400")
        self.sent.append((to, body))
        return f"SM{len(self.sent):032d}"


class MovableClock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def sms() -> FakeSms:
    return FakeSms()


@pytest.fixture
def clock() -> MovableClock:
    return MovableClock()


@pytest.fixture
def tools(
    client: TestClient,
    db_session: Session,
    sms: FakeSms,
    clock: MovableClock,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """Seeded roster, secrets set, movable clock, fake SMS, and Dale's call started."""
    monkeypatch.setenv("HOOK_SECRET", HOOK_SECRET)
    monkeypatch.setenv("TOOL_SECRET", TOOL_SECRET)
    monkeypatch.setenv("OFFICE_MAIN_NUMBER", "585-555-0100")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", JWT_SECRET)
    seed_roster(db_session, load_roster_file(SAMPLE_ROSTER))
    app.dependency_overrides[get_clock] = lambda: clock
    app.dependency_overrides[get_sms_sender] = lambda: sms
    started = client.post(
        "/hooks/call-start", json=ROSTERED, headers={"X-Hook-Secret": HOOK_SECRET}
    )
    assert started.status_code == 200
    yield client


def _staff(session: Session, name: str, phone: str | None) -> Staff:
    staff = Staff(
        id=uuid.uuid4(), name=name, email=f"{uuid.uuid4().hex}@example.com", role="coordinator"
    )
    staff.phone_e164 = phone
    session.add(staff)
    session.flush()
    return staff


def _duty(session: Session, day: date, on_duty: Staff, backup: Staff | None = None) -> None:
    session.add(
        DutyRoster(
            day=day,
            on_duty_staff_id=on_duty.id,
            backup_staff_id=None if backup is None else backup.id,
        )
    )
    session.flush()


@dataclass
class Team:
    on_duty: Staff
    backup: Staff


@pytest.fixture
def team(db_session: Session) -> Team:
    """Pat is on duty and Sam is the backup on Sunday."""
    team = Team(
        on_duty=_staff(db_session, "Pat Lee", "+15855550199"),
        backup=_staff(db_session, "Sam Ortiz", "+15855550198"),
    )
    _duty(db_session, SUNDAY, team.on_duty, team.backup)
    return team


def _submit(client: TestClient, session: Session, needed_by_spoken: str | None) -> str:
    job_id = session.scalars(select(Job.id).where(Job.name == "Route 104 Widening")).one()
    item: dict[str, Any] = {
        "job_id": job_id,
        "job_spoken": "the 104 job",
        "category": "Trucking",
        "need": "tri-axle dump trucks",
        "quantity": 3,
        "unit": "trucks",
    }
    if needed_by_spoken is not None:
        item["needed_by_spoken"] = needed_by_spoken
    response = client.post(
        "/tools/submit_requests",
        json={"items": [item]},
        headers={"X-Tool-Secret": TOOL_SECRET, "X-Conversation-Id": CONVERSATION},
    )
    assert response.status_code == 200
    [result] = response.json()
    return str(result["ref"])


def _headers(staff: Staff) -> dict[str, str]:
    claims = {"sub": str(staff.id), "aud": "authenticated", "exp": int(time.time()) + 3600}
    return {"Authorization": f"Bearer {jwt.encode(claims, JWT_SECRET, algorithm='HS256')}"}


def _queue(client: TestClient, staff: Staff) -> dict[str, bool]:
    response = client.get("/api/requests", headers=_headers(staff))
    assert response.status_code == 200
    return {r["ref"]: r["overdue"] for r in response.json()["requests"]}


def _sweep(session: Session, sms: FakeSms, clock: MovableClock) -> None:
    """One tick of the scheduler's Overdue sweep, on the test's session, SMS and clock."""

    @contextmanager
    def sessions() -> Iterator[Session]:
        yield session

    jobs.overdue_sweep(sessions=sessions, sms=lambda: sms, clock=clock)


def _overdue_alerts(session: Session) -> list[Alert]:
    return list(session.scalars(select(Alert).where(Alert.kind == "overdue").order_by(Alert.id)))


def _sms_to(sms: FakeSms, phone: str) -> list[str]:
    return [body for to, body in sms.sent if to == phone]


def test_ac9_3_a_today_request_not_acknowledged_in_15_min_shows_overdue_and_texts_the_backup(
    tools: TestClient, db_session: Session, sms: FakeSms, clock: MovableClock, team: Team
) -> None:
    ref = _submit(tools, db_session, "today at five")
    recorded = db_session.scalars(select(RequestEvent)).one()
    assert recorded.after is not None
    assert recorded.after["ack_due_at"] == "2026-11-01T20:19:00Z"

    clock.now = NOW + 15 * MINUTE  # exactly at the end of the window: not yet
    _sweep(db_session, sms, clock)
    assert _queue(tools, team.on_duty) == {ref: False}
    assert _sms_to(sms, team.backup.phone_e164 or "") == []

    clock.now = NOW + 15 * MINUTE + SECOND
    assert _queue(tools, team.on_duty) == {ref: True}
    _sweep(db_session, sms, clock)

    assert _sms_to(sms, team.backup.phone_e164 or "") == [
        f"Overdue: Today request {ref} from Dale Kramer, Route 104 Widening: "
        "tri-axle dump trucks, 3 trucks, needed by Sun, Nov 1, 5:00 PM. "
        "Recorded Sun, Nov 1, 3:04 PM, not Acknowledged"
    ]
    [alert] = _overdue_alerts(db_session)
    request = db_session.scalars(select(Request)).one()
    assert (alert.request_id, alert.channel, alert.to_staff_id, alert.status) == (
        request.id,
        "sms",
        team.backup.id,
        "sent",
    )
    assert (alert.sent_at, alert.provider_id) == (clock.now, "SM" + "0" * 31 + "2")


def test_the_backup_is_texted_once_however_many_sweeps_run(
    tools: TestClient, db_session: Session, sms: FakeSms, clock: MovableClock, team: Team
) -> None:
    _submit(tools, db_session, "today at five")

    for minutes in (16, 17, 18, 60):
        clock.now = NOW + minutes * MINUTE
        _sweep(db_session, sms, clock)

    assert len(_sms_to(sms, team.backup.phone_e164 or "")) == 1
    assert len(_overdue_alerts(db_session)) == 1


def test_a_scheduler_restart_does_not_double_send(
    tools: TestClient, db_session: Session, sms: FakeSms, clock: MovableClock, team: Team
) -> None:
    _submit(tools, db_session, "today at five")
    clock.now = NOW + 16 * MINUTE
    _sweep(db_session, sms, clock)

    # Restart: a new scheduler, a new SMS client; the alerts table is all that survives.
    restarted = FakeSms()
    jobs.start_scheduler()
    try:
        scheduler = jobs.running_scheduler()
        assert scheduler is not None and scheduler.get_job("overdue_sweep") is not None
    finally:
        jobs.stop_scheduler()
    _sweep(db_session, restarted, clock)

    assert restarted.sent == []
    assert len(_overdue_alerts(db_session)) == 1


def test_an_alert_recorded_before_a_crash_is_not_sent_again_after_the_restart(
    tools: TestClient, db_session: Session, sms: FakeSms, clock: MovableClock, team: Team
) -> None:
    """At most once: a pending alert (process died mid-send) is never re-sent."""
    _submit(tools, db_session, "today at five")
    request = db_session.scalars(select(Request)).one()
    db_session.add(
        Alert(
            request_id=request.id,
            kind="overdue",
            channel="sms",
            to_staff_id=team.backup.id,
            sent_at=NOW + 16 * MINUTE,
            status="pending",
        )
    )
    db_session.flush()

    clock.now = NOW + 17 * MINUTE
    _sweep(db_session, sms, clock)

    assert _sms_to(sms, team.backup.phone_e164 or "") == []
    assert len(_overdue_alerts(db_session)) == 1


def test_a_request_acknowledged_within_its_window_never_goes_overdue(
    tools: TestClient, db_session: Session, sms: FakeSms, clock: MovableClock, team: Team
) -> None:
    ref = _submit(tools, db_session, "today at five")
    owner_id = db_session.scalars(select(Owner.id).where(Owner.name == "Dispatch")).one()
    clock.now = NOW + 14 * MINUTE
    acknowledged = tools.post(
        f"/api/requests/{ref}/acknowledge",
        headers=_headers(team.on_duty),
        json={"owner_id": owner_id},
    )
    assert acknowledged.status_code == 200

    clock.now = NOW + 3 * timedelta(hours=1)
    _sweep(db_session, sms, clock)

    assert _queue(tools, team.on_duty) == {ref: False}
    assert _overdue_alerts(db_session) == []


def test_a_planned_request_goes_overdue_after_2_hours(
    tools: TestClient, db_session: Session, sms: FakeSms, clock: MovableClock, team: Team
) -> None:
    ref = _submit(tools, db_session, "tomorrow at seven")

    clock.now = NOW + timedelta(hours=2)
    _sweep(db_session, sms, clock)
    assert _queue(tools, team.on_duty) == {ref: False}
    assert _overdue_alerts(db_session) == []

    clock.now = NOW + timedelta(hours=2) + SECOND
    _sweep(db_session, sms, clock)
    assert _queue(tools, team.on_duty) == {ref: True}
    [body] = _sms_to(sms, team.backup.phone_e164 or "")
    assert body.startswith(f"Overdue: Planned request {ref} from Dale Kramer")


def test_the_ack_windows_are_the_offices_settings(
    tools: TestClient, db_session: Session, sms: FakeSms, clock: MovableClock, team: Team
) -> None:
    settings = db_session.get_one(Settings, 1)
    settings.ack_window_today_min = 5
    db_session.flush()
    ref = _submit(tools, db_session, "today at five")

    clock.now = NOW + 5 * MINUTE + SECOND
    _sweep(db_session, sms, clock)

    assert _queue(tools, team.on_duty) == {ref: True}
    assert len(_overdue_alerts(db_session)) == 1


def test_a_request_with_no_urgency_has_no_ack_window(
    tools: TestClient, db_session: Session, sms: FakeSms, clock: MovableClock, team: Team
) -> None:
    """Needed-by unknown → no Urgency → the spec gives no window (open question on #22)."""
    ref = _submit(tools, db_session, None)

    clock.now = NOW + timedelta(days=1)
    _sweep(db_session, sms, clock)

    assert _queue(tools, team.on_duty) == {ref: False}
    assert _overdue_alerts(db_session) == []


def test_a_coordinator_logged_request_also_goes_overdue(
    tools: TestClient, db_session: Session, sms: FakeSms, clock: MovableClock, team: Team
) -> None:
    dale = db_session.scalars(select(Foreman.id).where(Foreman.first_name == "Dale")).one()
    job_id = db_session.scalars(select(Job.id).where(Job.name == "Route 104 Widening")).one()
    logged = tools.post(
        "/api/requests",
        headers=_headers(team.on_duty),
        json={
            "foreman_id": dale,
            "job_id": job_id,
            "category": "Trucking",
            "need": "tri-axle dump trucks",
            "needed_by": "today at five",
        },
    )
    assert logged.status_code == 201
    ref = logged.json()["ref"]

    clock.now = NOW + 15 * MINUTE + SECOND
    _sweep(db_session, sms, clock)

    assert _queue(tools, team.on_duty) == {ref: True}
    assert len(_overdue_alerts(db_session)) == 1


def test_a_promoted_draft_s_window_starts_when_it_is_recorded(
    tools: TestClient, db_session: Session, sms: FakeSms, clock: MovableClock, team: Team
) -> None:
    dale = db_session.scalars(select(Foreman.id).where(Foreman.first_name == "Dale")).one()
    draft = Request(
        foreman_id=dale,
        job_id=None,
        job_spoken="the 104 job",
        category="Trucking",
        need="tri-axle dump trucks",
        needed_by_spoken="today at five",
        needed_by=datetime(2026, 11, 1, 22, 0, tzinfo=UTC),
        urgency="Today",
        status="Draft",
        source="ai_call",
        recorded_at=None,
    )
    db_session.add(draft)
    db_session.flush()
    clock.now = NOW + timedelta(hours=1)
    recorded = tools.post(
        f"/api/requests/{draft.ref_display}/record", headers=_headers(team.on_duty)
    )
    assert recorded.status_code == 200

    event = db_session.scalars(
        select(RequestEvent).where(RequestEvent.request_id == draft.id)
    ).one()
    assert (event.kind, event.before, event.after) == (
        "recorded",
        {"status": "Draft", "recorded_at": None, "ack_due_at": None},
        {
            "status": "Recorded",
            "recorded_at": "2026-11-01T21:04:00+00:00",
            "ack_due_at": "2026-11-01T21:19:00+00:00",
        },
    )

    clock.now = NOW + timedelta(hours=1) + 15 * MINUTE
    assert _queue(tools, team.on_duty) == {draft.ref_display: False}
    clock.now = NOW + timedelta(hours=1) + 15 * MINUTE + SECOND
    assert _queue(tools, team.on_duty) == {draft.ref_display: True}


def test_overnight_the_backup_is_texted_immediately(
    tools: TestClient, db_session: Session, sms: FakeSms, clock: MovableClock, team: Team
) -> None:
    """Spec §12: "Default v1: send immediately"; §4: 2 AM behaves exactly as 2 PM."""
    night_on_duty = _staff(db_session, "Lee Night", "+15855550197")
    night_backup = _staff(db_session, "Max Night", "+15855550196")
    _duty(db_session, MONDAY, night_on_duty, night_backup)
    clock.now = datetime(2026, 11, 2, 6, 50, tzinfo=UTC)  # Monday 1:50 AM in New York
    _submit(tools, db_session, "today at seven")

    clock.now += 15 * MINUTE + SECOND  # 2:05 AM
    _sweep(db_session, sms, clock)

    assert len(_sms_to(sms, "+15855550196")) == 1


def test_the_backup_is_the_one_on_the_roster_the_day_the_request_went_overdue(
    tools: TestClient, db_session: Session, sms: FakeSms, clock: MovableClock, team: Team
) -> None:
    monday_backup = _staff(db_session, "Max Monday", "+15855550196")
    _duty(db_session, MONDAY, team.on_duty, monday_backup)
    clock.now = datetime(2026, 11, 2, 4, 50, tzinfo=UTC)  # Sunday 11:50 PM in New York
    _submit(tools, db_session, "today at 11:59 pm")

    clock.now = datetime(2026, 11, 2, 5, 30, tzinfo=UTC)  # Monday 12:30 AM; due 12:05 AM
    _sweep(db_session, sms, clock)

    assert len(_sms_to(sms, "+15855550196")) == 1
    assert _sms_to(sms, team.backup.phone_e164 or "") == []


def test_no_backup_on_the_roster_is_a_failed_alert_shown_on_the_dashboard(
    tools: TestClient, db_session: Session, sms: FakeSms, clock: MovableClock
) -> None:
    pat = _staff(db_session, "Pat Lee", "+15855550199")
    _duty(db_session, SUNDAY, pat)
    ref = _submit(tools, db_session, "today at five")

    clock.now = NOW + 16 * MINUTE
    _sweep(db_session, sms, clock)
    _sweep(db_session, sms, clock)

    assert sms.sent == [sms.sent[0]]  # only the #21 Today SMS to Pat
    [alert] = _overdue_alerts(db_session)
    assert (alert.status, alert.to_staff_id, alert.detail) == (
        "failed",
        None,
        "No backup Coordinator for Sun, Nov 1",
    )
    failed = tools.get("/api/alerts/failed", headers=_headers(pat)).json()["alerts"]
    assert [(a["ref"], a["kind"], a["detail"]) for a in failed] == [
        (ref, "overdue", "No backup Coordinator for Sun, Nov 1")
    ]


def test_no_duty_roster_for_the_day_is_a_failed_alert(
    tools: TestClient, db_session: Session, sms: FakeSms, clock: MovableClock
) -> None:
    _submit(tools, db_session, "today at five")

    clock.now = NOW + 16 * MINUTE
    _sweep(db_session, sms, clock)

    [alert] = _overdue_alerts(db_session)
    assert (alert.status, alert.detail) == ("failed", "No backup Coordinator for Sun, Nov 1")


def test_a_backup_without_a_phone_is_a_failed_alert(
    tools: TestClient, db_session: Session, sms: FakeSms, clock: MovableClock
) -> None:
    pat = _staff(db_session, "Pat Lee", "+15855550199")
    sam = _staff(db_session, "Sam Ortiz", None)
    _duty(db_session, SUNDAY, pat, sam)
    _submit(tools, db_session, "today at five")

    clock.now = NOW + 16 * MINUTE
    _sweep(db_session, sms, clock)

    [alert] = _overdue_alerts(db_session)
    assert (alert.status, alert.to_staff_id, alert.detail) == (
        "failed",
        sam.id,
        "Sam Ortiz has no phone number",
    )


def test_a_provider_error_is_a_failed_alert_and_is_not_retried(
    tools: TestClient, db_session: Session, sms: FakeSms, clock: MovableClock, team: Team
) -> None:
    _submit(tools, db_session, "today at five")
    sms.fail = True

    clock.now = NOW + 16 * MINUTE
    _sweep(db_session, sms, clock)
    sms.fail = False
    clock.now = NOW + 17 * MINUTE
    _sweep(db_session, sms, clock)

    [alert] = _overdue_alerts(db_session)
    assert (alert.status, alert.detail) == ("failed", "SMS not sent: Twilio answered 400")
    assert _sms_to(sms, team.backup.phone_e164 or "") == []


def test_a_request_resolved_while_recorded_is_not_alerted(
    tools: TestClient, db_session: Session, sms: FakeSms, clock: MovableClock, team: Team
) -> None:
    ref = _submit(tools, db_session, "today at five")
    clock.now = NOW + 5 * MINUTE
    resolved = tools.post(
        f"/api/requests/{ref}/resolve",
        headers=_headers(team.on_duty),
        json={"outcome": "Denied", "explanation": "No trucks free"},
    )
    assert resolved.status_code == 200

    clock.now = NOW + 16 * MINUTE
    _sweep(db_session, sms, clock)

    assert _overdue_alerts(db_session) == []


def test_a_callback_request_goes_overdue_after_15_minutes_and_texts_the_backup(
    tools: TestClient, db_session: Session, sms: FakeSms, clock: MovableClock, team: Team
) -> None:
    """Spec J5 / §4: a Callback Request is Today with a 15-min window (#24 records it)."""
    created = tools.post(
        "/tools/create_callback_request",
        json={"reason": "the pump"},
        headers={"X-Tool-Secret": TOOL_SECRET, "X-Conversation-Id": CONVERSATION},
    )
    assert created.status_code == 200
    ref = created.json()["ref"]
    texted_on_creation = len(_sms_to(sms, team.backup.phone_e164 or ""))

    clock.now = NOW + 15 * MINUTE
    _sweep(db_session, sms, clock)
    assert _queue(tools, team.on_duty) == {ref: False}

    clock.now = NOW + 15 * MINUTE + SECOND
    _sweep(db_session, sms, clock)

    assert _queue(tools, team.on_duty) == {ref: True}
    assert _sms_to(sms, team.backup.phone_e164 or "")[texted_on_creation:] == [
        f"Overdue: Callback request {ref} from Dale Kramer, about: the pump. "
        "Recorded Sun, Nov 1, 3:04 PM, not Acknowledged"
    ]
