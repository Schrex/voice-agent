"""POST /tools/withdraw_request: the Foreman withdraws one of his own Requests by phone (#20, J4).

Before In Progress (Recorded, Acknowledged) the agent resolves it with Outcome Withdrawn and the
explanation "Withdrawn by foreman", with a `resolved` event by the agent (AC4.1). At or after In
Progress nothing changes: a note is added and the Request is flagged Change requested.
"""

import json
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import get_clock
from app.db.models import (
    Call,
    CallRequest,
    Foreman,
    Job,
    Owner,
    Request,
    RequestEvent,
    RequestNote,
    Staff,
)
from app.domain.draft import DraftItem
from app.domain.lifecycle import Outcome
from app.main import app
from app.services.calls import Caller
from app.services.drafts import save_draft
from app.services.requests import (
    NewItem,
    acknowledge_request,
    resolve_request,
    start_request,
    submit_requests,
)
from app.services.roster import load_roster_file, seed_roster

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "elevenlabs"
SAMPLE_ROSTER = ROOT / "backend" / "seed" / "sample_roster.json"

HOOK_SECRET = "test-hook-secret"
TOOL_SECRET = "test-tool-secret"
JWT_SECRET = "test-jwt-secret-at-least-32-bytes-long"
# Sunday, November 1, 2026, 3:04 PM in America/New_York.
NOW = datetime(2026, 11, 1, 20, 4, tzinfo=UTC)
STAFF_ID = uuid.uuid4()

ROSTERED = json.loads((FIXTURES / "call_start_rostered.json").read_text())
CONVERSATION = ROSTERED["conversation_id"]
RITA_CONVERSATION = "conv_synthetic_rita_0001"
RITA_CALL_START = {**ROSTERED, "caller_id": "+15855550103", "conversation_id": RITA_CONVERSATION}

NOT_FOUND = {"error": "I couldn't find that request."}
NOT_WITHDRAWN = {"error": "The request could not be withdrawn."}


