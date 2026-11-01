"""POST /tools/find_duplicates: the duplicate check during intake (ticket #18, spec J2).

Before the read-back, the agent asks the backend whether a new need duplicates one of the
caller's open Requests (same Foreman + Job + Category, not Resolved; ADR 0004 puts the rule in
the backend). Yes → `add_note` on the existing Request and no new Request (AC2.2); no →
`submit_requests` as usual. The check itself writes nothing.
"""

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import get_clock
from app.db.models import Call, CallRequest, Foreman, Job, Request, RequestEvent, RequestNote
from app.domain.draft import DraftItem
from app.domain.lifecycle import Outcome
from app.main import app
from app.services.calls import Caller
from app.services.drafts import save_draft
from app.services.merges import merge_request
from app.services.requests import NewItem, resolve_request, submit_requests
from app.services.roster import load_roster_file, seed_roster

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "elevenlabs"
SAMPLE_ROSTER = ROOT / "backend" / "seed" / "sample_roster.json"

HOOK_SECRET = "test-hook-secret"
TOOL_SECRET = "test-tool-secret"
# Sunday 1 Nov 2026, 3:04 PM in New York.
NOW = datetime(2026, 11, 1, 20, 4, tzinfo=UTC)
# Saturday 31 Oct 2026, 6:45 AM in New York (EDT).
EARLIER = datetime(2026, 10, 31, 10, 45, tzinfo=UTC)
STAFF_ID = uuid.uuid4()

ROSTERED = json.loads((FIXTURES / "call_start_rostered.json").read_text())
CONVERSATION = ROSTERED["conversation_id"]
RITA_CONVERSATION = "conv_synthetic_rita_0001"
RITA_CALL_START = {**ROSTERED, "caller_id": "+15855550103", "conversation_id": RITA_CONVERSATION}

NOT_CHECKED = {"error": "Your open Requests could not be checked."}


@pytest.fixture
def tools(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """Seeded roster, secrets set, frozen clock, and Dale's and Rita's calls started."""
    monkeypatch.setenv("HOOK_SECRET", HOOK_SECRET)
    monkeypatch.setenv("TOOL_SECRET", TOOL_SECRET)
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


def _job_id(session: Session, name: str) -> int:
    return session.scalars(select(Job.id).where(Job.name == name)).one()


def _record(
    session: Session,
    conversation_id: str = CONVERSATION,
    *,
    at: datetime = EARLIER,
    **overrides: Any,
) -> str:
    """A Recorded Request of the conversation's Foreman; returns its ref."""
    item: dict[str, Any] = {
        "job_id": _job_id(session, "Route 104 Widening"),
        "job_spoken": "the 104 job",
        "category": "Trucking",
        "need": "tri-axle dump trucks",
        "quantity": 3,
        "unit": "trucks",
        "needed_by_spoken": "monday at seven",
    }
    item.update(overrides)
    [recorded] = submit_requests(
        session, caller=_caller(session, conversation_id), items=[NewItem(**item)], now=at
    )
    return recorded.ref


def _post(
    client: TestClient,
    tool: str,
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
    return client.post(f"/tools/{tool}", json=body, headers=headers)


def _check(client: TestClient, body: Any, **kwargs: Any) -> Any:
    return _post(client, "find_duplicates", body, **kwargs)


def _trucks_at_104(session: Session) -> dict[str, Any]:
    return {"job_id": _job_id(session, "Route 104 Widening"), "category": "Trucking"}


def _refs(response: Any) -> list[str]:
    assert response.status_code == 200
    return [r["ref"] for r in response.json()]


def _request_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Request)) or 0


def test_an_open_trucking_request_on_the_same_job_is_a_duplicate(
    tools: TestClient, db_session: Session
) -> None:
    """AC2.1 at the tool: the agent has what it needs to ask "Is this about your … from …?"."""
    ref = _record(db_session)

    response = _check(tools, _trucks_at_104(db_session))

    assert response.status_code == 200
    assert response.json() == [
        {
            "ref": ref,
            "job": "Route 104 Widening",
            "category": "Trucking",
            "need": "tri-axle dump trucks",
            "quantity": 3,
            "unit": "trucks",
            "needed_by": "Monday, November 2 at 7:00 AM",
            "recorded_at": "Saturday, October 31 at 6:45 AM",
        }
    ]


def test_another_job_another_category_or_a_resolved_request_is_not_a_duplicate(
    tools: TestClient, db_session: Session
) -> None:
    _record(db_session, job_id=_job_id(db_session, "Penfield Sewer Replacement"))
    _record(db_session, category="Material", need="#2 stone")
    resolved = _record(db_session)
    resolve_request(
        db_session,
        ref=resolved,
        outcome=Outcome.FULFILLED,
        explanation="Two trucks sent.",
        staff_id=STAFF_ID,
        now=NOW,
    )
    _record(db_session, job_id=None, job_spoken="Route 104")

    assert _check(tools, _trucks_at_104(db_session)).json() == []


