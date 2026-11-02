"""Move to In Progress and Resolve with an Outcome (ticket #12; spec J9, AC9.2, AC9.5)."""

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
from app.db.models import Call, Foreman, Job, Owner, Request, Staff
from app.main import app
from app.services.calls import Caller
from app.services.requests import NewItem, submit_requests
from app.services.roster import load_roster_file, seed_roster

SAMPLE_ROSTER = Path(__file__).resolve().parents[2] / "backend" / "seed" / "sample_roster.json"

SECRET = "test-jwt-secret-at-least-32-bytes-long"
T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
NOW = datetime(2026, 11, 1, 14, 45, 10, tzinfo=UTC)
FIELDS_SET_BY_RESOLVE = ("outcome", "explanation", "resolved_at")


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
    staff = Staff(id=uuid.uuid4(), name="Pat Lee", email="pat@example.com")
    db_session.add(staff)
    db_session.flush()
    return staff


@pytest.fixture
def headers(staff: Staff) -> dict[str, str]:
    claims = {"sub": str(staff.id), "aud": "authenticated", "exp": int(time.time()) + 3600}
    return {"Authorization": f"Bearer {jwt.encode(claims, SECRET, algorithm='HS256')}"}


@pytest.fixture
def dispatch(db_session: Session, staff: Staff) -> Owner:
    return db_session.scalars(select(Owner).where(Owner.name == "Dispatch")).one()


def _record(session: Session) -> str:
    dale = session.scalars(select(Foreman).where(Foreman.first_name == "Dale")).one()
    call = Call(
        conversation_id=f"conv_{uuid.uuid4().hex}",
        caller_e164="+15855550101",
        foreman_id=dale.id,
        started_at=T0,
    )
    session.add(call)
    session.flush()
    job_id = session.scalars(select(Job.id).where(Job.name == "Route 104 Widening")).one()
    [recorded] = submit_requests(
        session,
        caller=Caller(call_id=call.id, foreman_id=dale.id),
        items=[
            NewItem(
                job_id=job_id, job_spoken="Route 104", category="Trucking", need="tri-axle dumps"
            )
        ],
        now=T0,
    )
    return recorded.ref


def _acknowledged(
    client: TestClient, session: Session, headers: dict[str, str], owner: Owner
) -> str:
    ref = _record(session)
    url = f"/api/requests/{ref}/acknowledge"
    assert client.post(url, headers=headers, json={"owner_id": owner.id}).status_code == 200
    return ref


def _in_progress(
    client: TestClient, session: Session, headers: dict[str, str], owner: Owner
) -> str:
    ref = _acknowledged(client, session, headers, owner)
    assert client.post(f"/api/requests/{ref}/start", headers=headers).status_code == 200
    return ref


def _detail(client: TestClient, headers: dict[str, str], ref: str) -> dict[str, Any]:
    response = client.get(f"/api/requests/{ref}", headers=headers)
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def _kinds(client: TestClient, headers: dict[str, str], ref: str) -> list[str]:
    return [e["kind"] for e in _detail(client, headers, ref)["events"]]


# --- Move to In Progress ---------------------------------------------------------------------


def test_start_moves_an_acknowledged_request_to_in_progress_with_a_staff_event(
    client: TestClient,
    db_session: Session,
    headers: dict[str, str],
    staff: Staff,
    dispatch: Owner,
) -> None:
    ref = _acknowledged(client, db_session, headers, dispatch)

    response = client.post(f"/api/requests/{ref}/start", headers=headers)

    assert response.status_code == 200
    detail = _detail(client, headers, ref)
    assert response.json() == detail
    assert detail["status"] == "In Progress"
    assert detail["owner"] == {"id": dispatch.id, "name": "Dispatch"}
    assert detail["events"][-1] == {
        "at": "2026-11-01T14:45:10Z",
        "actor": {"type": "staff", "id": str(staff.id), "name": "Pat Lee"},
        "kind": "in_progress",
        "before": {"status": "Acknowledged"},
        "after": {"status": "In Progress"},
    }
    queue = client.get("/api/requests", headers=headers).json()["requests"]
    assert [(r["ref"], r["status"]) for r in queue] == [(ref, "In Progress")]


def test_start_from_recorded_is_422_and_writes_nothing(
    client: TestClient, db_session: Session, headers: dict[str, str]
) -> None:
    ref = _record(db_session)

    response = client.post(f"/api/requests/{ref}/start", headers=headers)

    assert response.status_code == 422
    assert _detail(client, headers, ref)["status"] == "Recorded"
    assert _kinds(client, headers, ref) == ["recorded"]


