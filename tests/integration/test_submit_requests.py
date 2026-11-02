"""POST /tools/submit_requests: confirmed items → Recorded Requests, all or none (#6, #15).

Identity comes from the call: the backend resolves the Foreman from `X-Conversation-Id`
via the Call bound at call start (ADR 0004), never from the tool body.
"""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import get_clock
from app.db.models import Call, CallRequest, Foreman, Job, Request, RequestEvent
from app.main import app
from app.services import requests as requests_service
from app.services.roster import load_roster_file, seed_roster

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "elevenlabs"
SAMPLE_ROSTER = ROOT / "backend" / "seed" / "sample_roster.json"

HOOK_SECRET = "test-hook-secret"
TOOL_SECRET = "test-tool-secret"
NOW = datetime(2026, 11, 1, 20, 4, tzinfo=UTC)

# Dale Kramer calls from his second rostered number (fixture call_start_rostered.json).
ROSTERED = json.loads((FIXTURES / "call_start_rostered.json").read_text())
CONVERSATION = ROSTERED["conversation_id"]

SPEAKABLE_ERROR = {"error": "The request could not be saved."}


@pytest.fixture
def tools(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """Seeded roster, secrets set, frozen clock, and Dale's call started."""
    monkeypatch.setenv("HOOK_SECRET", HOOK_SECRET)
    monkeypatch.setenv("TOOL_SECRET", TOOL_SECRET)
    monkeypatch.setenv("OFFICE_MAIN_NUMBER", "585-555-0100")
    seed_roster(db_session, load_roster_file(SAMPLE_ROSTER))
    app.dependency_overrides[get_clock] = lambda: lambda: NOW
    started = client.post(
        "/hooks/call-start", json=ROSTERED, headers={"X-Hook-Secret": HOOK_SECRET}
    )
    assert started.status_code == 200
    yield client


def _job_id(session: Session, name: str) -> int:
    return session.scalars(select(Job.id).where(Job.name == name)).one()


def _foreman_id(session: Session, first_name: str) -> int:
    return session.scalars(select(Foreman.id).where(Foreman.first_name == first_name)).one()


def _item(session: Session, **overrides: Any) -> dict[str, Any]:
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
    return item


def _submit(
    client: TestClient,
    body: dict[str, Any],
    *,
    secret: str | None = TOOL_SECRET,
    conversation_id: str | None = CONVERSATION,
) -> Any:
    headers = {}
    if secret is not None:
        headers["X-Tool-Secret"] = secret
    if conversation_id is not None:
        headers["X-Conversation-Id"] = conversation_id
    return client.post("/tools/submit_requests", json=body, headers=headers)


def _count(session: Session, model: type[Any]) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_valid_call_records_a_request_with_a_reference_and_an_agent_event(
    tools: TestClient, db_session: Session
) -> None:
    response = _submit(tools, {"items": [_item(db_session)]})

    assert response.status_code == 200
    [result] = response.json()
    request = db_session.scalars(select(Request)).one()
    assert result["ref"] == f"R-{request.ref}"
    assert request.ref >= 1000
    assert request.status == "Recorded"
    assert request.foreman_id == _foreman_id(db_session, "Dale")
    assert request.job_id == _job_id(db_session, "Route 104 Widening")
    assert (request.category, request.need, request.quantity, request.unit) == (
        "Trucking",
        "tri-axle dump trucks",
        Decimal(3),
        "trucks",
    )
    assert request.needed_by_spoken == "tomorrow at seven"
    assert request.source == "ai_call"
    assert request.recorded_at == NOW

    event = db_session.scalars(select(RequestEvent)).one()
    assert event.request_id == request.id
    assert (event.actor_type, event.actor_id, event.kind, event.at) == (
        "agent",
        None,
        "recorded",
        NOW,
    )
    assert event.after is not None and event.after["status"] == "Recorded"

    link = db_session.scalars(select(CallRequest)).one()
    call_id = db_session.scalars(select(Call.id).where(Call.conversation_id == CONVERSATION)).one()
    assert (link.call_id, link.request_id, link.relation) == (call_id, request.id, "created")


def test_references_are_sequential(tools: TestClient, db_session: Session) -> None:
    first = _submit(tools, {"items": [_item(db_session)]}).json()[0]["ref"]
    second = _submit(tools, {"items": [_item(db_session, need="lowboy")]}).json()[0]["ref"]

    assert first.startswith("R-") and int(first[2:]) >= 1000
    assert int(second[2:]) == int(first[2:]) + 1


@pytest.mark.parametrize("field", ["foreman_id", "foremanId"])
def test_foreman_id_in_the_tool_body_is_ignored(
    tools: TestClient, db_session: Session, field: str
) -> None:
    rita = _foreman_id(db_session, "Rita")
    body = {"foreman_id": rita, "items": [_item(db_session, **{field: rita})]}

    response = _submit(tools, body)

    assert response.status_code == 200
    request = db_session.scalars(select(Request)).one()
    assert request.foreman_id == _foreman_id(db_session, "Dale")


def _nothing_written(session: Session) -> bool:
    return all(_count(session, m) == 0 for m in (Request, RequestEvent, CallRequest))


@pytest.mark.parametrize("secret", [None, "", "wrong"])
def test_missing_or_wrong_secret_is_rejected_and_nothing_written(
    tools: TestClient, db_session: Session, secret: str | None
) -> None:
    response = _submit(tools, {"items": [_item(db_session)]}, secret=secret)

    assert response.status_code == 401
    assert _nothing_written(db_session)


def test_unset_server_secret_rejects_every_tool_call(
    tools: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TOOL_SECRET")

    response = _submit(tools, {"items": [_item(db_session)]}, secret="")

    assert response.status_code == 401
    assert _nothing_written(db_session)


@pytest.mark.parametrize("conversation_id", [None, "", "conv_never_started"])
def test_unknown_conversation_is_rejected_and_nothing_written(
    tools: TestClient, db_session: Session, conversation_id: str | None
) -> None:
    response = _submit(tools, {"items": [_item(db_session)]}, conversation_id=conversation_id)

    assert response.status_code == 403
    assert _nothing_written(db_session)


def test_unrostered_callers_conversation_is_rejected_and_nothing_written(
    tools: TestClient, db_session: Session
) -> None:
    unrostered = json.loads((FIXTURES / "call_start_unrostered.json").read_text())
    tools.post("/hooks/call-start", json=unrostered, headers={"X-Hook-Secret": HOOK_SECRET})

    response = _submit(
        tools, {"items": [_item(db_session)]}, conversation_id=unrostered["conversation_id"]
    )

    assert response.status_code == 403
    assert _nothing_written(db_session)


def test_backend_error_returns_a_speakable_error_with_http_200(
    tools: TestClient, db_session: Session
) -> None:
    # A job id that does not exist fails the database's foreign key check mid-write.
    response = _submit(tools, {"items": [_item(db_session, job_id=999_999)]})

    assert response.status_code == 200
    assert response.json() == SPEAKABLE_ERROR
    assert _nothing_written(db_session)


def test_failure_after_the_request_is_written_rolls_everything_back(
    tools: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("boom")

    # The Request row is already flushed when its audit event is built.
    monkeypatch.setattr("app.services.requests.recorded_fields", fail)

    response = _submit(tools, {"items": [_item(db_session)]})

    assert response.status_code == 200
    assert response.json() == SPEAKABLE_ERROR
    assert _nothing_written(db_session)


@pytest.mark.parametrize(
    "body",
    [{}, {"items": []}, {"items": "R-1000"}, ["not", "an", "object"]],
    ids=["no-items", "empty-items", "items-not-a-list", "not-an-object"],
)
def test_malformed_body_returns_a_speakable_error(
    tools: TestClient, db_session: Session, body: Any
) -> None:
    response = tools.post(
        "/tools/submit_requests",
        json=body,
        headers={"X-Tool-Secret": TOOL_SECRET, "X-Conversation-Id": CONVERSATION},
    )

    assert response.status_code == 200
    assert response.json() == SPEAKABLE_ERROR
    assert _nothing_written(db_session)


@pytest.mark.parametrize(
    "override",
    [{"category": "Project"}, {"need": ""}, {"job_id": "Route 104"}, {"job_spoken": ""}],
    ids=["unknown-category", "empty-need", "job-not-an-id", "empty-job-spoken"],
)
def test_invalid_item_returns_a_speakable_error(
    tools: TestClient, db_session: Session, override: dict[str, Any]
) -> None:
    response = _submit(tools, {"items": [_item(db_session, **override)]})

    assert response.status_code == 200
    assert response.json() == SPEAKABLE_ERROR
    assert _nothing_written(db_session)


def test_several_items_each_become_a_recorded_request_with_its_own_reference_in_order(
    tools: TestClient, db_session: Session
) -> None:
    # AC1.6: two needs confirmed together → two Recorded Requests, distinct refs, both returned.
    trucks = _item(db_session, needed_by_spoken="tomorrow at seven")
    stone = _item(
        db_session,
        category="Material",
        need="number 2 stone",
        quantity=40,
        unit="tons",
        needed_by_spoken="this afternoon",
    )

    response = _submit(tools, {"items": [trucks, stone]})

    assert response.status_code == 200
    first, second = response.json()
    assert first["ref"] != second["ref"]
    assert (first["needed_by_resolved"], first["urgency"]) == (
        "Monday, November 2 at 7:00 AM",
        "Planned",
    )
    assert (second["needed_by_resolved"], second["urgency"]) == (
        "Sunday, November 1 at 1:00 PM",
        "Today",
    )
    by_ref = {f"R-{r.ref}": r for r in db_session.scalars(select(Request))}
    assert set(by_ref) == {first["ref"], second["ref"]}
    assert by_ref[first["ref"]].need == "tri-axle dump trucks"
    assert by_ref[second["ref"]].need == "number 2 stone"
    assert {r.status for r in by_ref.values()} == {"Recorded"}

    events = db_session.scalars(select(RequestEvent)).all()
    assert sorted(e.request_id for e in events) == sorted(r.id for r in by_ref.values())
    assert {(e.actor_type, e.kind) for e in events} == {("agent", "recorded")}
    links = db_session.scalars(select(CallRequest)).all()
    assert sorted(link.request_id for link in links) == sorted(r.id for r in by_ref.values())
    assert {link.relation for link in links} == {"created"}


def test_several_items_with_one_invalid_record_none_of_them(
    tools: TestClient, db_session: Session
) -> None:
    items = [_item(db_session), _item(db_session, category="Project")]

    response = _submit(tools, {"items": items})

    assert response.status_code == 200
    assert response.json() == SPEAKABLE_ERROR
    assert _nothing_written(db_session)


def test_several_items_where_a_later_one_fails_in_the_database_record_none_of_them(
    tools: TestClient, db_session: Session
) -> None:
    # The second item's job id fails the foreign key check after the first is written.
    items = [_item(db_session), _item(db_session, need="lowboy", job_id=999_999)]

    response = _submit(tools, {"items": items})

    assert response.status_code == 200
    assert response.json() == SPEAKABLE_ERROR
    assert _nothing_written(db_session)


def test_several_items_where_writing_the_last_event_fails_record_none_of_them(
    tools: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = requests_service.recorded_fields
    seen: list[object] = []

    def fail_on_second(request: Request) -> dict[str, object]:
        seen.append(request)
        if len(seen) == 2:
            raise RuntimeError("boom")
        return real(request)

    monkeypatch.setattr("app.services.requests.recorded_fields", fail_on_second)

    response = _submit(tools, {"items": [_item(db_session), _item(db_session, need="lowboy")]})

    assert response.status_code == 200
    assert response.json() == SPEAKABLE_ERROR
    assert len(seen) == 2
    assert _nothing_written(db_session)


def test_optional_fields_may_be_omitted(tools: TestClient, db_session: Session) -> None:
    item = {
        "job_id": _job_id(db_session, "Penfield Sewer Replacement"),
        "job_spoken": "Penfield",
        "category": "Information",
        "need": "where the tie-in is on the drawings",
    }

    response = _submit(tools, {"items": [item]})

    assert response.status_code == 200
    request = db_session.scalars(select(Request)).one()
    assert (request.quantity, request.unit, request.needed_by_spoken) == (None, None, None)


def test_unmatched_job_is_recorded_without_a_job_and_keeps_what_the_foreman_said(
    tools: TestClient, db_session: Session
) -> None:
    item = _item(db_session, job_spoken="the Smith pit")
    del item["job_id"]

    response = _submit(tools, {"items": [item]})

    assert response.status_code == 200
    request = db_session.scalars(select(Request)).one()
    assert [r["ref"] for r in response.json()] == [f"R-{request.ref}"]
    assert (request.job_id, request.job_spoken, request.status) == (
        None,
        "the Smith pit",
        "Recorded",
    )
    event = db_session.scalars(select(RequestEvent)).one()
    assert event.after is not None
    assert (event.after["job_id"], event.after["job_spoken"]) == (None, "the Smith pit")


def test_matched_job_keeps_what_the_foreman_said_too(
    tools: TestClient, db_session: Session
) -> None:
    _submit(tools, {"items": [_item(db_session)]})

    request = db_session.scalars(select(Request)).one()
    assert request.job_id == _job_id(db_session, "Route 104 Widening")
    assert request.job_spoken == "the 104 job"


def test_job_spoken_is_required(tools: TestClient, db_session: Session) -> None:
    item = _item(db_session)
    del item["job_spoken"]

    response = _submit(tools, {"items": [item]})

    assert response.json() == SPEAKABLE_ERROR
    assert _nothing_written(db_session)


# Needed-by and Urgency (ticket #14). NOW is Sunday, November 1, 2026, 3:04 PM in New York.


def test_spoken_needed_by_is_stored_as_a_time_with_its_urgency_and_read_back_by_weekday(
    tools: TestClient, db_session: Session
) -> None:
    response = _submit(tools, {"items": [_item(db_session, needed_by_spoken="tomorrow at seven")]})

    request = db_session.scalars(select(Request)).one()
    assert response.json() == [
        {
            "ref": f"R-{request.ref}",
            "needed_by_resolved": "Monday, November 2 at 7:00 AM",
            "urgency": "Planned",
        }
    ]
    # 7:00 AM EST on Monday 2 November is 12:00 UTC.
    assert request.needed_by == datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
    assert request.needed_by_spoken == "tomorrow at seven"
    assert request.urgency == "Planned"
    event = db_session.scalars(select(RequestEvent)).one()
    assert event.after is not None
    assert event.after["needed_by"] == "2026-11-02T12:00:00Z"
    assert event.after["needed_by_spoken"] == "tomorrow at seven"
    assert event.after["urgency"] == "Planned"


def test_needed_today_is_today_urgency(tools: TestClient, db_session: Session) -> None:
    response = _submit(tools, {"items": [_item(db_session, needed_by_spoken="this afternoon")]})

    request = db_session.scalars(select(Request)).one()
    assert response.json()[0]["urgency"] == "Today"
    assert request.urgency == "Today"
    assert request.needed_by == datetime(2026, 11, 1, 18, 0, tzinfo=UTC)


def test_missing_needed_by_is_recorded_as_unknown(tools: TestClient, db_session: Session) -> None:
    # AC1.5: the Foreman could not say when; the request is Recorded, not blocked.
    item = _item(db_session)
    del item["needed_by_spoken"]

    response = _submit(tools, {"items": [item]})

    request = db_session.scalars(select(Request)).one()
    assert response.json() == [
        {"ref": f"R-{request.ref}", "needed_by_resolved": None, "urgency": None}
    ]
    assert request.status == "Recorded"
    assert (request.needed_by, request.needed_by_spoken, request.urgency) == (None, None, None)


def test_needed_by_that_is_not_understood_is_kept_as_said_and_not_guessed(
    tools: TestClient, db_session: Session
) -> None:
    response = _submit(tools, {"items": [_item(db_session, needed_by_spoken="next Tuesday")]})

    request = db_session.scalars(select(Request)).one()
    assert response.json()[0]["needed_by_resolved"] is None
    assert (request.needed_by, request.needed_by_spoken, request.urgency) == (
        None,
        "next Tuesday",
        None,
    )


def test_a_day_without_a_time_sets_urgency_but_no_needed_by_time(
    tools: TestClient, db_session: Session
) -> None:
    response = _submit(tools, {"items": [_item(db_session, needed_by_spoken="tomorrow")]})

    request = db_session.scalars(select(Request)).one()
    assert response.json()[0]["needed_by_resolved"] == "Monday, November 2"
    assert (request.needed_by, request.urgency) == (None, "Planned")