def test_another_foremans_request_is_never_a_duplicate(
    tools: TestClient, db_session: Session
) -> None:
    _record(db_session, RITA_CONVERSATION)
    rita_id = db_session.scalars(select(Foreman.id).where(Foreman.first_name == "Rita")).one()

    body = {**_trucks_at_104(db_session), "foreman_id": rita_id}
    assert _check(tools, body).json() == []
    assert len(_check(tools, body, conversation_id=RITA_CONVERSATION).json()) == 1


def test_a_draft_is_not_a_duplicate(tools: TestClient, db_session: Session) -> None:
    caller = _caller(db_session, CONVERSATION)
    save_draft(
        db_session,
        call_id=caller.call_id,
        foreman_id=caller.foreman_id,
        item=DraftItem(
            need="a water truck",
            category="Trucking",
            job_spoken="Route 104 Widening",
        ),
        now=NOW,
    )
    db_session.commit()

    assert _check(tools, _trucks_at_104(db_session)).json() == []


def test_a_merged_request_is_not_a_duplicate_but_its_target_is(
    tools: TestClient, db_session: Session
) -> None:
    a = _record(db_session, need="a water truck")
    b = _record(db_session, need="water truck", at=NOW)
    merge_request(
        db_session,
        ref=a,
        into=b,
        outcome=Outcome.WITHDRAWN,
        explanation=f"Duplicate of {b}.",
        staff_id=STAFF_ID,
        now=NOW,
    )

    assert _refs(_check(tools, _trucks_at_104(db_session))) == [b]


def test_several_duplicates_come_back_newest_first(tools: TestClient, db_session: Session) -> None:
    older = _record(db_session, need="tri-axle dump trucks")
    newer = _record(db_session, need="a lowboy", at=NOW)

    assert _refs(_check(tools, _trucks_at_104(db_session))) == [newer, older]


def test_the_check_writes_nothing(tools: TestClient, db_session: Session) -> None:
    _record(db_session)
    events = db_session.scalar(select(func.count()).select_from(RequestEvent))
    links = db_session.scalar(select(func.count()).select_from(CallRequest))

    _check(tools, _trucks_at_104(db_session))

    assert db_session.scalar(select(func.count()).select_from(RequestEvent)) == events
    assert db_session.scalar(select(func.count()).select_from(CallRequest)) == links


def test_yes_it_is_about_that_request_adds_a_note_and_no_new_request(
    tools: TestClient, db_session: Session
) -> None:
    """AC2.2 at the tools: the duplicate's ref takes the note; nothing new is recorded."""
    _record(db_session)
    before = _request_count(db_session)
    [duplicate] = _check(tools, _trucks_at_104(db_session)).json()

    noted = _post(
        tools, "add_note", {"ref": duplicate["ref"], "text": "need two more trucks tomorrow"}
    )

    assert noted.json() == {"ok": True}
    assert _request_count(db_session) == before
    note = db_session.scalars(select(RequestNote)).one()
    assert (note.text, note.author_type) == ("need two more trucks tomorrow", "agent")


def test_no_it_is_a_new_one_records_a_new_request(tools: TestClient, db_session: Session) -> None:
    existing = _record(db_session)
    before = _request_count(db_session)
    assert _refs(_check(tools, _trucks_at_104(db_session))) == [existing]

    submitted = _post(
        tools,
        "submit_requests",
        {
            "items": [
                {
                    **_trucks_at_104(db_session),
                    "job_spoken": "the 104 job",
                    "need": "a water truck",
                }
            ]
        },
    )

    assert submitted.status_code == 200
    [new] = submitted.json()
    assert new["ref"] != existing
    assert _request_count(db_session) == before + 1
    assert db_session.scalar(select(func.count()).select_from(RequestNote)) == 0


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"category": "Trucking"}, id="no job_id"),
        pytest.param({"job_id": 14}, id="no category"),
        pytest.param({"job_id": "14", "category": "Trucking"}, id="job_id not a number"),
        pytest.param({"job_id": 14, "category": "Trucks"}, id="not a Category"),
        pytest.param([], id="not an object"),
    ],
)
def test_an_invalid_body_gets_a_speakable_error(tools: TestClient, body: Any) -> None:
    response = _check(tools, body)

    assert (response.status_code, response.json()) == (200, NOT_CHECKED)


def test_a_bad_tool_secret_is_rejected(tools: TestClient, db_session: Session) -> None:
    body = _trucks_at_104(db_session)
    assert _check(tools, body, secret="wrong").status_code == 401
    assert _check(tools, body, secret=None).status_code == 401


def test_an_unknown_or_missing_conversation_is_rejected(
    tools: TestClient, db_session: Session
) -> None:
    body = _trucks_at_104(db_session)
    assert _check(tools, body, conversation_id="conv_unknown").status_code == 403
    assert _check(tools, body, conversation_id=None).status_code == 403