def test_start_twice_is_422_with_one_event(
    client: TestClient, db_session: Session, headers: dict[str, str], dispatch: Owner
) -> None:
    ref = _in_progress(client, db_session, headers, dispatch)

    assert client.post(f"/api/requests/{ref}/start", headers=headers).status_code == 422
    assert _kinds(client, headers, ref) == ["recorded", "acknowledged", "in_progress"]


def test_start_unknown_ref_is_404_and_needs_a_staff_token(
    client: TestClient, db_session: Session, headers: dict[str, str], dispatch: Owner
) -> None:
    assert client.post("/api/requests/R-999999/start", headers=headers).status_code == 404
    ref = _acknowledged(client, db_session, headers, dispatch)
    assert client.post(f"/api/requests/{ref}/start").status_code == 401
    assert _detail(client, headers, ref)["status"] == "Acknowledged"


# --- Resolve ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"explanation": "Two trucks sent at 7"},
        {"outcome": None, "explanation": "Two trucks sent at 7"},
        {"outcome": "Fulfilled"},
        {"outcome": "Fulfilled", "explanation": None},
        {"outcome": "Fulfilled", "explanation": ""},
        {"outcome": "Fulfilled", "explanation": "   "},
        {},
    ],
    ids=[
        "no-outcome",
        "null-outcome",
        "no-explanation",
        "null-explanation",
        "empty-explanation",
        "blank-explanation",
        "neither",
    ],
)
def test_ac9_2_resolve_without_outcome_or_explanation_is_422_with_no_change_and_no_event(
    client: TestClient,
    db_session: Session,
    headers: dict[str, str],
    dispatch: Owner,
    body: dict[str, Any],
) -> None:
    ref = _in_progress(client, db_session, headers, dispatch)

    response = client.post(f"/api/requests/{ref}/resolve", headers=headers, json=body)

    assert response.status_code == 422
    detail = _detail(client, headers, ref)
    assert detail["status"] == "In Progress"
    assert [detail[f] for f in FIELDS_SET_BY_RESOLVE] == [None, None, None]
    assert _kinds(client, headers, ref) == ["recorded", "acknowledged", "in_progress"]


def test_resolve_with_an_outcome_that_is_not_a_glossary_outcome_is_422(
    client: TestClient, db_session: Session, headers: dict[str, str], dispatch: Owner
) -> None:
    ref = _in_progress(client, db_session, headers, dispatch)

    response = client.post(
        f"/api/requests/{ref}/resolve",
        headers=headers,
        json={"outcome": "Closed", "explanation": "done"},
    )

    assert response.status_code == 422
    assert _detail(client, headers, ref)["status"] == "In Progress"


def test_resolve_sets_outcome_explanation_and_time_with_a_staff_event_and_leaves_the_queue(
    client: TestClient,
    db_session: Session,
    headers: dict[str, str],
    staff: Staff,
    dispatch: Owner,
) -> None:
    ref = _in_progress(client, db_session, headers, dispatch)

    response = client.post(
        f"/api/requests/{ref}/resolve",
        headers=headers,
        json={"outcome": "Partially Fulfilled", "explanation": "One of two trucks; other at 1pm"},
    )

    assert response.status_code == 200
    detail = _detail(client, headers, ref)
    assert response.json() == detail
    assert detail["status"] == "Resolved"
    assert detail["outcome"] == "Partially Fulfilled"
    assert detail["explanation"] == "One of two trucks; other at 1pm"
    assert detail["resolved_at"] == "2026-11-01T14:45:10Z"
    assert detail["owner"] == {"id": dispatch.id, "name": "Dispatch"}
    assert detail["events"][-1] == {
        "at": "2026-11-01T14:45:10Z",
        "actor": {"type": "staff", "id": str(staff.id), "name": "Pat Lee"},
        "kind": "resolved",
        "before": {
            "status": "In Progress",
            "outcome": None,
            "explanation": None,
            "resolved_at": None,
        },
        "after": {
            "status": "Resolved",
            "outcome": "Partially Fulfilled",
            "explanation": "One of two trucks; other at 1pm",
            "resolved_at": "2026-11-01T14:45:10Z",
        },
    }
    assert client.get("/api/requests", headers=headers).json()["requests"] == []


