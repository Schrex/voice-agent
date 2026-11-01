"""POST /tools/add_note: a note (optionally urgent) on the caller's own Request (#17, J3 step 4).

The Foreman is the one bound to the conversation at call start (ADR 0004); a note on another
Foreman's Request is rejected and writes nothing. A note never creates a Request (AC3.5).
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
from app.db.models import Call, Foreman, Job, Request, RequestEvent, RequestNote, Staff
from app.domain.draft import DraftItem
from app.domain.lifecycle import Outcome
from app.main import app
from app.services.calls import Caller
from app.services.drafts import save_draft
from app.services.merges import merge_request
from app.services.requests import NewItem, submit_requests
from app.services.roster import load_roster_file, seed_roster

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "elevenlabs"
SAMPLE_ROSTER = ROOT / "backend" / "seed" / "sample_roster.json"

HOOK_SECRET = "test-hook-secret"
TOOL_SECRET = "test-tool-secret"
JWT_SECRET = "test-jwt-secret-at-least-32-bytes-long"
NOW = datetime(2026, 11, 1, 20, 4, tzinfo=UTC)
STAFF_ID = uuid.uuid4()

# Dale Kramer calls from his second rostered number (fixture call_start_rostered.json).
ROSTERED = json.loads((FIXTURES / "call_start_rostered.json").read_text())
CONVERSATION = ROSTERED["conversation_id"]
# Rita Owens, another rostered Foreman, on another call.
RITA_CONVERSATION = "conv_synthetic_rita_0001"
RITA_CALL_START = {**ROSTERED, "caller_id": "+15855550103", "conversation_id": RITA_CONVERSATION}

NOT_FOUND = {"error": "I couldn't find that request."}
NOT_ADDED = {"error": "The note could not be saved."}


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


def _caller(session: Session, conversation_id: str) -> Caller:
    call = session.scalars(select(Call).where(Call.conversation_id == conversation_id)).one()
    assert call.foreman_id is not None
    return Caller(call_id=call.id, foreman_id=call.foreman_id)


def _record(session: Session, conversation_id: str = CONVERSATION, **overrides: Any) -> str:
    """A Recorded Request of the conversation's Foreman; returns its ref."""
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


def _add_note(
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
    return client.post("/tools/add_note", json=body, headers=headers)


def _notes(session: Session) -> list[RequestNote]:
    return list(session.scalars(select(RequestNote).order_by(RequestNote.id)))


def _request_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Request)) or 0


def _staff_headers(session: Session) -> dict[str, str]:
    staff = Staff(id=STAFF_ID, name="Pat Lee", email="pat@example.com", role="coordinator")
    session.add(staff)
    session.flush()
    claims = {"sub": str(staff.id), "aud": "authenticated", "exp": int(time.time()) + 3600}
    return {"Authorization": f"Bearer {jwt.encode(claims, JWT_SECRET, algorithm='HS256')}"}


def test_note_on_another_foremans_request_is_rejected(
    tools: TestClient, db_session: Session
) -> None:
    ritas = _record(db_session, RITA_CONVERSATION, need="a lowboy")
    rita_id = db_session.scalars(select(Foreman.id).where(Foreman.first_name == "Rita")).one()

    # Dale's call, Rita's ref, and even her foreman id in the body: rejected, nothing written.
    response = _add_note(
        tools, {"ref": ritas, "text": "need an answer today", "foreman_id": rita_id}
    )

    assert response.status_code == 200
    assert response.json() == NOT_FOUND
    assert _notes(db_session) == []
    events = db_session.scalars(select(RequestEvent.kind)).all()
    assert "note_added" not in events


def test_urgent_note_is_appended_to_the_callers_request_and_no_request_is_created(
    tools: TestClient, db_session: Session
) -> None:
    """AC3.5 at the tool: "need an answer today" is a note on the existing Request."""
    ref = _record(db_session)
    before = _request_count(db_session)

    response = _add_note(tools, {"ref": ref, "text": "need an answer today", "urgent": True})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert _request_count(db_session) == before
    [note] = _notes(db_session)
    request = db_session.scalars(select(Request).where(Request.ref == int(ref[2:]))).one()
    assert (note.request_id, note.text, note.urgent) == (request.id, "need an answer today", True)
    assert (note.author_type, note.author_id, note.at) == ("agent", None, NOW)
    # The Request itself is unchanged: a note is not an edit.
    assert (request.status, request.urgency, request.need) == (
        "Recorded",
        "Planned",
        "tri-axle dump trucks",
    )


