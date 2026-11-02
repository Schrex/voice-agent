"""`POST /tools/transfer_to_office` (ticket #25; spec J5 step 2, AC5.3; architecture §3.3).

Before the agent transfers, the office is told who is coming: a dashboard pop-up and an SMS to
the on-duty Coordinator. Twilio is replaced by a fake `SmsSender`.
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
from app.db.models import Alert, Call, DutyRoster, Job, Staff
from app.http.sms import get_sms_sender
from app.integrations.twilio_sms import SmsNotSent
from app.main import app
from app.services.roster import load_roster_file, seed_roster

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "elevenlabs"
SAMPLE_ROSTER = ROOT / "backend" / "seed" / "sample_roster.json"

HOOK_SECRET = "test-hook-secret"
TOOL_SECRET = "test-tool-secret"
# Sunday, November 1, 2026, 3:04 PM in New York.
NOW = datetime(2026, 11, 1, 20, 4, tzinfo=UTC)
TODAY_NY = date(2026, 11, 1)
# 2:10 AM in New York on Monday, November 2 (still Nov 2 local, Nov 2 UTC).
OVERNIGHT = datetime(2026, 11, 2, 7, 10, tzinfo=UTC)

ROSTERED = json.loads((FIXTURES / "call_start_rostered.json").read_text())
UNROSTERED = json.loads((FIXTURES / "call_start_unrostered.json").read_text())
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


@dataclass
class Now:
    at: datetime = NOW


@pytest.fixture
def sms() -> FakeSms:
    return FakeSms()


@pytest.fixture
def now() -> Now:
    return Now()


@pytest.fixture
def tools(
    client: TestClient,
    db_session: Session,
    sms: FakeSms,
    now: Now,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """Seeded roster, secrets set, movable clock, fake SMS, and Dale's call started."""
    monkeypatch.setenv("HOOK_SECRET", HOOK_SECRET)
    monkeypatch.setenv("TOOL_SECRET", TOOL_SECRET)
    monkeypatch.setenv("OFFICE_MAIN_NUMBER", "585-555-0100")
    seed_roster(db_session, load_roster_file(SAMPLE_ROSTER))
    app.dependency_overrides[get_clock] = lambda: lambda: now.at
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


def _job_id(session: Session, name: str) -> int:
    return session.scalars(select(Job.id).where(Job.name == name)).one()


def _transfer(
    client: TestClient, body: Any, conversation: str = CONVERSATION, secret: str = TOOL_SECRET
) -> Any:
    response = client.post(
        "/tools/transfer_to_office",
        json=body,
        headers={"X-Tool-Secret": secret, "X-Conversation-Id": conversation},
    )
    return response


def _alerts(session: Session) -> list[Alert]:
    return list(session.scalars(select(Alert).order_by(Alert.id)))


def _call_id(session: Session) -> int:
    return session.scalars(select(Call.id).where(Call.conversation_id == CONVERSATION)).one()


