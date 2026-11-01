"""Drafts from unfinished calls (ticket #28; spec AC1.8, AC5.2; architecture §3.4 step 4).

When a call ends with no submitted Request but the call analysis (ElevenLabs data collection)
found a need, the post-call webhook creates a Draft with the extracted fields, linked to the
call. Drafts are listed apart from the queue, and a coordinator can promote one to Recorded.
Fixtures in tests/fixtures/elevenlabs/ are synthetic until real payloads are recorded (#37).
"""

import hashlib
import hmac
import json
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import get_clock
from app.db.models import Call, CallRequest, Job, Request, RequestEvent, Staff
from app.main import app
from app.services.roster import load_roster_file, seed_roster

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "elevenlabs"
SAMPLE_ROSTER = ROOT / "backend" / "seed" / "sample_roster.json"

HOOK_SECRET = "test-hook-secret"
TOOL_SECRET = "test-tool-secret"
WEBHOOK_SECRET = "wsec_test_post_call"
JWT_SECRET = "test-jwt-secret-at-least-32-bytes-long"
NOW = datetime(2026, 11, 1, 20, 30, tzinfo=UTC)
LATER = datetime(2026, 11, 1, 21, 0, tzinfo=UTC)

DALE = "+15855550102"
HANG_UP = "conv_synthetic_hang_up_0001"
TRANSFER = "conv_synthetic_transfer_mid_intake_0001"


