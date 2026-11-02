"""`POST /tools/start_emergency` (ticket #26; spec J6 steps 3-4, AC6.2; architecture §3.3).

On an Emergency the backend records an Emergency Request, texts every Coordinator and raises a
dashboard pop-up, all before the agent transfers. Twilio is replaced by a fake `SmsSender`.
"""

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import get_clock
from app.db.models import Alert, Call, CallRequest, Job, Request, RequestEvent, Staff
from app.http.sms import get_sms_sender
from app.integrations.twilio_sms import SmsNotSent
from app.main import app
from app.services.alerts import open_popups
from app.services.roster import load_roster_file, seed_roster

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "elevenlabs"
SAMPLE_ROSTER = ROOT / "backend" / "seed" / "sample_roster.json"

HOOK_SECRET = "test-hook-secret"
TOOL_SECRET = "test-tool-secret"
# Sunday, November 1, 2026, 3:04 PM in New York.
NOW = datetime(2026, 11, 1, 20, 4, tzinfo=UTC)
# 2:10 AM in New York on Monday, November 2.
OVERNIGHT = datetime(2026, 11, 2, 7, 10, tzinfo=UTC)

ROSTERED = json.loads((FIXTURES / "call_start_rostered.json").read_text())
UNROSTERED = json.loads((FIXTURES / "call_start_unrostered.json").read_text())
CONVERSATION = ROSTERED["conversation_id"]
NOT_RECORDED = {"error": "The emergency could not be recorded."}


@dataclass
class FakeSms:
    sent: list[tuple[str, str]] = field(default_factory=list)
    fail_to: set[str] = field(default_factory=set)

    def send(self, to: str, body: str) -> str:
        if to in self.fail_to:
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
    staff = Staff(id=uuid.uuid4(), name=name, email=f"{uuid.uuid4().hex}@example.com")
    staff.phone_e164 = phone
    session.add(staff)
    session.flush()
    return staff


def _job_id(session: Session, name: str) -> int:
    return session.scalars(select(Job.id).where(Job.name == name)).one()


def _emergency(
    client: TestClient, body: Any, conversation: str = CONVERSATION, secret: str = TOOL_SECRET
) -> Any:
    return client.post(
        "/tools/start_emergency",
        json=body,
        headers={"X-Tool-Secret": secret, "X-Conversation-Id": conversation},
    )


def _alerts(session: Session) -> list[Alert]:
    session.expire_all()
    return list(session.scalars(select(Alert).order_by(Alert.id)))


def _requests(session: Session) -> list[Request]:
    session.expire_all()
    return list(session.scalars(select(Request).order_by(Request.id)))


def _call_id(session: Session) -> int:
    return session.scalars(select(Call.id).where(Call.conversation_id == CONVERSATION)).one()