@pytest.fixture
def tools(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """Seeded roster, secrets set, frozen clock, and Dale's and Rita's calls started."""
    monkeypatch.setenv("HOOK_SECRET", HOOK_SECRET)
    monkeypatch.setenv("TOOL_SECRET", TOOL_SECRET)
    monkeypatch.setenv("SUPABASE_JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("OFFICE_MAIN_NUMBER", "585-555-0100")
    seed_roster(db_session, load_roster_file(SAMPLE_ROSTER))
    app.dependency_overrides[get_clock] = lambda: lambda: NOW
    for start in (ROSTERED, RITA_CALL_START):
        started = client.post(
            "/hooks/call-start", json=start, headers={"X-Hook-Secret": HOOK_SECRET}
        )
        assert started.status_code == 200
    yield client


def _caller(session: Session, conversation_id: str = CONVERSATION) -> Caller:
    call = session.scalars(select(Call).where(Call.conversation_id == conversation_id)).one()
    assert call.foreman_id is not None
    return Caller(call_id=call.id, foreman_id=call.foreman_id)


def _record(session: Session, conversation_id: str = CONVERSATION, **overrides: Any) -> str:
    """A Recorded Request of the conversation's Foreman (Planned: Monday 7 AM); its ref."""
    item: dict[str, Any] = {
        "job_id": session.scalars(select(Job.id).where(Job.name == "Route 104 Widening")).one(),
        "job_spoken": "the 104 job",
        "category": "Trucking",
        "need": "tri-axle dump trucks",
        "quantity": 3,
        "unit": "trucks",
        "needed_by_spoken": "tomorrow at seven",
    }
    item.update(overrides)
    [recorded] = submit_requests(
        session, caller=_caller(session, conversation_id), items=[NewItem(**item)], now=NOW
    )
    return recorded.ref


def _acknowledge(session: Session, ref: str) -> None:
    owner_id = session.scalars(select(Owner.id).where(Owner.name == "Dispatch")).one()
    acknowledge_request(session, ref=ref, owner_id=owner_id, staff_id=STAFF_ID, now=NOW)


def _in_progress(session: Session, ref: str) -> None:
    _acknowledge(session, ref)
    start_request(session, ref=ref, staff_id=STAFF_ID, now=NOW)


def _withdraw(
    client: TestClient,
    body: Any,
    *,
    secret: str | None = TOOL_SECRET,
    conversation_id: str | None = CONVERSATION,
) -> Any:
    headers = {}
    if secret is not None:
        headers["X-Tool-Secret"] = secret
    if conversation_id is not None:
        headers["X-Conversation-Id"] = conversation_id
    return client.post("/tools/withdraw_request", json=body, headers=headers)


def _request(session: Session, ref: str) -> Request:
    session.expire_all()
    return session.scalars(select(Request).where(Request.ref == int(ref[2:]))).one()


def _events(session: Session, ref: str) -> list[RequestEvent]:
    request = _request(session, ref)
    return list(
        session.scalars(
            select(RequestEvent)
            .where(RequestEvent.request_id == request.id)
            .order_by(RequestEvent.id)
        )
    )


def _notes(session: Session) -> list[RequestNote]:
    return list(session.scalars(select(RequestNote).order_by(RequestNote.id)))


def _fields(request: Request) -> dict[str, Any]:
    return {
        "need": request.need,
        "quantity": request.quantity,
        "unit": request.unit,
        "needed_by_spoken": request.needed_by_spoken,
        "needed_by": request.needed_by,
        "urgency": request.urgency,
        "status": request.status,
        "ack_due_at": request.ack_due_at,
    }


def _staff_headers(session: Session) -> dict[str, str]:
    staff = Staff(id=STAFF_ID, name="Pat Lee", email="pat@example.com", role="coordinator")
    session.add(staff)
    session.flush()
    claims = {"sub": str(staff.id), "aud": "authenticated", "exp": int(time.time()) + 3600}
    return {"Authorization": f"Bearer {jwt.encode(claims, JWT_SECRET, algorithm='HS256')}"}


# --- Before In Progress: resolved as Withdrawn (AC4.1) ---


def test_ac4_1_a_recorded_request_is_resolved_as_withdrawn_with_an_agent_event(
    tools: TestClient, db_session: Session
) -> None:
    ref = _record(db_session)

    response = _withdraw(tools, {"ref": ref})

    assert response.status_code == 200
    assert response.json() == {"applied": True}
    request = _request(db_session, ref)
    assert (request.status, request.outcome, request.explanation, request.resolved_at) == (
        "Resolved",
        "Withdrawn",
        "Withdrawn by foreman",
        NOW,
    )
    assert request.change_requested is False
    *_, event = _events(db_session, ref)
    assert (event.kind, event.actor_type, event.actor_id, event.at) == (
        "resolved",
        "agent",
        None,
        NOW,
    )
    assert event.before == {
        "status": "Recorded",
        "outcome": None,
        "explanation": None,
        "resolved_at": None,
    }
    assert event.after == {
        "status": "Resolved",
        "outcome": "Withdrawn",
        "explanation": "Withdrawn by foreman",
        "resolved_at": "2026-11-01T20:04:00Z",
    }
    assert _notes(db_session) == []


def test_an_acknowledged_request_is_withdrawn_too(tools: TestClient, db_session: Session) -> None:
    ref = _record(db_session)
    _acknowledge(db_session, ref)

    assert _withdraw(tools, {"ref": ref}).json() == {"applied": True}

    request = _request(db_session, ref)
    assert (request.status, request.outcome) == ("Resolved", "Withdrawn")


def test_ac4_1_the_withdrawn_request_leaves_the_queue_and_its_detail_shows_why(
    tools: TestClient, db_session: Session
) -> None:
    ref = _record(db_session)
    other = _record(db_session, need="a lowboy")
    headers = _staff_headers(db_session)

    _withdraw(tools, {"ref": ref})

    rows = tools.get("/api/requests", headers=headers).json()["requests"]
    assert [r["ref"] for r in rows] == [other]
    detail = tools.get(f"/api/requests/{ref}", headers=headers).json()
    assert (detail["status"], detail["outcome"], detail["explanation"]) == (
        "Resolved",
        "Withdrawn",
        "Withdrawn by foreman",
    )


def test_the_call_is_linked_to_the_request_it_withdrew(
    tools: TestClient, db_session: Session
) -> None:
    ref = _record(db_session)

    _withdraw(tools, {"ref": ref})

    request = _request(db_session, ref)
    links = db_session.scalars(
        select(CallRequest).where(
            CallRequest.request_id == request.id, CallRequest.relation == "amended"
        )
    ).all()
    assert [link.call_id for link in links] == [_caller(db_session).call_id]


# --- At or after In Progress: flagged Change requested, not withdrawn ---


def test_withdraw_of_an_in_progress_request_leaves_its_status_unchanged_and_flags_it(
    tools: TestClient, db_session: Session
) -> None:
    ref = _record(db_session)
    _in_progress(db_session, ref)
    before = _fields(_request(db_session, ref))

    response = _withdraw(tools, {"ref": ref})

    assert response.status_code == 200
    assert response.json() == {"applied": False}
    request = _request(db_session, ref)
    assert _fields(request) == before
    assert (request.status, request.outcome, request.explanation) == ("In Progress", None, None)
    assert request.change_requested is True
    [note] = _notes(db_session)
    assert (note.request_id, note.author_type, note.urgent) == (request.id, "agent", False)
    assert note.text == "Change requested: withdraw"
    *_, noted, flagged = _events(db_session, ref)
    assert (noted.kind, noted.actor_type) == ("note_added", "agent")
    assert (flagged.kind, flagged.actor_type, flagged.actor_id) == (
        "change_requested",
        "agent",
        None,
    )
    assert (flagged.before, flagged.after) == (
        {"change_requested": False},
        {"change_requested": True},
    )


def test_a_request_already_flagged_gets_the_note_but_no_second_flag_event(
    tools: TestClient, db_session: Session
) -> None:
    ref = _record(db_session)
    _in_progress(db_session, ref)
    tools.post(
        "/tools/amend_request",
        json={"ref": ref, "changes": {"quantity": 4}},
        headers={"X-Tool-Secret": TOOL_SECRET, "X-Conversation-Id": CONVERSATION},
    )

    _withdraw(tools, {"ref": ref})

    assert [n.text for n in _notes(db_session)] == [
        "Change requested: quantity 4",
        "Change requested: withdraw",
    ]
    kinds = [e.kind for e in _events(db_session, ref)]
    assert kinds.count("change_requested") == 1


def test_a_resolved_request_is_flagged_not_changed(tools: TestClient, db_session: Session) -> None:
    ref = _record(db_session)
    resolve_request(
        db_session,
        ref=ref,
        outcome=Outcome.FULFILLED,
        explanation="Delivered.",
        staff_id=STAFF_ID,
        now=NOW,
    )
    before = _fields(_request(db_session, ref))

    assert _withdraw(tools, {"ref": ref}).json() == {"applied": False}

    request = _request(db_session, ref)
    assert _fields(request) == before
    assert (request.outcome, request.explanation) == ("Fulfilled", "Delivered.")
    assert request.change_requested is True


# --- Refused: nothing written ---


def test_withdraw_of_another_foremans_request_is_rejected(
    tools: TestClient, db_session: Session
) -> None:
    ritas = _record(db_session, RITA_CONVERSATION, need="a lowboy")
    rita_id = db_session.scalars(select(Foreman.id).where(Foreman.first_name == "Rita")).one()
    events_before = len(_events(db_session, ritas))

    response = _withdraw(tools, {"ref": ritas, "foreman_id": rita_id})

    assert response.json() == NOT_FOUND
    assert _request(db_session, ritas).status == "Recorded"
    assert len(_events(db_session, ritas)) == events_before


def test_a_draft_or_unknown_ref_is_not_found(tools: TestClient, db_session: Session) -> None:
    call = _caller(db_session)
    draft = save_draft(
        db_session,
        call_id=call.call_id,
        foreman_id=call.foreman_id,
        item=DraftItem(job_spoken="the 104 job", category="Trucking", need="trucks"),
        now=NOW,
    )
    db_session.commit()

    for ref in (draft.ref_display, "R-999999", "1042"):
        assert _withdraw(tools, {"ref": ref}).json() == NOT_FOUND
    assert _request(db_session, draft.ref_display).status == "Draft"
    assert _notes(db_session) == []


@pytest.mark.parametrize("body", [{}, {"ref": ""}, {"ref": 1042}, {"ref": None}, []])
def test_invalid_body_is_a_speakable_error(
    tools: TestClient, db_session: Session, body: Any
) -> None:
    _record(db_session)
    events_before = db_session.scalar(select(func.count()).select_from(RequestEvent))

    response = _withdraw(tools, body)

    assert response.status_code == 200
    assert response.json() == NOT_WITHDRAWN
    assert db_session.scalar(select(func.count()).select_from(RequestEvent)) == events_before


def test_bad_secret_is_401_and_unknown_conversation_is_403(
    tools: TestClient, db_session: Session
) -> None:
    ref = _record(db_session)
    body = {"ref": ref}

    assert _withdraw(tools, body, secret="wrong").status_code == 401
    assert _withdraw(tools, body, conversation_id="conv_unknown").status_code == 403
    assert _withdraw(tools, body, conversation_id=None).status_code == 403
    assert _request(db_session, ref).status == "Recorded"
