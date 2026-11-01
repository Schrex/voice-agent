"""POST /tools/find_open_requests: the caller's own Requests and their recorded state (#16).

The Foreman is the one bound to the conversation at call start (ADR 0004); another Foreman's
Requests are never returned, whatever the body says. Each Request comes back with exactly the
facts on record (architecture §4.2), which are all the agent may speak (spec J3, ACX.1).
"""

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import get_clock
from app.db.models import Call, CallRequest, Foreman, Job, Owner, Request
from app.domain.draft import DraftItem
from app.domain.lifecycle import Outcome
from app.main import app
from app.services.calls import Caller
from app.services.drafts import save_draft
from app.services.merges import merge_request
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
NOW = datetime(2026, 11, 1, 20, 4, tzinfo=UTC)
STAFF_ID = uuid.uuid4()

# Dale Kramer calls from his second rostered number (fixture call_start_rostered.json).
ROSTERED = json.loads((FIXTURES / "call_start_rostered.json").read_text())
CONVERSATION = ROSTERED["conversation_id"]
# Rita Owens, another rostered Foreman, on another call.
RITA_CONVERSATION = "conv_synthetic_rita_0001"
RITA_CALL_START = {**ROSTERED, "caller_id": "+15855550103", "conversation_id": RITA_CONVERSATION}

NOT_LOOKED_UP = {"error": "Your Requests could not be looked up."}


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


def _owner_id(session: Session, name: str) -> int:
    return session.scalars(select(Owner.id).where(Owner.name == name)).one()


def _record(session: Session, conversation_id: str = CONVERSATION, **overrides: Any) -> str:
    """A Recorded Request of the conversation's Foreman; returns its ref."""
    item: dict[str, Any] = {
        "job_id": _job_id(session, "Route 104 Widening"),
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


def _find(
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
    return client.post("/tools/find_open_requests", json=body, headers=headers)


def _refs(response: Any) -> list[str]:
    assert response.status_code == 200
    return [r["ref"] for r in response.json()]


def test_another_foremans_requests_are_never_returned(
    tools: TestClient, db_session: Session
) -> None:
    dales = _record(db_session)
    ritas = _record(db_session, RITA_CONVERSATION, need="a lowboy")
    rita_id = db_session.scalars(select(Foreman.id).where(Foreman.first_name == "Rita")).one()

    assert _refs(_find(tools, {})) == [dales]
    # Same Job and Category as Rita's, and her foreman id in the body: still only Dale's.
    assert _refs(_find(tools, {"category": "Trucking", "foreman_id": rita_id})) == [dales]
    assert _refs(_find(tools, {}, conversation_id=RITA_CONVERSATION)) == [ritas]


def test_a_recorded_request_comes_back_with_the_facts_on_record(
    tools: TestClient, db_session: Session
) -> None:
    ref = _record(db_session)

    assert _find(tools, {}).json() == [
        {
            "ref": ref,
            "job": "Route 104 Widening",
            "category": "Trucking",
            "need": "tri-axle dump trucks",
            "quantity": 3,
            "unit": "trucks",
            "needed_by": "Monday, November 2 at 7:00 AM",
            "status": "Recorded",
            "owner": None,
            "outcome": None,
            "explanation": None,
        }
    ]


def test_an_acknowledged_request_names_its_owner(tools: TestClient, db_session: Session) -> None:
    ref = _record(db_session)
    acknowledge_request(
        db_session,
        ref=ref,
        owner_id=_owner_id(db_session, "Dispatch"),
        staff_id=STAFF_ID,
        now=NOW,
    )

    [found] = _find(tools, {}).json()
    assert (found["status"], found["owner"]) == ("Acknowledged", "Dispatch")


def test_an_in_progress_request_names_its_owner(tools: TestClient, db_session: Session) -> None:
    ref = _record(db_session)
    owner_id = _owner_id(db_session, "Equipment Manager")
    acknowledge_request(db_session, ref=ref, owner_id=owner_id, staff_id=STAFF_ID, now=NOW)
    start_request(db_session, ref=ref, staff_id=STAFF_ID, now=NOW)

    [found] = _find(tools, {}).json()
    assert (found["status"], found["owner"]) == ("In Progress", "Equipment Manager")


def test_a_denied_request_carries_its_outcome_and_explanation_as_written(
    tools: TestClient, db_session: Session
) -> None:
    ref = _record(db_session)
    resolve_request(
        db_session,
        ref=ref,
        outcome=Outcome.DENIED,
        explanation="No tri-axles free this week; use the 10-wheelers already on site.",
        staff_id=STAFF_ID,
        now=NOW,
    )

    [found] = _find(tools, {}).json()
    assert (found["status"], found["outcome"], found["explanation"]) == (
        "Resolved",
        "Denied",
        "No tri-axles free this week; use the 10-wheelers already on site.",
    )


def test_job_and_category_narrow_the_lookup(tools: TestClient, db_session: Session) -> None:
    penfield = _job_id(db_session, "Penfield Sewer Replacement")
    trucks_104 = _record(db_session)
    stone_104 = _record(db_session, category="Material", need="#2 stone")
    trucks_penfield = _record(db_session, job_id=penfield, job_spoken="Penfield")

    assert _refs(_find(tools, {"category": "Trucking"})) == [trucks_penfield, trucks_104]
    assert _refs(_find(tools, {"job_id": penfield})) == [trucks_penfield]
    route_104 = _job_id(db_session, "Route 104 Widening")
    assert _refs(_find(tools, {"job_id": route_104, "category": "Material"})) == [stone_104]
    assert _find(tools, {"job_id": penfield, "category": "Material"}).json() == []


def test_an_unmatched_request_is_named_by_the_job_as_said(
    tools: TestClient, db_session: Session
) -> None:
    _record(db_session, job_id=None, job_spoken="the Hilton job")

    [found] = _find(tools, {}).json()
    assert found["job"] == "the Hilton job"


def test_a_draft_is_not_returned(tools: TestClient, db_session: Session) -> None:
    caller = _caller(db_session, CONVERSATION)
    save_draft(
        db_session,
        call_id=caller.call_id,
        foreman_id=caller.foreman_id,
        item=DraftItem(need="a water truck", category="Trucking", job_spoken="the 104 job"),
        now=NOW,
    )
    db_session.commit()

    assert _find(tools, {}).json() == []


def test_no_requests_is_an_empty_list(tools: TestClient) -> None:
    response = _find(tools, {})

    assert (response.status_code, response.json()) == (200, [])


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"category": "Trucks"}, id="not a Category"),
        pytest.param({"job_id": "14"}, id="job_id not a number"),
        pytest.param([], id="not an object"),
    ],
)
def test_an_invalid_body_gets_a_speakable_error(tools: TestClient, body: Any) -> None:
    response = _find(tools, body)

    assert (response.status_code, response.json()) == (200, NOT_LOOKED_UP)


