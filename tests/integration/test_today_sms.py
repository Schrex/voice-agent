"""SMS to the on-duty Coordinator for a new Today Request (ticket #21; spec J1 step 8, AC1.9).

Twilio is replaced by a fake `SmsSender`; the alerts table records what was sent (or why not).
"""

import json
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import get_clock
from app.db.models import Alert, DutyRoster, Job, Request, Staff
from app.http.sms import get_sms_sender
from app.integrations.twilio_sms import SmsNotSent
from app.main import app
from app.services.alerts import alert_new_today
from app.services.roster import load_roster_file, seed_roster

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "elevenlabs"
SAMPLE_ROSTER = ROOT / "backend" / "seed" / "sample_roster.json"

HOOK_SECRET = "test-hook-secret"
TOOL_SECRET = "test-tool-secret"
JWT_SECRET = "test-jwt-secret-at-least-32-bytes-long"
# Sunday, November 1, 2026, 3:04 PM in New York.
NOW = datetime(2026, 11, 1, 20, 4, tzinfo=UTC)
TODAY_NY = date(2026, 11, 1)

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


@pytest.fixture
def sms() -> FakeSms:
    return FakeSms()


@pytest.fixture
def tools(
    client: TestClient, db_session: Session, sms: FakeSms, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """Seeded roster, secrets set, frozen clock, fake SMS, and Dale's call started."""
    monkeypatch.setenv("HOOK_SECRET", HOOK_SECRET)
    monkeypatch.setenv("TOOL_SECRET", TOOL_SECRET)
    monkeypatch.setenv("OFFICE_MAIN_NUMBER", "585-555-0100")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", JWT_SECRET)
    seed_roster(db_session, load_roster_file(SAMPLE_ROSTER))
    app.dependency_overrides[get_clock] = lambda: lambda: NOW
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


def _on_duty(session: Session, day: date, on_duty: Staff, backup: Staff | None = None) -> None:
    session.add(
        DutyRoster(
            day=day,
            on_duty_staff_id=on_duty.id,
            backup_staff_id=None if backup is None else backup.id,
        )
    )
    session.flush()


def _submit(client: TestClient, session: Session, needed_by_spoken: str) -> Any:
    job_id = session.scalars(select(Job.id).where(Job.name == "Route 104 Widening")).one()
    item = {
        "job_id": job_id,
        "job_spoken": "the 104 job",
        "category": "Trucking",
        "need": "tri-axle dump trucks",
        "quantity": 3,
        "unit": "trucks",
        "needed_by_spoken": needed_by_spoken,
    }
    response = client.post(
        "/tools/submit_requests",
        json={"items": [item]},
        headers={"X-Tool-Secret": TOOL_SECRET, "X-Conversation-Id": CONVERSATION},
    )
    assert response.status_code == 200
    return response.json()


def _alerts(session: Session) -> list[Alert]:
    return list(session.scalars(select(Alert).order_by(Alert.id)))


def _headers(staff: Staff) -> dict[str, str]:
    claims = {"sub": str(staff.id), "aud": "authenticated", "exp": int(time.time()) + 3600}
    return {"Authorization": f"Bearer {jwt.encode(claims, JWT_SECRET, algorithm='HS256')}"}


def test_a_recorded_today_request_texts_the_on_duty_coordinator_once(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    pat = _staff(db_session, "Pat Lee", "+15855550199")
    backup = _staff(db_session, "Sam Ortiz", "+15855550198")
    _on_duty(db_session, TODAY_NY, pat, backup)

    [result] = _submit(tools, db_session, "today at five")

    assert result["urgency"] == "Today"
    [(to, body)] = sms.sent
    assert to == "+15855550199"
    assert body == (
        f"Today request {result['ref']} from Dale Kramer, Route 104 Widening: "
        "tri-axle dump trucks, 3 trucks, needed by Sun, Nov 1, 5:00 PM"
    )
    [alert] = _alerts(db_session)
    request = db_session.scalars(select(Request)).one()
    assert (alert.request_id, alert.kind, alert.channel, alert.to_staff_id) == (
        request.id,
        "today_new",
        "sms",
        pat.id,
    )
    assert (alert.status, alert.provider_id, alert.sent_at) == ("sent", "SM" + "0" * 31 + "1", NOW)


def test_retrying_the_trigger_does_not_resend(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    _on_duty(db_session, TODAY_NY, _staff(db_session, "Pat Lee", "+15855550199"))
    [result] = _submit(tools, db_session, "today at five")

    alert_new_today(db_session, sms, ref=result["ref"], now=NOW)
    alert_new_today(db_session, sms, ref=result["ref"], now=NOW)

    assert len(sms.sent) == 1
    assert len(_alerts(db_session)) == 1


def test_a_planned_request_sends_no_sms(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    _on_duty(db_session, TODAY_NY, _staff(db_session, "Pat Lee", "+15855550199"))

    [result] = _submit(tools, db_session, "tomorrow at seven")

    assert result["urgency"] == "Planned"
    assert sms.sent == []
    assert _alerts(db_session) == []


def test_no_duty_roster_for_today_records_a_failed_alert_and_the_request_is_still_recorded(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    # Someone is on duty tomorrow, nobody today.
    _on_duty(db_session, date(2026, 11, 2), _staff(db_session, "Pat Lee", "+15855550199"))

    [result] = _submit(tools, db_session, "today at five")

    assert result["ref"].startswith("R-")
    assert sms.sent == []
    [alert] = _alerts(db_session)
    assert (alert.kind, alert.channel, alert.to_staff_id, alert.status) == (
        "today_new",
        "sms",
        None,
        "failed",
    )
    assert alert.detail == "No on-duty Coordinator for Sun, Nov 1"


def test_failed_alert_is_visible_on_the_dashboard(tools: TestClient, db_session: Session) -> None:
    viewer = _staff(db_session, "Pat Lee", None)
    [result] = _submit(tools, db_session, "today at five")

    response = tools.get("/api/alerts/failed", headers=_headers(viewer))

    assert response.status_code == 200
    assert response.json() == {
        "alerts": [
            {
                "ref": result["ref"],
                "kind": "today_new",
                "channel": "sms",
                "at": "2026-11-01T20:04:00Z",
                "detail": "No on-duty Coordinator for Sun, Nov 1",
            }
        ]
    }


def test_failed_alerts_of_requests_no_longer_open_leave_the_dashboard(
    tools: TestClient, db_session: Session
) -> None:
    viewer = _staff(db_session, "Pat Lee", None)
    _submit(tools, db_session, "today at five")
    request = db_session.scalars(select(Request)).one()
    request.status = "Resolved"
    request.outcome = "Withdrawn"
    request.explanation = "test"
    request.resolved_at = NOW
    db_session.flush()

    response = tools.get("/api/alerts/failed", headers=_headers(viewer))

    assert response.json() == {"alerts": []}


def test_failed_alerts_need_a_staff_token(tools: TestClient) -> None:
    assert tools.get("/api/alerts/failed").status_code == 401


def test_on_duty_coordinator_without_a_phone_is_a_failed_alert(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    _on_duty(db_session, TODAY_NY, _staff(db_session, "Pat Lee", None))

    _submit(tools, db_session, "today at five")

    [alert] = _alerts(db_session)
    assert alert.status == "failed"
    assert alert.detail == "Pat Lee has no phone number"
    assert sms.sent == []


def test_provider_error_is_a_failed_alert_and_the_request_is_still_recorded(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    pat = _staff(db_session, "Pat Lee", "+15855550199")
    _on_duty(db_session, TODAY_NY, pat)
    sms.fail = True

    [result] = _submit(tools, db_session, "today at five")

    assert result["urgency"] == "Today"
    [alert] = _alerts(db_session)
    assert (alert.to_staff_id, alert.status) == (pat.id, "failed")
    assert alert.detail == "SMS not sent: Twilio answered 400"
    assert db_session.scalars(select(Request)).one().status == "Recorded"
