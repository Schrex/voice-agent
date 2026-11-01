"""POST /api/requests: a coordinator logs a request from an answered call (ticket #30, spec J7)."""

import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import get_clock
from app.db.models import Foreman, Job, Owner, Request, RequestEvent, Staff
from app.main import app
from app.services.roster import load_roster_file, seed_roster

SAMPLE_ROSTER = Path(__file__).resolve().parents[2] / "backend" / "seed" / "sample_roster.json"

SECRET = "test-jwt-secret-at-least-32-bytes-long"
# Sunday, November 1, 2026, 8:00 AM in New York.
NOW = datetime(2026, 11, 1, 13, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    yield


@pytest.fixture(autouse=True)
def frozen_clock(client: TestClient) -> None:
    app.dependency_overrides[get_clock] = lambda: lambda: NOW


@pytest.fixture
def staff(db_session: Session) -> Staff:
    seed_roster(db_session, load_roster_file(SAMPLE_ROSTER))
    staff = Staff(id=uuid.uuid4(), name="Pat Lee", email="pat@example.com", role="coordinator")
    db_session.add(staff)
    db_session.flush()
    return staff


@pytest.fixture
def headers(staff: Staff) -> dict[str, str]:
    claims = {"sub": str(staff.id), "aud": "authenticated", "exp": int(time.time()) + 3600}
    return {"Authorization": f"Bearer {jwt.encode(claims, SECRET, algorithm='HS256')}"}


def _foreman(session: Session, first_name: str) -> int:
    return session.scalars(select(Foreman.id).where(Foreman.first_name == first_name)).one()


def _job(session: Session, name: str) -> int:
    return session.scalars(select(Job.id).where(Job.name == name)).one()


def _owner(session: Session, name: str) -> int:
    return session.scalars(select(Owner.id).where(Owner.name == name)).one()


def _entry(session: Session, **overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "foreman_id": _foreman(session, "Dale"),
        "job_id": _job(session, "Route 104 Widening"),
        "category": "Trucking",
        "need": "tri-axle dump trucks",
        "quantity": "3",
        "unit": "trucks",
        "needed_by": "tomorrow 7am",
    }
    entry.update(overrides)
    return entry


def _detail(client: TestClient, headers: dict[str, str], ref: str) -> dict[str, Any]:
    response = client.get(f"/api/requests/{ref}", headers=headers)
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def test_ac7_1_logged_request_is_recorded_with_source_coordinator_and_enters_the_queue(
    client: TestClient, db_session: Session, headers: dict[str, str], staff: Staff
) -> None:
    response = client.post("/api/requests", headers=headers, json=_entry(db_session))

    assert response.status_code == 201
    ref = response.json()["ref"]
    assert response.json()["status"] == "Recorded"
    queue = client.get("/api/requests", headers=headers).json()["requests"]
    assert [r["ref"] for r in queue] == [ref]
    detail = _detail(client, headers, ref)
    assert detail["source"] == "coordinator"
    assert detail["status"] == "Recorded"
    assert detail["foreman"] == "Dale Kramer"
    assert detail["job"] == "Route 104 Widening"
    assert detail["category"] == "Trucking"
    assert detail["need"] == "tri-axle dump trucks"
    assert (detail["quantity"], detail["unit"]) == ("3", "trucks")
    assert detail["owner"] is None
    [event] = detail["events"]
    assert event["kind"] == "recorded"
    assert event["actor"] == {"type": "staff", "id": str(staff.id), "name": "Pat Lee"}
    assert event["after"]["source"] == "coordinator"
    assert event["after"]["status"] == "Recorded"


def test_ac7_1_with_an_owner_the_request_is_logged_straight_to_acknowledged(
    client: TestClient, db_session: Session, headers: dict[str, str], staff: Staff
) -> None:
    owner_id = _owner(db_session, "Dispatch")

    response = client.post(
        "/api/requests", headers=headers, json=_entry(db_session, owner_id=owner_id)
    )

    assert response.status_code == 201
    assert response.json()["status"] == "Acknowledged"
    ref = response.json()["ref"]
    [queued] = client.get("/api/requests", headers=headers).json()["requests"]
    assert (queued["ref"], queued["status"]) == (ref, "Acknowledged")
    detail = _detail(client, headers, ref)
    assert detail["owner"] == {"id": owner_id, "name": "Dispatch"}
    assert detail["acknowledged_at"] == "2026-11-01T13:00:00Z"
    assert [(e["kind"], e["actor"]["id"]) for e in detail["events"]] == [
        ("recorded", str(staff.id)),
        ("acknowledged", str(staff.id)),
    ]
    assert detail["events"][1]["after"] == {
        "status": "Acknowledged",
        "owner_id": owner_id,
        "acknowledged_at": "2026-11-01T13:00:00Z",
    }


def test_needed_by_is_resolved_in_new_york_and_sets_the_urgency(
    client: TestClient, db_session: Session, headers: dict[str, str]
) -> None:
    ref = client.post("/api/requests", headers=headers, json=_entry(db_session)).json()["ref"]

    detail = _detail(client, headers, ref)
    # Tomorrow (Monday, November 2) 7:00 AM EST = 12:00 UTC.
    assert detail["needed_by"] == "2026-11-02T12:00:00Z"
    assert detail["needed_by_spoken"] == "tomorrow 7am"
    assert detail["urgency"] == "Planned"


@pytest.mark.parametrize("needed_by", [None, "", "   "], ids=["missing", "empty", "blank"])
def test_no_needed_by_is_recorded_as_unknown(
    client: TestClient, db_session: Session, headers: dict[str, str], needed_by: str | None
) -> None:
    ref = client.post(
        "/api/requests", headers=headers, json=_entry(db_session, needed_by=needed_by)
    ).json()["ref"]

    detail = _detail(client, headers, ref)
    assert (detail["needed_by"], detail["needed_by_spoken"], detail["urgency"]) == (
        None,
        None,
        None,
    )


def test_quantity_and_unit_are_optional(
    client: TestClient, db_session: Session, headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/requests", headers=headers, json=_entry(db_session, quantity=None, unit="")
    )

    assert response.status_code == 201
    detail = _detail(client, headers, response.json()["ref"])
    assert (detail["quantity"], detail["unit"]) == (None, None)


@pytest.mark.parametrize(
    "overrides",
    [
        {"foreman_id": 999_999},
        {"foreman": "Marco"},  # inactive
        {"job_id": 999_999},
        {"job": "Lakeside Plaza Site Work"},  # inactive
        {"owner_id": 999_999},
        {"need": "   "},
        {"category": "Concrete"},
        {"foreman_id": None},
        {"job_id": None},
    ],
    ids=[
        "unknown foreman",
        "inactive foreman",
        "unknown job",
        "inactive job",
        "unknown owner",
        "blank need",
        "not a category",
        "no foreman",
        "no job",
    ],
)
def test_invalid_entry_is_422_and_nothing_is_written(
    client: TestClient, db_session: Session, headers: dict[str, str], overrides: dict[str, Any]
) -> None:
    if "foreman" in overrides:
        overrides = {"foreman_id": _foreman(db_session, overrides["foreman"])}
    if "job" in overrides:
        overrides = {"job_id": _job(db_session, overrides["job"])}

    response = client.post("/api/requests", headers=headers, json=_entry(db_session, **overrides))

    assert response.status_code == 422
    assert db_session.scalars(select(Request)).all() == []
    assert db_session.scalars(select(RequestEvent)).all() == []


def test_logging_needs_a_staff_token(client: TestClient, db_session: Session, staff: Staff) -> None:
    response = client.post("/api/requests", json=_entry(db_session))

    assert response.status_code == 401
    assert db_session.scalars(select(Request)).all() == []


FIND_OPEN_REQUESTS = "/tools/find_open_requests"


def test_ac7_1_logged_request_is_returned_by_the_foremans_phone_status_lookup(
    client: TestClient,
    db_session: Session,
    headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """J3 status lookup is `find_open_requests` (architecture §4.2), built by ticket #16."""
    # app.openapi(), not app.routes: this FastAPI version nests included routers in app.routes.
    if FIND_OPEN_REQUESTS not in app.openapi()["paths"]:
        pytest.skip("find_open_requests (ticket #16) is not built on this branch yet")
    ref = client.post("/api/requests", headers=headers, json=_entry(db_session)).json()["ref"]
    monkeypatch.setenv("HOOK_SECRET", "test-hook-secret")
    monkeypatch.setenv("TOOL_SECRET", "test-tool-secret")
    monkeypatch.setenv("OFFICE_MAIN_NUMBER", "585-555-0100")
    conversation = f"conv_{uuid.uuid4().hex}"
    started = client.post(
        "/hooks/call-start",
        json={
            "caller_id": "+15855550101",  # Dale Kramer
            "agent_id": "agent_test",
            "called_number": "+15855550199",
            "call_sid": f"CA{uuid.uuid4().hex}",
            "conversation_id": conversation,
        },
        headers={"X-Hook-Secret": "test-hook-secret"},
    )
    assert started.status_code == 200

    response = client.post(
        FIND_OPEN_REQUESTS,
        json={},
        headers={"X-Tool-Secret": "test-tool-secret", "X-Conversation-Id": conversation},
    )

    assert response.status_code == 200
    assert ref in [r["ref"] for r in response.json()]


def test_choices_offer_active_foremen_and_jobs_every_category_and_owner(
    client: TestClient, headers: dict[str, str]
) -> None:
    response = client.get("/api/quick-entry", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert [f["name"] for f in body["foremen"]] == ["Dale Kramer", "Rita Owens"]
    assert [j["name"] for j in body["jobs"]] == ["Penfield Sewer Replacement", "Route 104 Widening"]
    assert body["categories"] == [
        "Trucking",
        "Equipment",
        "Equipment Repair",
        "Material",
        "Labor",
        "Information",
        "Callback",
        "Other",
    ]
    assert [o["name"] for o in body["owners"]] == ["Dispatch", "Equipment Manager"]
