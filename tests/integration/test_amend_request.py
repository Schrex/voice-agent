"""POST /tools/amend_request: the Foreman changes one of his own Requests by phone (#19, J4).

Before In Progress (Recorded, Acknowledged) the change is applied, with an `amended` event by
the agent holding the changed fields before and after. At or after In Progress nothing changes:
a note is added and the Request is flagged Change requested (AC4.2).
"""

import json
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
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
NOT_CHANGED = {"error": "The change could not be saved."}


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


def _amend(
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
    return client.post("/tools/amend_request", json=body, headers=headers)


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
    staff = Staff(id=STAFF_ID, name="Pat Lee", email="pat@example.com")
    session.add(staff)
    session.flush()
    claims = {"sub": str(staff.id), "aud": "authenticated", "exp": int(time.time()) + 3600}
    return {"Authorization": f"Bearer {jwt.encode(claims, JWT_SECRET, algorithm='HS256')}"}


# --- Before In Progress: the change is applied ---


def test_applied_amend_writes_an_agent_event_with_before_and_after(
    tools: TestClient, db_session: Session
) -> None:
    ref = _record(db_session)

    response = _amend(tools, {"ref": ref, "changes": {"needed_by_spoken": "thursday at seven"}})

    assert response.status_code == 200
    assert response.json() == {
        "applied": True,
        "status": "Recorded",
        "ref": ref,
        "need": "tri-axle dump trucks",
        "quantity": 3,
        "unit": "trucks",
        "needed_by_resolved": "Thursday, November 5 at 7:00 AM",
    }
    request = _request(db_session, ref)
    assert request.needed_by_spoken == "thursday at seven"
    assert request.needed_by == datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
    assert request.change_requested is False
    *_, event = _events(db_session, ref)
    assert (event.kind, event.actor_type, event.actor_id, event.at) == (
        "amended",
        "agent",
        None,
        NOW,
    )
    # Only the fields that changed; Urgency stays Planned, so it is not in the event.
    assert event.before == {
        "needed_by_spoken": "tomorrow at seven",
        "needed_by": "2026-11-02T12:00:00Z",
    }
    assert event.after == {
        "needed_by_spoken": "thursday at seven",
        "needed_by": "2026-11-05T12:00:00Z",
    }
    assert _notes(db_session) == []


def test_an_acknowledged_request_is_amended_too(tools: TestClient, db_session: Session) -> None:
    ref = _record(db_session)
    _acknowledge(db_session, ref)

    response = _amend(tools, {"ref": ref, "changes": {"quantity": 4, "unit": "trucks"}})

    assert response.json()["applied"] is True
    assert response.json()["status"] == "Acknowledged"
    assert response.json()["quantity"] == 4
    request = _request(db_session, ref)
    assert request.quantity == 4
    *_, event = _events(db_session, ref)
    assert (event.kind, event.before, event.after) == (
        "amended",
        {"quantity": "3"},
        {"quantity": "4"},
    )


def test_a_needed_by_moved_to_today_makes_it_today_with_the_today_ack_window(
    tools: TestClient, db_session: Session
) -> None:
    ref = _record(db_session)

    response = _amend(tools, {"ref": ref, "changes": {"needed_by_spoken": "today at five"}})

    assert response.json()["needed_by_resolved"] == "Sunday, November 1 at 5:00 PM"
    request = _request(db_session, ref)
    assert request.urgency == "Today"
    assert request.ack_due_at == NOW + timedelta(minutes=15)
    *_, event = _events(db_session, ref)
    assert event.before is not None and event.after is not None
    assert (event.before["urgency"], event.after["urgency"]) == ("Planned", "Today")
    assert (event.before["ack_due_at"], event.after["ack_due_at"]) == (
        "2026-11-01T22:04:00Z",
        "2026-11-01T20:19:00Z",
    )


def test_a_needed_by_not_understood_is_kept_as_said_and_unknown(
    tools: TestClient, db_session: Session
) -> None:
    ref = _record(db_session)

    response = _amend(
        tools, {"ref": ref, "changes": {"needed_by_spoken": "whenever the rain stops"}}
    )

    assert response.json()["needed_by_resolved"] is None
    request = _request(db_session, ref)
    assert (request.needed_by_spoken, request.needed_by, request.urgency) == (
        "whenever the rain stops",
        None,
        None,
    )


def test_need_and_unit_can_be_changed_and_quantity_cleared(
    tools: TestClient, db_session: Session
) -> None:
    ref = _record(db_session)

    response = _amend(
        tools, {"ref": ref, "changes": {"need": "a lowboy", "quantity": None, "unit": None}}
    )

    assert response.json()["need"] == "a lowboy"
    request = _request(db_session, ref)
    assert (request.need, request.quantity, request.unit) == ("a lowboy", None, None)
    *_, event = _events(db_session, ref)
    assert event.before == {"need": "tri-axle dump trucks", "quantity": "3", "unit": "trucks"}
    assert event.after == {"need": "a lowboy", "quantity": None, "unit": None}


def test_an_amend_that_changes_nothing_writes_no_event(
    tools: TestClient, db_session: Session
) -> None:
    ref = _record(db_session)
    events_before = len(_events(db_session, ref))

    response = _amend(tools, {"ref": ref, "changes": {"quantity": 3}})

    assert response.json()["applied"] is True
    assert len(_events(db_session, ref)) == events_before


def test_the_call_is_linked_to_the_request_it_amended(
    tools: TestClient, db_session: Session
) -> None:
    ref = _record(db_session)

    _amend(tools, {"ref": ref, "changes": {"quantity": 4}})
    _amend(tools, {"ref": ref, "changes": {"quantity": 5}})

    links = db_session.scalars(
        select(CallRequest).where(
            CallRequest.request_id == _request(db_session, ref).id,
            CallRequest.relation == "amended",
        )
    ).all()
    assert [link.call_id for link in links] == [_caller(db_session).call_id]


# --- At or after In Progress: flagged Change requested, nothing changed (AC4.2) ---


def test_in_progress_request_is_unchanged_noted_and_flagged_change_requested(
    tools: TestClient, db_session: Session
) -> None:
    ref = _record(db_session)
    _in_progress(db_session, ref)
    before = _fields(_request(db_session, ref))

    response = _amend(tools, {"ref": ref, "changes": {"needed_by_spoken": "thursday at seven"}})

    assert response.status_code == 200
    assert response.json() == {"applied": False, "status": "In Progress"}
    request = _request(db_session, ref)
    assert _fields(request) == before
    assert request.change_requested is True
    [note] = _notes(db_session)
    assert (note.request_id, note.author_type, note.urgent) == (request.id, "agent", False)
    assert note.text == 'Change requested: needed-by "thursday at seven"'
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


def test_the_note_names_every_requested_change(tools: TestClient, db_session: Session) -> None:
    ref = _record(db_session)
    _in_progress(db_session, ref)

    _amend(
        tools,
        {"ref": ref, "changes": {"need": "end dumps", "quantity": 4, "unit": "loads"}},
    )

    [note] = _notes(db_session)
    assert note.text == 'Change requested: need "end dumps"; quantity 4; unit "loads"'


def test_a_second_change_request_adds_a_note_but_no_second_flag_event(
    tools: TestClient, db_session: Session
) -> None:
    ref = _record(db_session)
    _in_progress(db_session, ref)

    _amend(tools, {"ref": ref, "changes": {"quantity": 4}})
    _amend(tools, {"ref": ref, "changes": {"quantity": 5}})

    assert len(_notes(db_session)) == 2
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

    response = _amend(tools, {"ref": ref, "changes": {"quantity": 4}})

    assert response.json() == {"applied": False, "status": "Resolved"}
    request = _request(db_session, ref)
    assert _fields(request) == before
    assert request.change_requested is True


# --- Refused: nothing written ---


def test_amend_of_another_foremans_request_is_rejected(
    tools: TestClient, db_session: Session
) -> None:
    ritas = _record(db_session, RITA_CONVERSATION, need="a lowboy")
    rita_id = db_session.scalars(select(Foreman.id).where(Foreman.first_name == "Rita")).one()
    before = _fields(_request(db_session, ritas))
    events_before = len(_events(db_session, ritas))

    response = _amend(tools, {"ref": ritas, "changes": {"quantity": 9}, "foreman_id": rita_id})

    assert response.json() == NOT_FOUND
    assert _fields(_request(db_session, ritas)) == before
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
        assert _amend(tools, {"ref": ref, "changes": {"quantity": 2}}).json() == NOT_FOUND
    assert _notes(db_session) == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"ref": "R-1000"},
        {"ref": "R-1000", "changes": {}},
        {"ref": "R-1000", "changes": {"job_id": 3}},
        {"ref": "R-1000", "changes": {"category": "Equipment"}},
        {"ref": "R-1000", "changes": {"need": ""}},
        {"ref": "R-1000", "changes": {"quantity": "lots"}},
        {"ref": "R-1000", "changes": {"needed_by_spoken": ""}},
    ],
)
def test_invalid_body_is_a_speakable_error(
    tools: TestClient, db_session: Session, body: dict[str, Any]
) -> None:
    _record(db_session)
    events_before = db_session.scalar(select(func.count()).select_from(RequestEvent))

    response = _amend(tools, body)

    assert response.status_code == 200
    assert response.json() == NOT_CHANGED
    assert db_session.scalar(select(func.count()).select_from(RequestEvent)) == events_before


def test_bad_secret_is_401_and_unknown_conversation_is_403(
    tools: TestClient, db_session: Session
) -> None:
    ref = _record(db_session)
    body = {"ref": ref, "changes": {"quantity": 4}}

    assert _amend(tools, body, secret="wrong").status_code == 401
    assert _amend(tools, body, conversation_id="conv_unknown").status_code == 403
    assert _amend(tools, body, conversation_id=None).status_code == 403
    assert _request(db_session, ref).quantity == 3


# --- Dashboard ---


def test_the_queue_flags_change_requested(tools: TestClient, db_session: Session) -> None:
    flagged = _record(db_session)
    other = _record(db_session, need="a lowboy")
    _in_progress(db_session, flagged)
    _amend(tools, {"ref": flagged, "changes": {"quantity": 4}})

    rows = tools.get("/api/requests", headers=_staff_headers(db_session)).json()["requests"]

    assert {r["ref"]: r["change_requested"] for r in rows} == {flagged: True, other: False}
