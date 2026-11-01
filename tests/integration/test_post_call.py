"""POST /hooks/post-call: the record of every call (ticket #27, architecture §3.4).

ElevenLabs signs each delivery with `ElevenLabs-Signature: t=<unix secs>,v0=<hex>`, where
hex = HMAC-SHA256(secret, "<t>.<raw body>"). Payload fixtures in tests/fixtures/elevenlabs/
are synthetic (built from the documented shape) until real payloads are recorded.
"""

import hashlib
import hmac
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import get_clock
from app.db.models import Call, Job
from app.main import app
from app.services.roster import load_roster_file, seed_roster

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "elevenlabs"
SAMPLE_ROSTER = ROOT / "backend" / "seed" / "sample_roster.json"

HOOK_SECRET = "test-hook-secret"
TOOL_SECRET = "test-tool-secret"
WEBHOOK_SECRET = "wsec_test_post_call"
# Sunday 1 Nov 2026, 15:04 in New York; the post-call deliveries arrive at this time.
NOW = datetime(2026, 11, 1, 20, 4, tzinfo=UTC)

ROSTERED_NUMBER = "+15855550102"  # Dale Kramer, sample roster
UNROSTERED_NUMBER = "+15855550999"


def _fixture(name: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((FIXTURES / name).read_text())
    return payload


def _start(client: TestClient, conversation_id: str, caller: str) -> None:
    response = client.post(
        "/hooks/call-start",
        json={"caller_id": caller, "conversation_id": conversation_id},
        headers={"X-Hook-Secret": HOOK_SECRET},
    )
    assert response.status_code == 200


@pytest.fixture
def hook(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """Seeded roster, secrets set, frozen clock, and the fixtures' calls started."""
    monkeypatch.setenv("HOOK_SECRET", HOOK_SECRET)
    monkeypatch.setenv("TOOL_SECRET", TOOL_SECRET)
    monkeypatch.setenv("ELEVENLABS_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.setenv("OFFICE_MAIN_NUMBER", "585-555-0100")
    seed_roster(db_session, load_roster_file(SAMPLE_ROSTER))
    app.dependency_overrides[get_clock] = lambda: lambda: NOW
    _start(client, "conv_synthetic_rostered_0001", ROSTERED_NUMBER)
    _start(client, "conv_synthetic_unrostered_0001", UNROSTERED_NUMBER)
    _start(client, "conv_synthetic_transferred_0001", ROSTERED_NUMBER)
    yield client


def _signature(body: bytes, *, secret: str = WEBHOOK_SECRET, at: datetime = NOW) -> str:
    timestamp = int(at.timestamp())
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return f"t={timestamp},v0={digest.hexdigest()}"


def _deliver(client: TestClient, payload: dict[str, Any], signature: str | None = "sign") -> Any:
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if signature == "sign":
        headers["ElevenLabs-Signature"] = _signature(body)
    elif signature is not None:
        headers["ElevenLabs-Signature"] = signature
    return client.post("/hooks/post-call", content=body, headers=headers)


def _call(session: Session, conversation_id: str) -> Call:
    session.expire_all()
    return session.scalars(select(Call).where(Call.conversation_id == conversation_id)).one()


def _snapshot(session: Session) -> list[tuple[Any, ...]]:
    session.expire_all()
    return [
        (c.conversation_id, c.outcome, c.transcript, c.summary, c.duration_s, c.ended_at)
        for c in session.scalars(select(Call).order_by(Call.id))
    ]


SUBMITTED = _fixture("post_call_submitted.json")
_BODY = json.dumps(SUBMITTED).encode()


@pytest.mark.parametrize(
    "signature",
    [
        pytest.param(None, id="missing"),
        pytest.param("", id="empty"),
        pytest.param("garbage", id="malformed"),
        pytest.param("t=1793563440", id="no-v0"),
        pytest.param(_signature(_BODY, secret="wrong-secret"), id="wrong-secret"),
        pytest.param(_signature(_BODY + b" "), id="other-body"),
        pytest.param(_signature(_BODY, at=NOW - timedelta(minutes=31)), id="stale"),
        pytest.param(_signature(_BODY).replace("v0=", "v1="), id="other-scheme"),
    ],
)
def test_bad_or_missing_signature_is_rejected_and_nothing_written(
    hook: TestClient, db_session: Session, signature: str | None
) -> None:
    before = _snapshot(db_session)

    response = _deliver(hook, SUBMITTED, signature)

    assert response.status_code == 401
    assert _snapshot(db_session) == before


def test_unset_webhook_secret_rejects_every_delivery(
    hook: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _snapshot(db_session)
    monkeypatch.delenv("ELEVENLABS_WEBHOOK_SECRET")

    response = _deliver(hook, SUBMITTED)

    assert response.status_code == 401
    assert _snapshot(db_session) == before


def test_signed_delivery_stores_the_record_on_the_call(
    hook: TestClient, db_session: Session
) -> None:
    response = _deliver(hook, SUBMITTED)

    assert response.status_code == 200
    call = _call(db_session, "conv_synthetic_rostered_0001")
    assert call.transcript == SUBMITTED["data"]["transcript"]
    assert call.summary == (
        "Dale asked for two loads of #2 stone at Route 104 Widening for tomorrow morning. "
        "Recorded as R-1000."
    )
    assert call.duration_s == 26
    assert call.termination_reason == "end_call tool was called."
    # Started at 1793563440 (2026-11-01 20:04:00 UTC) and lasted 26 s.
    assert call.ended_at == datetime(2026, 11, 1, 20, 4, 26, tzinfo=UTC)


def test_same_payload_twice_is_one_update(hook: TestClient, db_session: Session) -> None:
    first = _deliver(hook, SUBMITTED)
    after_first = _snapshot(db_session)

    second = _deliver(hook, SUBMITTED)

    assert (first.json(), second.json()) == ({"status": "recorded"}, {"status": "duplicate"})
    assert second.status_code == 200
    assert _snapshot(db_session) == after_first


def test_a_repeat_delivery_never_overwrites_the_stored_record(
    hook: TestClient, db_session: Session
) -> None:
    _deliver(hook, SUBMITTED)
    altered = json.loads(json.dumps(SUBMITTED))
    altered["data"]["analysis"]["transcript_summary"] = "Something else."
    altered["data"]["metadata"]["call_duration_secs"] = 99

    response = _deliver(hook, altered)

    assert response.json() == {"status": "duplicate"}
    call = _call(db_session, "conv_synthetic_rostered_0001")
    assert call.duration_s == 26
    assert call.summary is not None and call.summary.startswith("Dale asked")


def _submit_on(client: TestClient, session: Session, conversation_id: str) -> None:
    job_id = session.scalars(select(Job.id).where(Job.name == "Route 104 Widening")).one()
    item = {"job_id": job_id, "category": "Material", "need": "#2 stone", "quantity": 2}
    response = client.post(
        "/tools/submit_requests",
        json={"items": [item]},
        headers={"X-Tool-Secret": TOOL_SECRET, "X-Conversation-Id": conversation_id},
    )
    assert "ref" in response.json()[0]


def test_submitted_call_gets_outcome_submitted(hook: TestClient, db_session: Session) -> None:
    _submit_on(hook, db_session, "conv_synthetic_rostered_0001")

    _deliver(hook, SUBMITTED)

    assert _call(db_session, "conv_synthetic_rostered_0001").outcome == "submitted"


def test_rejected_call_keeps_outcome_rejected(hook: TestClient, db_session: Session) -> None:
    response = _deliver(hook, _fixture("post_call_rejected.json"))

    assert response.json() == {"status": "recorded"}
    call = _call(db_session, "conv_synthetic_unrostered_0001")
    assert call.outcome == "rejected"
    assert call.duration_s == 8


def test_transferred_call_gets_outcome_transferred(hook: TestClient, db_session: Session) -> None:
    _deliver(hook, _fixture("post_call_transferred.json"))

    call = _call(db_session, "conv_synthetic_transferred_0001")
    assert (call.outcome, call.termination_reason) == ("transferred", "Call transferred")


@pytest.mark.parametrize(
    ("caller", "foreman_bound", "outcome"),
    [
        pytest.param(ROSTERED_NUMBER, True, "none", id="rostered"),
        pytest.param(UNROSTERED_NUMBER, False, "rejected", id="unrostered"),
    ],
)
def test_call_without_a_call_start_is_recorded_from_the_payload(
    hook: TestClient, db_session: Session, caller: str, foreman_bound: bool, outcome: str
) -> None:
    payload = json.loads(json.dumps(SUBMITTED))
    payload["data"]["conversation_id"] = "conv_synthetic_never_started"
    payload["data"]["metadata"]["phone_call"]["external_number"] = caller

    response = _deliver(hook, payload)

    assert response.json() == {"status": "recorded"}
    call = _call(db_session, "conv_synthetic_never_started")
    assert call.caller_e164 == caller
    assert (call.foreman_id is not None, call.outcome) == (foreman_bound, outcome)
    assert call.started_at == datetime(2026, 11, 1, 20, 4, tzinfo=UTC)
    assert call.duration_s == 26


def test_call_without_a_call_start_or_caller_number_is_not_recorded(
    hook: TestClient, db_session: Session
) -> None:
    before = _snapshot(db_session)
    payload = json.loads(json.dumps(SUBMITTED))
    payload["data"]["conversation_id"] = "conv_synthetic_never_started"
    del payload["data"]["metadata"]["phone_call"]

    response = _deliver(hook, payload)

    assert (response.status_code, response.json()) == (200, {"status": "unknown_call"})
    assert _snapshot(db_session) == before


def test_other_event_types_are_acknowledged_and_ignored(
    hook: TestClient, db_session: Session
) -> None:
    before = _snapshot(db_session)
    payload = {"type": "post_call_audio", "event_timestamp": 1793563500, "data": {}}

    response = _deliver(hook, payload)

    assert (response.status_code, response.json()) == (200, {"status": "ignored"})
    assert _snapshot(db_session) == before


def test_call_with_nothing_submitted_or_transferred_gets_outcome_none(
    hook: TestClient, db_session: Session
) -> None:
    # The submitted fixture's transcript, but no Request was actually recorded on the call.
    _deliver(hook, SUBMITTED)

    assert _call(db_session, "conv_synthetic_rostered_0001").outcome == "none"
