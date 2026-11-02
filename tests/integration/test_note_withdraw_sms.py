"""SMS to the on-duty Coordinator for an urgent note and a phone withdrawal (#21: "urgent notes
(17) and withdrawals (20) text too"; spec AC3.5 "the coordinator is alerted", AC4.1 "the
coordinator is notified").

Twilio is replaced by a fake `SmsSender`; the alerts table records what was sent (or why not).
"""

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import get_clock
from app.db.models import Alert, Call, DutyRoster, Job, Request, RequestNote, Staff
from app.domain.lifecycle import Status
from app.http.sms import get_sms_sender
from app.integrations.twilio_sms import SmsNotSent
from app.main import app
from app.services.calls import Caller
from app.services.requests import NewItem, submit_requests
from app.services.roster import load_roster_file, seed_roster

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "elevenlabs"
SAMPLE_ROSTER = ROOT / "backend" / "seed" / "sample_roster.json"

HOOK_SECRET = "test-hook-secret"
TOOL_SECRET = "test-tool-secret"
# Sunday, November 1, 2026, 3:04 PM in New York.
NOW = datetime(2026, 11, 1, 20, 4, tzinfo=UTC)
TODAY_NY = date(2026, 11, 1)

ROSTERED = json.loads((FIXTURES / "call_start_rostered.json").read_text())
CONVERSATION = ROSTERED["conversation_id"]
HEADERS = {"X-Tool-Secret": TOOL_SECRET, "X-Conversation-Id": CONVERSATION}


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
    seed_roster(db_session, load_roster_file(SAMPLE_ROSTER))
    app.dependency_overrides[get_clock] = lambda: lambda: NOW
    app.dependency_overrides[get_sms_sender] = lambda: sms
    started = client.post(
        "/hooks/call-start", json=ROSTERED, headers={"X-Hook-Secret": HOOK_SECRET}
    )
    assert started.status_code == 200
    yield client


def _on_duty(session: Session, phone: str | None = "+15855550190") -> Staff:
    staff = Staff(
        id=uuid.uuid4(), name="Pat Lee", email=f"{uuid.uuid4().hex}@example.com", role="coordinator"
    )
    staff.phone_e164 = phone
    session.add(staff)
    session.flush()
    session.add(DutyRoster(day=TODAY_NY, on_duty_staff_id=staff.id))
    session.flush()
    return staff


def _record(session: Session) -> str:
    """A Recorded Planned Request of Dale's (no Today SMS of its own)."""
    call = session.scalars(select(Call).where(Call.conversation_id == CONVERSATION)).one()
    assert call.foreman_id is not None
    job_id = session.scalars(select(Job.id).where(Job.name == "Route 104 Widening")).one()
    [recorded] = submit_requests(
        session,
        caller=Caller(call_id=call.id, foreman_id=call.foreman_id),
        items=[
            NewItem(
                job_id=job_id,
                job_spoken="the 104 job",
                category="Trucking",
                need="tri-axle dump trucks",
                quantity=None,
                unit=None,
                needed_by_spoken="tomorrow at seven",
            )
        ],
        now=NOW,
    )
    return recorded.ref


def _alerts(session: Session, kind: str) -> list[Alert]:
    return list(session.scalars(select(Alert).where(Alert.kind == kind).order_by(Alert.id)))


def _note(client: TestClient, ref: str, urgent: bool) -> Any:
    body = {"ref": ref, "text": "need an answer today", "urgent": urgent}
    response = client.post("/tools/add_note", json=body, headers=HEADERS)
    assert response.status_code == 200
    return response.json()


def _withdraw(client: TestClient, ref: str) -> Any:
    response = client.post("/tools/withdraw_request", json={"ref": ref}, headers=HEADERS)
    assert response.status_code == 200
    return response.json()


def test_ac3_5_an_urgent_note_texts_the_on_duty_coordinator(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    staff = _on_duty(db_session)
    ref = _record(db_session)

    assert _note(tools, ref, urgent=True) == {"ok": True}

    assert sms.sent == [
        (
            "+15855550190",
            f"Urgent note on {ref} from Dale Kramer, Route 104 Widening (tri-axle dump trucks): "
            "“need an answer today”",
        )
    ]
    [alert] = _alerts(db_session, "urgent_note")
    assert (alert.status, alert.channel, alert.to_staff_id) == ("sent", "sms", staff.id)
    assert alert.provider_id is not None


def test_each_urgent_note_texts_once_and_a_plain_note_texts_nobody(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    _on_duty(db_session)
    ref = _record(db_session)

    _note(tools, ref, urgent=False)
    assert sms.sent == []
    _note(tools, ref, urgent=True)
    _note(tools, ref, urgent=True)

    assert len(sms.sent) == 2
    assert len(_alerts(db_session, "urgent_note")) == 2


def test_no_one_on_duty_records_a_failed_alert_and_the_note_is_kept(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    ref = _record(db_session)

    assert _note(tools, ref, urgent=True) == {"ok": True}

    assert sms.sent == []
    [alert] = _alerts(db_session, "urgent_note")
    assert alert.status == "failed"
    assert alert.detail == "No on-duty Coordinator for Sun, Nov 1"
    assert db_session.scalars(select(RequestNote.text)).all() == ["need an answer today"]


def test_ac4_1_an_applied_withdrawal_texts_the_on_duty_coordinator_once(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    staff = _on_duty(db_session)
    ref = _record(db_session)

    assert _withdraw(tools, ref) == {"applied": True}
    _withdraw(tools, ref)  # asked again: Resolved now, flagged, no second text

    assert sms.sent == [
        (
            "+15855550190",
            f"Withdrawn by foreman: {ref} from Dale Kramer, Route 104 Widening: "
            "tri-axle dump trucks, needed by Mon, Nov 2, 7:00 AM",
        )
    ]
    [alert] = _alerts(db_session, "withdrawn")
    assert (alert.status, alert.to_staff_id) == ("sent", staff.id)


def test_a_withdrawal_that_is_only_flagged_texts_nobody(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    _on_duty(db_session)
    ref = _record(db_session)
    request = db_session.scalars(select(Request).where(Request.ref == int(ref[2:]))).one()
    request.status = Status.IN_PROGRESS.value
    db_session.flush()

    assert _withdraw(tools, ref) == {"applied": False}

    assert sms.sent == []
    assert _alerts(db_session, "withdrawn") == []


def test_a_provider_error_is_a_failed_alert_and_the_withdrawal_stands(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    _on_duty(db_session)
    ref = _record(db_session)
    sms.fail = True

    assert _withdraw(tools, ref) == {"applied": True}

    [alert] = _alerts(db_session, "withdrawn")
    assert alert.status == "failed"
    assert alert.detail == "SMS not sent: Twilio answered 400"
    request = db_session.scalars(select(Request).where(Request.ref == int(ref[2:]))).one()
    assert (request.status, request.outcome) == ("Resolved", "Withdrawn")