def _fixture(name: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((FIXTURES / name).read_text())
    return payload


HANG_UP_PAYLOAD = _fixture("post_call_hang_up_before_confirm.json")
TRANSFER_PAYLOAD = _fixture("post_call_transfer_mid_intake.json")


@pytest.fixture
def hook(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """Seeded roster, secrets set, frozen clock, and the fixtures' calls started."""
    monkeypatch.setenv("HOOK_SECRET", HOOK_SECRET)
    monkeypatch.setenv("TOOL_SECRET", TOOL_SECRET)
    monkeypatch.setenv("ELEVENLABS_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.setenv("SUPABASE_JWT_SECRET", JWT_SECRET)
    seed_roster(db_session, load_roster_file(SAMPLE_ROSTER))
    app.dependency_overrides[get_clock] = lambda: lambda: NOW
    for conversation_id in (HANG_UP, TRANSFER):
        response = client.post(
            "/hooks/call-start",
            json={"caller_id": DALE, "conversation_id": conversation_id},
            headers={"X-Hook-Secret": HOOK_SECRET},
        )
        assert response.status_code == 200
    yield client


def _deliver(client: TestClient, payload: dict[str, Any]) -> Any:
    body = json.dumps(payload).encode()
    timestamp = int(NOW.timestamp())
    digest = hmac.new(WEBHOOK_SECRET.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return client.post(
        "/hooks/post-call",
        content=body,
        headers={
            "Content-Type": "application/json",
            "ElevenLabs-Signature": f"t={timestamp},v0={digest.hexdigest()}",
        },
    )


def _call(session: Session, conversation_id: str) -> Call:
    session.expire_all()
    return session.scalars(select(Call).where(Call.conversation_id == conversation_id)).one()


def _requests_of(session: Session, conversation_id: str) -> list[Request]:
    session.expire_all()
    return list(
        session.scalars(
            select(Request)
            .join(CallRequest, CallRequest.request_id == Request.id)
            .join(Call, Call.id == CallRequest.call_id)
            .where(Call.conversation_id == conversation_id)
            .order_by(Request.id)
        )
    )


def _events(session: Session, request: Request) -> list[RequestEvent]:
    return list(
        session.scalars(
            select(RequestEvent)
            .where(RequestEvent.request_id == request.id)
            .order_by(RequestEvent.id)
        )
    )


def _job_id(session: Session, name: str) -> int:
    return session.scalars(select(Job.id).where(Job.name == name)).one()


# --- Draft creation (post-call) --------------------------------------------------------------


def test_hang_up_before_confirm_creates_a_draft_and_no_recorded_request(
    hook: TestClient, db_session: Session
) -> None:
    """AC1.8: the Foreman hangs up during read-back → a Draft exists, nothing is Recorded."""
    response = _deliver(hook, HANG_UP_PAYLOAD)

    assert response.json() == {"status": "recorded"}
    [draft] = _requests_of(db_session, HANG_UP)
    assert draft.status == "Draft"
    assert draft.recorded_at is None
    assert db_session.scalars(select(Request).where(Request.status == "Recorded")).all() == []
    call = _call(db_session, HANG_UP)
    assert draft.foreman_id == call.foreman_id
    assert (
        draft.job_id,
        draft.job_spoken,
        draft.category,
        draft.need,
        draft.quantity,
        draft.unit,
        draft.needed_by_spoken,
        draft.source,
    ) == (
        _job_id(db_session, "Route 104 Widening"),
        "Route 104",
        "Trucking",
        "tri-axle dump trucks",
        Decimal(2),
        "trucks",
        "tomorrow at 7 AM",
        "ai_call",
    )
    assert call.outcome == "draft"


def test_draft_is_linked_to_its_call_and_has_an_audit_event(
    hook: TestClient, db_session: Session
) -> None:
    _deliver(hook, HANG_UP_PAYLOAD)

    [draft] = _requests_of(db_session, HANG_UP)
    links = db_session.scalars(select(CallRequest).where(CallRequest.request_id == draft.id)).all()
    assert [(link.call_id, link.relation) for link in links] == [
        (_call(db_session, HANG_UP).id, "created")
    ]
    [event] = _events(db_session, draft)
    assert (event.kind, event.actor_type, event.actor_id, event.before, event.at) == (
        "drafted",
        "agent",
        None,
        None,
        NOW,
    )
    assert event.after is not None
    assert event.after["status"] == "Draft"
    assert event.after["need"] == "tri-axle dump trucks"


def test_transfer_mid_intake_creates_a_draft_linked_to_the_call(
    hook: TestClient, db_session: Session
) -> None:
    """AC5.2: intake interrupted by a Transfer → a Draft linked to the call."""
    _deliver(hook, TRANSFER_PAYLOAD)

    [draft] = _requests_of(db_session, TRANSFER)
    assert (draft.status, draft.job_id, draft.job_spoken, draft.category, draft.need) == (
        "Draft",
        _job_id(db_session, "Penfield Sewer Replacement"),
        "Penfield sewer",
        "Equipment",
        "move an excavator",
    )
    assert draft.needed_by_spoken is None
    # The call is still recorded as transferred: the office spoke with the Foreman.
    assert _call(db_session, TRANSFER).outcome == "transferred"


def test_a_call_that_submitted_a_request_creates_no_draft(
    hook: TestClient, db_session: Session
) -> None:
    """Data collection found the need, but it was already submitted on this call."""
    job_id = _job_id(db_session, "Route 104 Widening")
    submitted = hook.post(
        "/tools/submit_requests",
        json={
            "items": [
                {
                    "job_id": job_id,
                    "job_spoken": "Route 104",
                    "category": "Trucking",
                    "need": "dump trucks",
                }
            ]
        },
        headers={"X-Tool-Secret": TOOL_SECRET, "X-Conversation-Id": HANG_UP},
    )
    assert "ref" in submitted.json()[0]

    _deliver(hook, HANG_UP_PAYLOAD)

    requests = _requests_of(db_session, HANG_UP)
    assert [r.status for r in requests] == ["Recorded"]
    assert db_session.scalars(select(Request).where(Request.status == "Draft")).all() == []
    assert _call(db_session, HANG_UP).outcome == "submitted"


def _without_need(payload: dict[str, Any], value: Any) -> dict[str, Any]:
    altered: dict[str, Any] = json.loads(json.dumps(payload))
    results = altered["data"]["analysis"]["data_collection_results"]
    if value is _MISSING:
        del results["need"]
    else:
        results["need"]["value"] = value
    return altered


_MISSING = object()


@pytest.mark.parametrize(
    "need",
    [
        pytest.param(_MISSING, id="field absent"),
        pytest.param(None, id="null"),
        pytest.param("", id="empty"),
        pytest.param("   ", id="blank"),
    ],
)
def test_no_need_found_creates_no_draft(hook: TestClient, db_session: Session, need: Any) -> None:
    _deliver(hook, _without_need(HANG_UP_PAYLOAD, need))

    assert _requests_of(db_session, HANG_UP) == []
    assert _call(db_session, HANG_UP).outcome == "none"


def test_repeat_delivery_creates_no_second_draft(hook: TestClient, db_session: Session) -> None:
    first = _deliver(hook, HANG_UP_PAYLOAD)
    second = _deliver(hook, HANG_UP_PAYLOAD)

    assert (first.json(), second.json()) == ({"status": "recorded"}, {"status": "duplicate"})
    assert len(_requests_of(db_session, HANG_UP)) == 1


def test_unrostered_call_gets_no_draft(hook: TestClient, db_session: Session) -> None:
    payload: dict[str, Any] = json.loads(json.dumps(HANG_UP_PAYLOAD))
    payload["data"]["conversation_id"] = "conv_synthetic_unrostered_draft"
    payload["data"]["metadata"]["phone_call"]["external_number"] = "+15855550999"

    _deliver(hook, payload)

    assert _requests_of(db_session, "conv_synthetic_unrostered_draft") == []
    assert _call(db_session, "conv_synthetic_unrostered_draft").outcome == "rejected"


@pytest.mark.parametrize(
    ("spoken", "job", "stored_spoken"),
    [
        pytest.param("the 104 job", "Route 104 Widening", "the 104 job", id="find_jobs match"),
        pytest.param("Brighton", None, "Brighton", id="no match is Unmatched"),
        pytest.param("Lakeside", None, "Lakeside", id="inactive Job is Unmatched"),
        pytest.param(None, None, "", id="no Job said"),
    ],
)
def test_draft_job_is_linked_only_on_a_single_match(
    hook: TestClient,
    db_session: Session,
    spoken: str | None,
    job: str | None,
    stored_spoken: str,
) -> None:
    """The Job is matched like `find_jobs` does (#13); no single match → Unmatched, as said."""
    payload: dict[str, Any] = json.loads(json.dumps(HANG_UP_PAYLOAD))
    payload["data"]["analysis"]["data_collection_results"]["job_spoken"]["value"] = spoken

    _deliver(hook, payload)

    [draft] = _requests_of(db_session, HANG_UP)
    expected = None if job is None else _job_id(db_session, job)
    assert (draft.job_id, draft.job_spoken) == (expected, stored_spoken)


def test_draft_job_matching_two_jobs_is_unmatched(hook: TestClient, db_session: Session) -> None:
    """No read-back on a Draft, so a spoken Job that fits two Jobs is not picked."""
    db_session.add(Job(name="Route 104 Annex", active=True))
    db_session.flush()
    payload: dict[str, Any] = json.loads(json.dumps(HANG_UP_PAYLOAD))
    payload["data"]["analysis"]["data_collection_results"]["job_spoken"]["value"] = "104"

    _deliver(hook, payload)

    [draft] = _requests_of(db_session, HANG_UP)
    assert (draft.job_id, draft.job_spoken) == (None, "104")


# --- Drafts list and promotion (dashboard API) -------------------------------------------------


def _coordinator(session: Session) -> dict[str, str]:
    staff = Staff(
        id=uuid.uuid4(), name="Pat Coordinator", email="pat@example.com", role="coordinator"
    )
    session.add(staff)
    session.flush()
    claims = {"sub": str(staff.id), "aud": "authenticated", "exp": int(time.time()) + 3600}
    return {"Authorization": f"Bearer {jwt.encode(claims, JWT_SECRET, algorithm='HS256')}"}


def test_drafts_list_shows_drafts_with_their_call(hook: TestClient, db_session: Session) -> None:
    _deliver(hook, HANG_UP_PAYLOAD)
    [draft] = _requests_of(db_session, HANG_UP)

    response = hook.get("/api/drafts", headers=_coordinator(db_session))

    assert response.status_code == 200
    assert response.json() == {
        "drafts": [
            {
                "ref": draft.ref_display,
                "foreman": "Dale Kramer",
                "job": "Route 104 Widening",
                "job_spoken": "Route 104",
                "category": "Trucking",
                "need": "tri-axle dump trucks",
                "quantity": "2",
                "unit": "trucks",
                "needed_by_spoken": "tomorrow at 7 AM",
                "call_started_at": "2026-11-01T20:30:00Z",
                "call_summary": HANG_UP_PAYLOAD["data"]["analysis"]["transcript_summary"],
            }
        ]
    }


def test_drafts_list_needs_a_staff_token(hook: TestClient) -> None:
    assert hook.get("/api/drafts").status_code == 401


def test_drafts_list_leaves_out_recorded_requests(hook: TestClient, db_session: Session) -> None:
    _deliver(hook, HANG_UP_PAYLOAD)
    headers = _coordinator(db_session)
    [draft] = _requests_of(db_session, HANG_UP)
    hook.post(f"/api/requests/{draft.ref_display}/record", headers=headers)

    assert hook.get("/api/drafts", headers=headers).json() == {"drafts": []}


def test_coordinator_promotes_a_draft_to_recorded_with_an_audit_event(
    hook: TestClient, db_session: Session
) -> None:
    _deliver(hook, HANG_UP_PAYLOAD)
    headers = _coordinator(db_session)
    staff_id = db_session.scalars(select(Staff.id)).one()
    [draft] = _requests_of(db_session, HANG_UP)
    app.dependency_overrides[get_clock] = lambda: lambda: LATER

    response = hook.post(f"/api/requests/{draft.ref_display}/record", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"ref": draft.ref_display, "status": "Recorded"}
    db_session.expire_all()
    assert (draft.status, draft.recorded_at) == ("Recorded", LATER)
    event = _events(db_session, draft)[-1]
    assert (event.kind, event.actor_type, event.actor_id, event.at) == (
        "recorded",
        "staff",
        str(staff_id),
        LATER,
    )
    assert event.before == {"status": "Draft", "recorded_at": None}
    assert event.after == {"status": "Recorded", "recorded_at": "2026-11-01T21:00:00+00:00"}


def test_promoting_a_request_that_is_not_a_draft_is_refused_and_writes_nothing(
    hook: TestClient, db_session: Session
) -> None:
    _deliver(hook, HANG_UP_PAYLOAD)
    headers = _coordinator(db_session)
    [draft] = _requests_of(db_session, HANG_UP)
    hook.post(f"/api/requests/{draft.ref_display}/record", headers=headers)
    events_before = len(_events(db_session, draft))

    again = hook.post(f"/api/requests/{draft.ref_display}/record", headers=headers)

    assert again.status_code == 422
    db_session.expire_all()
    assert len(_events(db_session, draft)) == events_before


@pytest.mark.parametrize("ref", ["R-999999", "nonsense"])
def test_promoting_an_unknown_ref_is_404(hook: TestClient, db_session: Session, ref: str) -> None:
    response = hook.post(f"/api/requests/{ref}/record", headers=_coordinator(db_session))

    assert response.status_code == 404


def test_promoting_needs_a_staff_token(hook: TestClient, db_session: Session) -> None:
    _deliver(hook, HANG_UP_PAYLOAD)
    [draft] = _requests_of(db_session, HANG_UP)

    response = hook.post(f"/api/requests/{draft.ref_display}/record")

    assert response.status_code == 401
    db_session.expire_all()
    assert draft.status == "Draft"


def test_a_draft_without_a_job_is_recorded_as_unmatched_and_enters_the_queue(
    hook: TestClient, db_session: Session
) -> None:
    """AC1.4: Unmatched is a Recorded state; the Job stays as the Foreman said it."""
    payload: dict[str, Any] = json.loads(json.dumps(HANG_UP_PAYLOAD))
    payload["data"]["analysis"]["data_collection_results"]["job_spoken"]["value"] = "Brighton"
    _deliver(hook, payload)
    headers = _coordinator(db_session)
    [draft] = _requests_of(db_session, HANG_UP)

    response = hook.post(f"/api/requests/{draft.ref_display}/record", headers=headers)

    assert response.json() == {"ref": draft.ref_display, "status": "Recorded"}
    queue = hook.get("/api/requests", headers=headers).json()["requests"]
    assert [(r["ref"], r["job"], r["job_spoken"]) for r in queue] == [
        (draft.ref_display, None, "Brighton")
    ]


def test_draft_detail_shows_it_is_not_recorded(hook: TestClient, db_session: Session) -> None:
    _deliver(hook, HANG_UP_PAYLOAD)
    [draft] = _requests_of(db_session, HANG_UP)

    response = hook.get(f"/api/requests/{draft.ref_display}", headers=_coordinator(db_session))

    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["recorded_at"]) == ("Draft", None)
    assert [e["kind"] for e in body["events"]] == ["drafted"]