@pytest.mark.parametrize("stage", ["Recorded", "Acknowledged"])
def test_any_open_request_can_be_resolved(
    client: TestClient,
    db_session: Session,
    headers: dict[str, str],
    dispatch: Owner,
    stage: str,
) -> None:
    ref = (
        _record(db_session)
        if stage == "Recorded"
        else _acknowledged(client, db_session, headers, dispatch)
    )

    response = client.post(
        f"/api/requests/{ref}/resolve",
        headers=headers,
        json={"outcome": "Withdrawn", "explanation": "Foreman called to cancel"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "Resolved"
    assert response.json()["outcome"] == "Withdrawn"
    assert _kinds(client, headers, ref)[-1] == "resolved"


def test_a_resolved_request_cannot_be_resolved_again_or_started(
    client: TestClient, db_session: Session, headers: dict[str, str], dispatch: Owner
) -> None:
    ref = _in_progress(client, db_session, headers, dispatch)
    url = f"/api/requests/{ref}/resolve"
    first = client.post(
        url, headers=headers, json={"outcome": "Denied", "explanation": "No trucks"}
    )
    assert first.status_code == 200

    again = client.post(url, headers=headers, json={"outcome": "Fulfilled", "explanation": "x"})

    assert again.status_code == 422
    assert client.post(f"/api/requests/{ref}/start", headers=headers).status_code == 422
    detail = _detail(client, headers, ref)
    assert (detail["outcome"], detail["explanation"]) == ("Denied", "No trucks")
    assert _kinds(client, headers, ref) == ["recorded", "acknowledged", "in_progress", "resolved"]


def test_resolve_unknown_ref_is_404_and_needs_a_staff_token(
    client: TestClient, db_session: Session, headers: dict[str, str]
) -> None:
    body = {"outcome": "Denied", "explanation": "No trucks"}
    unknown = client.post("/api/requests/R-999999/resolve", headers=headers, json=body)
    assert unknown.status_code == 404
    ref = _record(db_session)
    assert client.post(f"/api/requests/{ref}/resolve", json=body).status_code == 401
    assert _detail(client, headers, ref)["status"] == "Recorded"


def test_detail_of_an_unresolved_request_has_no_outcome(
    client: TestClient, db_session: Session, headers: dict[str, str]
) -> None:
    detail = _detail(client, headers, _record(db_session))
    assert [detail[f] for f in FIELDS_SET_BY_RESOLVE] == [None, None, None]


# --- AC9.5 -----------------------------------------------------------------------------------


def test_ac9_5_every_lifecycle_change_has_an_event_with_who_and_when(
    client: TestClient,
    db_session: Session,
    headers: dict[str, str],
    staff: Staff,
    dispatch: Owner,
) -> None:
    ref = _in_progress(client, db_session, headers, dispatch)
    client.post(
        f"/api/requests/{ref}/resolve",
        headers=headers,
        json={"outcome": "Fulfilled", "explanation": "Two trucks sent at 7"},
    )

    events = _detail(client, headers, ref)["events"]

    assert [(e["before"] or {}).get("status") for e in events] == [
        None,
        "Recorded",
        "Acknowledged",
        "In Progress",
    ]
    assert [e["after"]["status"] for e in events] == [
        "Recorded",
        "Acknowledged",
        "In Progress",
        "Resolved",
    ]
    for event in events[1:]:
        assert event["actor"] == {"type": "staff", "id": str(staff.id), "name": "Pat Lee"}
        assert event["at"] == "2026-11-01T14:45:10Z"


def test_ac9_5_no_route_can_delete_a_request() -> None:
    # The app's full route list, as FastAPI publishes it (included routers flattened).
    paths: dict[str, dict[str, Any]] = app.openapi()["paths"]
    assert "post" in paths["/api/requests/{ref}/resolve"], "the request routes are listed"
    # The only DELETE routes are the admin's removal of a duty day, a roster phone and a Job alias.
    assert sorted(path for path, ops in paths.items() if "delete" in ops) == [
        "/api/admin/duty/{day}",
        "/api/admin/foremen/{foreman_id}/phones/{phone_id}",
        "/api/admin/jobs/{job_id}/aliases/{alias_id}",
    ]


def test_ac9_5_a_resolved_request_is_kept(
    client: TestClient, db_session: Session, headers: dict[str, str], dispatch: Owner
) -> None:
    ref = _in_progress(client, db_session, headers, dispatch)
    client.post(
        f"/api/requests/{ref}/resolve",
        headers=headers,
        json={"outcome": "Fulfilled", "explanation": "Two trucks sent at 7"},
    )

    assert client.delete(f"/api/requests/{ref}", headers=headers).status_code == 405
    stored = db_session.scalars(select(Request).where(Request.ref == int(ref[2:]))).one()
    assert stored.status == "Resolved"
