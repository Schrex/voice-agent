"""Coordinator actions "Reassign owner" and "Add note" on the request detail (spec J9:
"Actions: ... Add note · ... · Reassign owner"; "Every change audit-logged (who, when,
before/after)").
"""

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
from app.db.models import Call, Foreman, Job, Owner, RequestEvent, RequestNote, Staff
from app.main import app
from app.services.calls import Caller
from app.services.requests import NewItem, submit_requests
from app.services.roster import load_roster_file, seed_roster

SAMPLE_ROSTER = Path(__file__).resolve().parents[2] / "backend" / "seed" / "sample_roster.json"
SECRET = "test-jwt-secret-at-least-32-bytes-long"
T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
T1 = datetime(2026, 11, 1, 12, 7, 30, tzinfo=UTC)


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    yield


@pytest.fixture(autouse=True)
def frozen_clock(client: TestClient) -> None:
    app.dependency_overrides[get_clock] = lambda: lambda: T1


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


def _owner(session: Session, name: str) -> int:
    return session.scalars(select(Owner.id).where(Owner.name == name)).one()


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
        items=[NewItem(job_id=job_id, job_spoken="Route 104", category="Trucking", need="trucks")],
        now=T0,
    )
    return recorded.ref


def _acknowledged(client: TestClient, session: Session, headers: dict[str, str]) -> str:
    ref = _record(session)
    response = client.post(
        f"/api/requests/{ref}/acknowledge",
        headers=headers,
        json={"owner_id": _owner(session, "Dispatch")},
    )
    assert response.status_code == 200
    return ref


def _events(session: Session, kind: str) -> list[RequestEvent]:
    return list(session.scalars(select(RequestEvent).where(RequestEvent.kind == kind)))


# --- Reassign owner ----------------------------------------------------------------------


def test_reassigning_the_owner_changes_it_and_writes_a_staff_event_with_before_and_after(
    client: TestClient, db_session: Session, headers: dict[str, str], staff: Staff
) -> None:
    ref = _acknowledged(client, db_session, headers)
    dispatch, equipment = _owner(db_session, "Dispatch"), _owner(db_session, "Equipment Manager")

    response = client.post(
        f"/api/requests/{ref}/owner", headers=headers, json={"owner_id": equipment}
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["owner"]) == (
        "Acknowledged",
        {"id": equipment, "name": "Equipment Manager"},
    )
    [event] = _events(db_session, "owner_reassigned")
    assert (event.actor_type, event.actor_id, event.at) == ("staff", str(staff.id), T1)
    assert (event.before, event.after) == ({"owner_id": dispatch}, {"owner_id": equipment})


def test_reassigning_an_in_progress_request_keeps_it_in_progress(
    client: TestClient, db_session: Session, headers: dict[str, str]
) -> None:
    ref = _acknowledged(client, db_session, headers)
    assert client.post(f"/api/requests/{ref}/start", headers=headers).status_code == 200

    response = client.post(
        f"/api/requests/{ref}/owner",
        headers=headers,
        json={"owner_id": _owner(db_session, "Equipment Manager")},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "In Progress"


@pytest.mark.parametrize(
    "body", [{}, {"owner_id": None}, {"owner_id": 999_999}], ids=["missing", "null", "unknown"]
)
def test_reassigning_without_a_known_owner_is_422_and_writes_nothing(
    client: TestClient, db_session: Session, headers: dict[str, str], body: dict[str, Any]
) -> None:
    ref = _acknowledged(client, db_session, headers)

    response = client.post(f"/api/requests/{ref}/owner", headers=headers, json=body)

    assert response.status_code == 422
    assert _events(db_session, "owner_reassigned") == []


def test_a_recorded_request_is_acknowledged_not_reassigned(
    client: TestClient, db_session: Session, headers: dict[str, str]
) -> None:
    ref = _record(db_session)

    response = client.post(
        f"/api/requests/{ref}/owner",
        headers=headers,
        json={"owner_id": _owner(db_session, "Dispatch")},
    )

    assert response.status_code == 422
    assert _events(db_session, "owner_reassigned") == []


def test_reassigning_an_unknown_request_is_404(
    client: TestClient, db_session: Session, headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/requests/R-999999/owner",
        headers=headers,
        json={"owner_id": _owner(db_session, "Dispatch")},
    )
    assert response.status_code == 404


# --- Add note ----------------------------------------------------------------------------


def test_a_coordinator_adds_a_note_shown_on_the_detail_with_a_staff_event(
    client: TestClient, db_session: Session, headers: dict[str, str], staff: Staff
) -> None:
    ref = _record(db_session)

    response = client.post(
        f"/api/requests/{ref}/notes", headers=headers, json={"text": "Called Dale back at 8"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "Recorded"  # a note never changes the Request
    assert body["notes"] == [
        {
            "at": "2026-11-01T12:07:30Z",
            "author_type": "staff",
            "author": "Pat Lee",
            "text": "Called Dale back at 8",
            "urgent": False,
        }
    ]
    [event] = _events(db_session, "note_added")
    assert (event.actor_type, event.actor_id) == ("staff", str(staff.id))
    assert event.after == {"text": "Called Dale back at 8", "urgent": False}


@pytest.mark.parametrize(
    "body", [{}, {"text": ""}, {"text": "   "}], ids=["none", "empty", "blank"]
)
def test_a_blank_note_is_422_and_writes_nothing(
    client: TestClient, db_session: Session, headers: dict[str, str], body: dict[str, Any]
) -> None:
    ref = _record(db_session)

    response = client.post(f"/api/requests/{ref}/notes", headers=headers, json=body)

    assert response.status_code == 422
    assert db_session.scalars(select(RequestNote)).all() == []
    assert _events(db_session, "note_added") == []


def test_a_note_on_an_unknown_request_is_404(client: TestClient, headers: dict[str, str]) -> None:
    response = client.post("/api/requests/R-999999/notes", headers=headers, json={"text": "x"})
    assert response.status_code == 404


def test_both_actions_need_a_staff_token(client: TestClient, db_session: Session) -> None:
    seed_roster(db_session, load_roster_file(SAMPLE_ROSTER))
    ref = _record(db_session)
    assert client.post(f"/api/requests/{ref}/owner", json={"owner_id": 1}).status_code == 401
    assert client.post(f"/api/requests/{ref}/notes", json={"text": "x"}).status_code == 401