def test_ac5_3_transfer_texts_the_on_duty_coordinator_and_raises_a_pop_up(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    pat = _staff(db_session, "Pat Lee", "+15855550199")
    backup = _staff(db_session, "Sam Ortiz", "+15855550198")
    _on_duty(db_session, TODAY_NY, pat, backup)

    response = _transfer(
        tools,
        {
            "reason": "tri-axle dump trucks",
            "job_id": _job_id(db_session, "Route 104 Widening"),
            "job_spoken": "the 104 job",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    text = "Incoming transfer: Dale Kramer, Route 104 Widening, about: tri-axle dump trucks"
    # Only the on-duty Coordinator, not the backup (spec J5 step 2).
    assert sms.sent == [("+15855550199", text)]
    popup, texted = _alerts(db_session)
    call_id = _call_id(db_session)
    assert (popup.kind, popup.channel, popup.call_id, popup.request_id) == (
        "transfer",
        "popup",
        call_id,
        None,
    )
    assert (popup.status, popup.to_staff_id, popup.seen_at, popup.sent_at) == (
        "sent",
        None,
        None,
        NOW,
    )
    assert popup.detail == text
    assert (texted.kind, texted.channel, texted.call_id, texted.to_staff_id) == (
        "transfer",
        "sms",
        call_id,
        pat.id,
    )
    assert (texted.status, texted.provider_id, texted.sent_at) == (
        "sent",
        "SM" + "0" * 31 + "1",
        NOW,
    )


def test_ac5_1_no_reason_and_no_job_is_still_told_as_not_stated(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    _on_duty(db_session, TODAY_NY, _staff(db_session, "Pat Lee", "+15855550199"))

    response = _transfer(tools, {})

    assert response.json() == {"ok": True}
    assert sms.sent == [
        ("+15855550199", "Incoming transfer: Dale Kramer, not stated, about: not stated")
    ]


def test_a_job_not_on_the_active_list_is_quoted_as_said(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    _on_duty(db_session, TODAY_NY, _staff(db_session, "Pat Lee", "+15855550199"))

    _transfer(tools, {"job_spoken": "the quarry", "reason": "a loader"})

    assert sms.sent[0][1] == (
        "Incoming transfer: Dale Kramer, “the quarry” (Unmatched), about: a loader"
    )


def test_an_inactive_job_id_is_not_named(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    _on_duty(db_session, TODAY_NY, _staff(db_session, "Pat Lee", "+15855550199"))
    job = db_session.scalars(select(Job).where(Job.name == "Route 104 Widening")).one()
    job.active = False
    db_session.flush()

    _transfer(tools, {"job_id": job.id, "job_spoken": "the 104 job"})

    assert sms.sent[0][1] == (
        "Incoming transfer: Dale Kramer, “the 104 job” (Unmatched), about: not stated"
    )


def test_no_duty_roster_still_raises_the_pop_up_and_records_a_failed_sms(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    response = _transfer(tools, {"reason": "a loader"})

    assert response.json() == {"ok": True}
    assert sms.sent == []
    popup, texted = _alerts(db_session)
    assert (popup.channel, popup.status) == ("popup", "sent")
    assert (texted.channel, texted.status, texted.to_staff_id) == ("sms", "failed", None)
    assert texted.detail == "No on-duty Coordinator for Sun, Nov 1"


def test_on_duty_coordinator_without_a_phone_is_a_failed_sms(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    pat = _staff(db_session, "Pat Lee", None)
    _on_duty(db_session, TODAY_NY, pat)

    assert _transfer(tools, {}).json() == {"ok": True}

    _, texted = _alerts(db_session)
    assert (texted.status, texted.to_staff_id, texted.detail) == (
        "failed",
        pat.id,
        "Pat Lee has no phone number",
    )


def test_provider_error_is_a_failed_sms_and_the_agent_still_gets_ok(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    _on_duty(db_session, TODAY_NY, _staff(db_session, "Pat Lee", "+15855550199"))
    sms.fail = True

    assert _transfer(tools, {}).json() == {"ok": True}

    _, texted = _alerts(db_session)
    assert (texted.status, texted.detail) == ("failed", "SMS not sent: Twilio answered 400")


def test_asking_again_on_the_same_call_does_not_text_or_pop_up_twice(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    _on_duty(db_session, TODAY_NY, _staff(db_session, "Pat Lee", "+15855550199"))

    assert _transfer(tools, {"reason": "a loader"}).json() == {"ok": True}
    assert _transfer(tools, {"reason": "a loader"}).json() == {"ok": True}

    assert len(sms.sent) == 1
    assert len(_alerts(db_session)) == 2


def test_overnight_transfer_behaves_as_by_day_with_that_dates_on_duty_coordinator(
    tools: TestClient, db_session: Session, sms: FakeSms, now: Now
) -> None:
    """Spec §4: a Transfer at 2 AM behaves exactly as at 2 PM (24/7 single mode)."""
    _on_duty(db_session, TODAY_NY, _staff(db_session, "Pat Lee", "+15855550199"))
    _on_duty(db_session, date(2026, 11, 2), _staff(db_session, "Sam Ortiz", "+15855550198"))
    now.at = OVERNIGHT

    assert _transfer(tools, {}).json() == {"ok": True}

    assert [to for to, _ in sms.sent] == ["+15855550198"]


def test_unrostered_caller_is_refused_and_nothing_is_written(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    _on_duty(db_session, TODAY_NY, _staff(db_session, "Pat Lee", "+15855550199"))
    started = tools.post(
        "/hooks/call-start", json=UNROSTERED, headers={"X-Hook-Secret": HOOK_SECRET}
    )
    assert started.status_code == 200

    rejected = _transfer(tools, {}, conversation=UNROSTERED["conversation_id"])
    unknown = _transfer(tools, {}, conversation="conv_never_started")

    assert (rejected.status_code, unknown.status_code) == (403, 403)
    assert sms.sent == [] and _alerts(db_session) == []


def test_bad_tool_secret_is_refused_and_nothing_is_written(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    _on_duty(db_session, TODAY_NY, _staff(db_session, "Pat Lee", "+15855550199"))

    assert _transfer(tools, {}, secret="wrong").status_code == 401
    assert sms.sent == [] and _alerts(db_session) == []


def test_a_malformed_body_is_a_speakable_error_and_nothing_is_written(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    _on_duty(db_session, TODAY_NY, _staff(db_session, "Pat Lee", "+15855550199"))

    response = _transfer(tools, {"job_id": "fourteen"})

    assert response.status_code == 200
    assert response.json() == {"error": "The office could not be told you are coming."}
    assert sms.sent == [] and _alerts(db_session) == []