def test_ac6_2_emergency_request_is_recorded_and_every_coordinator_is_texted(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    """One Staff role (ADR 0006): every staff member is a Coordinator, so all are texted."""
    pat = _staff(db_session, "Pat Lee", "+15855550199")
    sam = _staff(db_session, "Sam Ortiz", "+15855550198")

    response = _emergency(
        tools,
        {
            "summary": "we hit a gas line",
            "job_id": _job_id(db_session, "Route 104 Widening"),
            "job_spoken": "the 104 job",
        },
    )

    assert response.status_code == 200
    [request] = _requests(db_session)
    assert response.json() == {"ref": request.ref_display}
    assert (request.urgency, request.status, request.source) == ("Emergency", "Recorded", "ai_call")
    assert (request.need, request.job_spoken) == ("we hit a gas line", "the 104 job")
    assert request.job_id == _job_id(db_session, "Route 104 Widening")
    assert request.recorded_at == NOW
    text = "EMERGENCY call from Dale Kramer, Route 104 Widening: we hit a gas line"
    assert sorted(sms.sent) == [("+15855550198", text), ("+15855550199", text)]
    texted = [a for a in _alerts(db_session) if a.channel == "sms"]
    assert {(a.kind, a.to_staff_id, a.status, a.request_id) for a in texted} == {
        ("emergency", pat.id, "sent", request.id),
        ("emergency", sam.id, "sent", request.id),
    }
    assert all(a.provider_id and a.call_id == _call_id(db_session) for a in texted)


def test_emergency_raises_a_dashboard_pop_up_with_the_same_text(
    tools: TestClient, db_session: Session
) -> None:
    _staff(db_session, "Pat Lee", "+15855550199")

    _emergency(tools, {"summary": "trench collapse, a man is hurt"})

    [popup] = [a for a in _alerts(db_session) if a.channel == "popup"]
    assert (popup.kind, popup.to_staff_id, popup.status, popup.seen_at) == (
        "emergency",
        None,
        "sent",
        None,
    )
    text = "EMERGENCY call from Dale Kramer, not stated: trench collapse, a man is hurt"
    assert popup.detail == text
    assert popup.call_id == _call_id(db_session)
    assert popup.request_id == _requests(db_session)[0].id
    [shown] = open_popups(db_session)
    assert (shown.kind, shown.text) == ("emergency", text)


def test_emergency_is_recorded_by_the_agent_with_its_event_and_call_link(
    tools: TestClient, db_session: Session
) -> None:
    _emergency(tools, {"summary": "fire in the equipment shed", "job_spoken": "the Fairport job"})

    [request] = _requests(db_session)
    [event] = db_session.scalars(select(RequestEvent).where(RequestEvent.request_id == request.id))
    assert (event.kind, event.actor_type, event.actor_id, event.at) == (
        "recorded",
        "agent",
        None,
        NOW,
    )
    assert event.after is not None
    assert event.after["urgency"] == "Emergency"
    link = db_session.scalars(select(CallRequest).where(CallRequest.request_id == request.id)).one()
    assert (link.call_id, link.relation) == (_call_id(db_session), "created")
    assert (request.job_id, request.job_spoken) == (None, "the Fairport job")


def test_an_emergency_gets_the_today_ack_window(tools: TestClient, db_session: Session) -> None:
    """Product owner decision on #22/#26: an Emergency nobody acknowledges goes Overdue."""
    _emergency(tools, {"summary": "we hit a gas line"})

    [request] = _requests(db_session)
    assert request.ack_due_at == NOW + timedelta(minutes=15)


def test_asking_again_on_the_same_call_returns_the_same_ref_and_texts_nobody_twice(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    _staff(db_session, "Pat Lee", "+15855550199")

    first = _emergency(tools, {"summary": "we hit a gas line"})
    again = _emergency(tools, {"summary": "gas everywhere"})

    assert "ref" in first.json()
    assert again.json() == first.json()
    assert len(_requests(db_session)) == 1
    assert len(sms.sent) == 1
    assert len(_alerts(db_session)) == 2  # one SMS, one pop-up


def test_a_coordinator_without_a_phone_is_a_failed_alert_and_the_others_are_still_texted(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    pat = _staff(db_session, "Pat Lee", None)
    _staff(db_session, "Sam Ortiz", "+15855550198")

    response = _emergency(tools, {"summary": "we hit a gas line"})

    assert "ref" in response.json()
    assert [to for to, _ in sms.sent] == ["+15855550198"]
    [failed] = [a for a in _alerts(db_session) if a.status == "failed"]
    assert (failed.to_staff_id, failed.detail) == (pat.id, "Pat Lee has no phone number")


def test_a_provider_error_is_a_failed_alert_and_the_tool_still_answers_with_the_ref(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    _staff(db_session, "Pat Lee", "+15855550199")
    sms.fail_to.add("+15855550199")

    response = _emergency(tools, {"summary": "we hit a gas line"})

    assert "ref" in response.json()
    [texted] = [a for a in _alerts(db_session) if a.channel == "sms"]
    assert (texted.status, texted.detail) == ("failed", "SMS not sent: Twilio answered 400")


def test_no_coordinator_on_the_staff_list_is_one_failed_alert_shown_as_not_sent(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    response = _emergency(tools, {"summary": "we hit a gas line"})

    assert "ref" in response.json()
    assert sms.sent == []
    [texted] = [a for a in _alerts(db_session) if a.channel == "sms"]
    assert (texted.kind, texted.status, texted.to_staff_id, texted.detail) == (
        "emergency",
        "failed",
        None,
        "No Coordinator on the staff list",
    )


def test_an_emergency_at_2_am_texts_every_coordinator_as_by_day(
    tools: TestClient, db_session: Session, sms: FakeSms, now: Now
) -> None:
    """Spec §4: "Emergencies still transfer to the office line and SMS all coordinators at any
    hour." No duty roster is needed: every Coordinator is texted."""
    _staff(db_session, "Pat Lee", "+15855550199")
    now.at = OVERNIGHT

    _emergency(tools, {"summary": "we hit a gas line"})

    assert [to for to, _ in sms.sent] == ["+15855550199"]
    assert _requests(db_session)[0].recorded_at == OVERNIGHT


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="no summary"),
        pytest.param({"summary": "  "}, id="blank summary"),
        pytest.param({"summary": 12}, id="summary not text"),
        pytest.param({"summary": "gas", "job_id": "14"}, id="job_id not a number"),
        pytest.param([], id="not an object"),
    ],
)
def test_a_bad_body_is_a_speakable_error_and_nothing_is_written(
    tools: TestClient, db_session: Session, sms: FakeSms, body: Any
) -> None:
    response = _emergency(tools, body)

    assert response.status_code == 200
    assert response.json() == NOT_RECORDED
    assert _requests(db_session) == []
    assert _alerts(db_session) == []
    assert sms.sent == []


def test_a_foreman_id_in_the_body_is_ignored(tools: TestClient, db_session: Session) -> None:
    _emergency(tools, {"summary": "we hit a gas line", "foreman_id": 999999})

    [request] = _requests(db_session)
    call = db_session.get_one(Call, _call_id(db_session))
    assert request.foreman_id == call.foreman_id


def test_a_bad_secret_is_401_and_nothing_is_written(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    response = _emergency(tools, {"summary": "we hit a gas line"}, secret="wrong")

    assert response.status_code == 401
    assert _requests(db_session) == []
    assert _alerts(db_session) == []


@pytest.mark.parametrize(
    "conversation",
    [
        pytest.param("conv_never_started", id="unknown conversation"),
        pytest.param(UNROSTERED["conversation_id"], id="caller not on the Roster"),
    ],
)
def test_an_unknown_or_rejected_conversation_is_403_and_nothing_is_written(
    tools: TestClient, db_session: Session, sms: FakeSms, conversation: str
) -> None:
    tools.post("/hooks/call-start", json=UNROSTERED, headers={"X-Hook-Secret": HOOK_SECRET})

    response = _emergency(tools, {"summary": "we hit a gas line"}, conversation=conversation)

    assert response.status_code == 403
    assert _requests(db_session) == []
    assert _alerts(db_session) == []
    assert sms.sent == []