def test_a_bad_tool_secret_is_rejected(tools: TestClient) -> None:
    assert _find(tools, {}, secret="wrong").status_code == 401
    assert _find(tools, {}, secret=None).status_code == 401


def test_the_call_is_linked_once_to_each_request_it_looked_up(
    tools: TestClient, db_session: Session
) -> None:
    trucks = _record(db_session)
    _record(db_session, category="Material", need="#2 stone")
    caller = _caller(db_session, CONVERSATION)

    _find(tools, {"category": "Trucking"})
    _find(tools, {"category": "Trucking"})

    looked_up = db_session.execute(
        select(CallRequest.call_id, Request.ref)
        .join(Request, CallRequest.request_id == Request.id)
        .where(CallRequest.relation == "looked_up")
    ).all()
    assert [(call_id, f"R-{ref}") for call_id, ref in looked_up] == [(caller.call_id, trucks)]


def test_an_unknown_or_missing_conversation_is_rejected(tools: TestClient) -> None:
    assert _find(tools, {}, conversation_id="conv_unknown").status_code == 403
    assert _find(tools, {}, conversation_id=None).status_code == 403


def _merge(session: Session, ref: str, into: str) -> None:
    merge_request(
        session,
        ref=ref,
        into=into,
        outcome=Outcome.WITHDRAWN,
        explanation=f"Duplicate of {into}.",
        staff_id=STAFF_ID,
        now=NOW,
    )


def test_a_merged_request_is_reported_as_its_final_target(
    tools: TestClient, db_session: Session
) -> None:
    """#33 + #16: a lookup that finds merged A reports B, following A→B→C, once each."""
    a = _record(db_session, need="a water truck")
    b = _record(db_session, need="water truck")
    c = _record(db_session, need="water truck for dust")
    other = _record(db_session, need="a lowboy")
    _merge(db_session, a, b)
    _merge(db_session, b, c)
    owner_id = _owner_id(db_session, "Dispatch")
    acknowledge_request(db_session, ref=c, owner_id=owner_id, staff_id=STAFF_ID, now=NOW)

    found = _find(tools, {}).json()
    assert [f["ref"] for f in found] == [other, c]
    reported = next(f for f in found if f["ref"] == c)
    assert (reported["need"], reported["status"], reported["owner"]) == (
        "water truck for dust",
        "Acknowledged",
        "Dispatch",
    )
    linked = db_session.scalars(
        select(Request.ref)
        .join(CallRequest, CallRequest.request_id == Request.id)
        .where(CallRequest.relation == "looked_up")
    ).all()
    assert sorted(f"R-{n}" for n in linked) == sorted([other, c])


def test_a_merge_target_of_another_foreman_is_left_out(
    tools: TestClient, db_session: Session
) -> None:
    """#16's rule holds through a merge: Dale's A merged into Rita's B returns nothing of Rita's."""
    dales = _record(db_session)
    ritas = _record(db_session, RITA_CONVERSATION, need="tri-axle dump trucks")
    _merge(db_session, dales, ritas)

    assert _refs(_find(tools, {})) == []
    assert _refs(_find(tools, {}, conversation_id=RITA_CONVERSATION)) == [ritas]