def test_note_is_not_urgent_unless_said(tools: TestClient, db_session: Session) -> None:
    ref = _record(db_session)

    assert _add_note(tools, {"ref": ref, "text": "use the north gate"}).json() == {"ok": True}

    [note] = _notes(db_session)
    assert (note.text, note.urgent) == ("use the north gate", False)


def test_note_writes_an_audit_event_by_the_agent(tools: TestClient, db_session: Session) -> None:
    ref = _record(db_session)

    _add_note(tools, {"ref": ref, "text": "need an answer today", "urgent": True})

    event = db_session.scalars(select(RequestEvent).where(RequestEvent.kind == "note_added")).one()
    assert (event.actor_type, event.actor_id, event.at) == ("agent", None, NOW)
    assert event.before is None
    assert event.after == {"text": "need an answer today", "urgent": True}


def test_unknown_ref_is_a_speakable_not_found(tools: TestClient, db_session: Session) -> None:
    for ref in ("R-999999", "not-a-ref"):
        assert _add_note(tools, {"ref": ref, "text": "x"}).json() == NOT_FOUND
    assert _notes(db_session) == []


def test_a_draft_is_not_the_foremans_request_to_note(
    tools: TestClient, db_session: Session
) -> None:
    """A Draft was never confirmed by the Foreman (GLOSSARY) and the lookup never returns one."""
    dale = _caller(db_session, CONVERSATION)
    draft = save_draft(
        db_session,
        call_id=dale.call_id,
        foreman_id=dale.foreman_id,
        item=DraftItem(need="a lowboy", category="Trucking", job_spoken="the 104 job"),
        now=NOW,
    )
    db_session.commit()

    assert _add_note(tools, {"ref": draft.ref_display, "text": "x"}).json() == NOT_FOUND
    assert _notes(db_session) == []


def test_note_on_a_merged_request_goes_to_the_request_it_was_merged_into(
    tools: TestClient, db_session: Session
) -> None:
    """The lookup answers a merged Request with its target (#33), so the note follows it."""
    duplicate = _record(db_session)
    target = _record(db_session, need="two tri-axles")
    merge_request(
        db_session,
        ref=duplicate,
        into=target,
        outcome=Outcome.WITHDRAWN,
        explanation=f"Duplicate of {target}.",
        staff_id=STAFF_ID,
        now=NOW,
    )

    assert _add_note(tools, {"ref": duplicate, "text": "x"}).json() == {"ok": True}

    [note] = _notes(db_session)
    assert (
        note.request_id
        == db_session.scalars(select(Request.id).where(Request.ref == int(target[2:]))).one()
    )


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"ref": "R-1000"},
        {"ref": "R-1000", "text": ""},
        {"ref": "R-1000", "text": "x", "urgent": "yes"},
        ["R-1000"],
    ],
)
def test_invalid_body_is_a_speakable_error(
    tools: TestClient, db_session: Session, body: Any
) -> None:
    _record(db_session)

    response = _add_note(tools, body)

    assert response.status_code == 200
    assert response.json() == NOT_ADDED
    assert _notes(db_session) == []


def test_bad_secret_is_401_and_unknown_conversation_is_403(
    tools: TestClient, db_session: Session
) -> None:
    ref = _record(db_session)
    body = {"ref": ref, "text": "x"}

    assert _add_note(tools, body, secret="wrong").status_code == 401
    assert _add_note(tools, body, conversation_id="conv_unknown").status_code == 403
    assert _add_note(tools, body, conversation_id=None).status_code == 403
    assert _notes(db_session) == []


def test_detail_shows_the_notes_oldest_first_with_the_urgent_marker(
    tools: TestClient, db_session: Session
) -> None:
    ref = _record(db_session)
    _add_note(tools, {"ref": ref, "text": "use the north gate"})
    _add_note(tools, {"ref": ref, "text": "need an answer today", "urgent": True})

    detail = tools.get(f"/api/requests/{ref}", headers=_staff_headers(db_session)).json()

    assert detail["notes"] == [
        {
            "at": "2026-11-01T20:04:00Z",
            "author_type": "agent",
            "author": None,
            "text": "use the north gate",
            "urgent": False,
        },
        {
            "at": "2026-11-01T20:04:00Z",
            "author_type": "agent",
            "author": None,
            "text": "need an answer today",
            "urgent": True,
        },
    ]
