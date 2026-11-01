"""Callback Request (ticket #24; spec J5 "Callback Request", AC5.4).

The Foreman asks to be called back; the agent calls `create_callback_request` with the optional
reason. The backend records a Callback Request (urgency Today) and texts the on-duty and the
backup Coordinator once each. Twilio is replaced by a fake `SmsSender`.
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
from app.db.models import (
    Alert,
    Call,
    CallRequest,
    DutyRoster,
    Foreman,
    Request,
    RequestEvent,
    Staff,
)
from app.http.sms import get_sms_sender
from app.integrations.twilio_sms import SmsNotSent
from app.main import app
from app.services.alerts import alert_callback
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
CALLER = ROSTERED["caller_id"]
TOOL_HEADERS = {"X-Tool-Secret": TOOL_SECRET, "X-Conversation-Id": CONVERSATION}


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


def _callback(client: TestClient, body: Any) -> Any:
    response = client.post("/tools/create_callback_request", json=body, headers=TOOL_HEADERS)
    assert response.status_code == 200
    return response.json()


def _alerts(session: Session) -> list[Alert]:
    return list(session.scalars(select(Alert).order_by(Alert.id)))


def _headers(staff: Staff) -> dict[str, str]:
    claims = {"sub": str(staff.id), "aud": "authenticated", "exp": int(time.time()) + 3600}
    return {"Authorization": f"Bearer {jwt.encode(claims, JWT_SECRET, algorithm='HS256')}"}


def test_a_callback_request_is_recorded_today_for_the_callers_foreman(
    tools: TestClient, db_session: Session
) -> None:
    result = _callback(tools, {"reason": "the pump on the sewer job"})

    request = db_session.scalars(select(Request)).one()
    assert result == {"ref": request.ref_display}
    dale = db_session.scalars(select(Foreman).where(Foreman.first_name == "Dale")).one()
    assert (request.foreman_id, request.category, request.need) == (
        dale.id,
        "Callback",
        "the pump on the sewer job",
    )
    assert (request.urgency, request.status, request.source, request.recorded_at) == (
        "Today",
        "Recorded",
        "ai_call",
        NOW,
    )
    assert (request.job_id, request.job_spoken, request.needed_by, request.quantity) == (
        None,
        "",
        None,
        None,
    )
    [event] = db_session.scalars(select(RequestEvent)).all()
    assert (event.actor_type, event.kind, event.at) == ("agent", "recorded", NOW)
    assert event.after is not None
    assert event.after["category"] == "Callback"
    assert event.after["urgency"] == "Today"
    call = db_session.scalars(select(Call).where(Call.conversation_id == CONVERSATION)).one()
    [link] = db_session.scalars(select(CallRequest)).all()
    assert (link.call_id, link.request_id, link.relation) == (call.id, request.id, "created")


def test_the_on_duty_and_the_backup_coordinator_are_each_texted_once(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    """AC5.4 (I): both texts sent once."""
    pat = _staff(db_session, "Pat Lee", "+15855550199")
    sam = _staff(db_session, "Sam Ortiz", "+15855550198")
    _on_duty(db_session, TODAY_NY, pat, sam)

    ref = _callback(tools, {"reason": "the pump on the sewer job"})["ref"]

    text = f"Callback request {ref} from Dale Kramer ({CALLER}), about: the pump on the sewer job"
    assert sms.sent == [("+15855550199", text), ("+15855550198", text)]
    request = db_session.scalars(select(Request)).one()
    alerts = _alerts(db_session)
    assert [(a.request_id, a.kind, a.channel, a.to_staff_id, a.status) for a in alerts] == [
        (request.id, "callback", "sms", pat.id, "sent"),
        (request.id, "callback", "sms", sam.id, "sent"),
    ]
    assert [a.provider_id for a in alerts] == ["SM" + "0" * 31 + "1", "SM" + "0" * 31 + "2"]
    assert {a.sent_at for a in alerts} == {NOW}


def test_retrying_the_trigger_does_not_resend(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    _on_duty(
        db_session,
        TODAY_NY,
        _staff(db_session, "Pat Lee", "+15855550199"),
        _staff(db_session, "Sam Ortiz", "+15855550198"),
    )
    ref = _callback(tools, {"reason": "the pump"})["ref"]

    alert_callback(db_session, sms, ref=ref, now=NOW)
    alert_callback(db_session, sms, ref=ref, now=NOW)

    assert len(sms.sent) == 2
    assert len(_alerts(db_session)) == 2


def test_without_a_reason_the_text_says_not_stated(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    _on_duty(db_session, TODAY_NY, _staff(db_session, "Pat Lee", "+15855550199"))

    ref = _callback(tools, {})["ref"]

    assert db_session.scalars(select(Request)).one().need == ""
    [(_, body)] = sms.sent
    assert body == f"Callback request {ref} from Dale Kramer ({CALLER}), about: not stated"


def test_the_callback_request_is_not_also_texted_as_a_new_today_request(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    _on_duty(db_session, TODAY_NY, _staff(db_session, "Pat Lee", "+15855550199"))

    _callback(tools, {"reason": "the pump"})

    assert {a.kind for a in _alerts(db_session)} == {"callback"}
    assert len(sms.sent) == 1


def test_no_backup_coordinator_is_a_failed_alert_and_the_on_duty_one_is_still_texted(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    pat = _staff(db_session, "Pat Lee", "+15855550199")
    _on_duty(db_session, TODAY_NY, pat)

    _callback(tools, {"reason": "the pump"})

    assert [to for to, _ in sms.sent] == ["+15855550199"]
    alerts = _alerts(db_session)
    assert [(a.to_staff_id, a.status, a.detail) for a in alerts] == [
        (pat.id, "sent", None),
        (None, "failed", "No backup Coordinator for Sun, Nov 1"),
    ]


def test_no_duty_roster_for_today_records_failed_alerts_and_the_request_is_still_recorded(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    viewer = _staff(db_session, "Pat Lee", None)
    # Someone is on duty tomorrow, nobody today.
    _on_duty(db_session, date(2026, 11, 2), _staff(db_session, "Sam Ortiz", "+15855550198"))

    result = _callback(tools, {"reason": "the pump"})

    assert result["ref"].startswith("R-")
    assert sms.sent == []
    assert db_session.scalars(select(Request)).one().status == "Recorded"
    response = tools.get("/api/alerts/failed", headers=_headers(viewer))
    assert response.json() == {
        "alerts": [
            {
                "ref": result["ref"],
                "kind": "callback",
                "channel": "sms",
                "at": "2026-11-01T20:04:00Z",
                "detail": detail,
            }
            for detail in (
                "No backup Coordinator for Sun, Nov 1",
                "No on-duty Coordinator for Sun, Nov 1",
            )
        ]
    }


def test_one_person_on_duty_and_backup_is_texted_once(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    pat = _staff(db_session, "Pat Lee", "+15855550199")
    _on_duty(db_session, TODAY_NY, pat, pat)

    _callback(tools, {"reason": "the pump"})

    assert [to for to, _ in sms.sent] == ["+15855550199"]
    assert [(a.to_staff_id, a.status) for a in _alerts(db_session)] == [(pat.id, "sent")]


def test_backup_without_a_phone_is_a_failed_alert(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    sam = _staff(db_session, "Sam Ortiz", None)
    _on_duty(db_session, TODAY_NY, _staff(db_session, "Pat Lee", "+15855550199"), sam)

    _callback(tools, {"reason": "the pump"})

    assert len(sms.sent) == 1
    assert [(a.to_staff_id, a.status, a.detail) for a in _alerts(db_session)][1] == (
        sam.id,
        "failed",
        "Sam Ortiz has no phone number",
    )


def test_provider_error_is_a_failed_alert_and_the_ref_is_still_returned(
    tools: TestClient, db_session: Session, sms: FakeSms
) -> None:
    _on_duty(
        db_session,
        TODAY_NY,
        _staff(db_session, "Pat Lee", "+15855550199"),
        _staff(db_session, "Sam Ortiz", "+15855550198"),
    )
    sms.fail = True

    result = _callback(tools, {"reason": "the pump"})

    assert result["ref"].startswith("R-")
    assert [(a.status, a.detail) for a in _alerts(db_session)] == [
        ("failed", "SMS not sent: Twilio answered 400")
    ] * 2


def test_a_foreman_id_in_the_body_is_ignored(tools: TestClient, db_session: Session) -> None:
    rita = db_session.scalars(select(Foreman).where(Foreman.first_name == "Rita")).one()

    _callback(tools, {"reason": "the pump", "foreman_id": rita.id})

    request = db_session.scalars(select(Request)).one()
    assert request.foreman_id != rita.id


def test_an_invalid_body_is_a_speakable_error_and_nothing_is_written(
    tools: TestClient, db_session: Session
) -> None:
    assert _callback(tools, {"reason": 42}) == {"error": "The callback request could not be saved."}
    assert db_session.scalars(select(Request)).all() == []
    assert _alerts(db_session) == []


def test_bad_secret_is_401_and_unknown_conversation_is_403(
    tools: TestClient, db_session: Session
) -> None:
    bad_secret = tools.post(
        "/tools/create_callback_request",
        json={},
        headers={**TOOL_HEADERS, "X-Tool-Secret": "wrong"},
    )
    unknown = tools.post(
        "/tools/create_callback_request",
        json={},
        headers={**TOOL_HEADERS, "X-Conversation-Id": "conv_unknown"},
    )

    assert (bad_secret.status_code, unknown.status_code) == (401, 403)
    assert db_session.scalars(select(Request)).all() == []
