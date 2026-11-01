"""Foreman Informed and Uninformed (ticket #32; spec §5 flags, J9, AC9.4, AC9.5).

A Resolved Request not marked Foreman Informed within 2 h shows Uninformed (dashboard only).
The clock is a FastAPI dependency the tests move by hand.
"""

import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import get_clock
from app.db.models import Call, Foreman, Job, Owner, Staff
from app.main import app
from app.services.calls import Caller
from app.services.requests import NewItem, submit_requests
from app.services.roster import load_roster_file, seed_roster

SAMPLE_ROSTER = Path(__file__).resolve().parents[2] / "backend" / "seed" / "sample_roster.json"

SECRET = "test-jwt-secret-at-least-32-bytes-long"
T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
RESOLVED_AT = datetime(2026, 11, 1, 14, 0, tzinfo=UTC)
TWO_HOURS_LATER = RESOLVED_AT + timedelta(hours=2)
JUST_PAST = TWO_HOURS_LATER + timedelta(seconds=1)


class MovableClock:
    def __init__(self) -> None:
        self.now = RESOLVED_AT

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    yield


@pytest.fixture
def clock(client: TestClient) -> MovableClock:
    clock = MovableClock()
    app.dependency_overrides[get_clock] = lambda: clock
    return clock


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


def _acknowledged(client: TestClient, session: Session, headers: dict[str, str]) -> str:
    ref = _record(session)
    owner = session.scalars(select(Owner).where(Owner.name == "Dispatch")).one()
    url = f"/api/requests/{ref}/acknowledge"
    assert client.post(url, headers=headers, json={"owner_id": owner.id}).status_code == 200
    return ref


def _resolved(
    client: TestClient, session: Session, headers: dict[str, str], clock: MovableClock
) -> str:
    """Resolved as Fulfilled at RESOLVED_AT; the clock is left there."""
    ref = _acknowledged(client, session, headers)
    clock.now = RESOLVED_AT
    body = {"outcome": "Fulfilled", "explanation": "Two dumps sent from the yard."}
    assert client.post(f"/api/requests/{ref}/resolve", headers=headers, json=body).status_code == (
        200
    )
    return ref


def _detail(client: TestClient, headers: dict[str, str], ref: str) -> dict[str, Any]:
    response = client.get(f"/api/requests/{ref}", headers=headers)
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def _uninformed_refs(client: TestClient, headers: dict[str, str]) -> list[str]:
    response = client.get("/api/requests", headers=headers, params={"flag": "uninformed"})
    assert response.status_code == 200
    return [r["ref"] for r in response.json()["requests"]]


def test_ac9_4_a_resolved_request_not_informed_within_2_hours_shows_uninformed(
    client: TestClient, db_session: Session, headers: dict[str, str], clock: MovableClock
) -> None:
    ref = _resolved(client, db_session, headers, clock)

    detail = _detail(client, headers, ref)
    assert detail["foreman_informed_at"] is None
    assert detail["uninformed"] is False
    assert _uninformed_refs(client, headers) == []

    clock.now = TWO_HOURS_LATER
    assert _detail(client, headers, ref)["uninformed"] is False
    assert _uninformed_refs(client, headers) == []

    clock.now = JUST_PAST
    assert _detail(client, headers, ref)["uninformed"] is True
    assert _uninformed_refs(client, headers) == [ref]


def test_the_uninformed_list_shows_who_to_tell_and_what_outcome(
    client: TestClient, db_session: Session, headers: dict[str, str], clock: MovableClock
) -> None:
    ref = _resolved(client, db_session, headers, clock)
    clock.now = JUST_PAST

    response = client.get("/api/requests", headers=headers, params={"flag": "uninformed"})

    assert response.json() == {
        "requests": [
            {
                "ref": ref,
                "foreman": "Dale Kramer",
                "job": "Route 104 Widening",
                "job_spoken": "Route 104",
                "need": "tri-axle dumps",
                "outcome": "Fulfilled",
                "resolved_at": "2026-11-01T14:00:00Z",
            }
        ]
    }


def test_the_uninformed_list_is_oldest_resolved_first(
    client: TestClient, db_session: Session, headers: dict[str, str], clock: MovableClock
) -> None:
    first = _resolved(client, db_session, headers, clock)
    second = _acknowledged(client, db_session, headers)
    clock.now = RESOLVED_AT + timedelta(minutes=30)
    body = {"outcome": "Denied", "explanation": "No trucks free."}
    client.post(f"/api/requests/{second}/resolve", headers=headers, json=body)
    clock.now = datetime(2026, 11, 1, 23, 0, tzinfo=UTC)

    assert _uninformed_refs(client, headers) == [first, second]


def test_marking_foreman_informed_clears_uninformed_with_a_staff_event(
    client: TestClient,
    db_session: Session,
    headers: dict[str, str],
    staff: Staff,
    clock: MovableClock,
) -> None:
    ref = _resolved(client, db_session, headers, clock)
    clock.now = JUST_PAST + timedelta(minutes=5)

    response = client.post(f"/api/requests/{ref}/informed", headers=headers)

    assert response.status_code == 200
    detail = _detail(client, headers, ref)
    assert response.json() == detail
    assert detail["status"] == "Resolved"
    assert detail["foreman_informed_at"] == "2026-11-01T16:05:01Z"
    assert detail["uninformed"] is False
    assert detail["events"][-1] == {
        "at": "2026-11-01T16:05:01Z",
        "actor": {"type": "staff", "id": str(staff.id), "name": "Pat Lee"},
        "kind": "foreman_informed",
        "before": {"foreman_informed_at": None},
        "after": {"foreman_informed_at": "2026-11-01T16:05:01Z"},
    }
    assert _uninformed_refs(client, headers) == []


def test_a_request_marked_within_2_hours_never_shows_uninformed(
    client: TestClient, db_session: Session, headers: dict[str, str], clock: MovableClock
) -> None:
    ref = _resolved(client, db_session, headers, clock)
    clock.now = RESOLVED_AT + timedelta(minutes=10)
    assert client.post(f"/api/requests/{ref}/informed", headers=headers).status_code == 200

    clock.now = datetime(2026, 11, 3, tzinfo=UTC)

    assert _detail(client, headers, ref)["uninformed"] is False
    assert _uninformed_refs(client, headers) == []


def test_an_open_request_cannot_be_marked_and_nothing_is_written(
    client: TestClient, db_session: Session, headers: dict[str, str], clock: MovableClock
) -> None:
    ref = _acknowledged(client, db_session, headers)
    events_before = _detail(client, headers, ref)["events"]

    response = client.post(f"/api/requests/{ref}/informed", headers=headers)

    assert response.status_code == 422
    detail = _detail(client, headers, ref)
    assert detail["foreman_informed_at"] is None
    assert detail["events"] == events_before


def test_marking_twice_is_422_with_one_event(
    client: TestClient, db_session: Session, headers: dict[str, str], clock: MovableClock
) -> None:
    ref = _resolved(client, db_session, headers, clock)
    assert client.post(f"/api/requests/{ref}/informed", headers=headers).status_code == 200
    clock.now = RESOLVED_AT + timedelta(hours=5)

    again = client.post(f"/api/requests/{ref}/informed", headers=headers)

    assert again.status_code == 422
    detail = _detail(client, headers, ref)
    assert detail["foreman_informed_at"] == "2026-11-01T14:00:00Z"
    assert [e["kind"] for e in detail["events"]].count("foreman_informed") == 1


def test_mark_informed_unknown_ref_is_404_and_needs_a_staff_token(
    client: TestClient, db_session: Session, headers: dict[str, str], clock: MovableClock
) -> None:
    ref = _resolved(client, db_session, headers, clock)

    assert client.post("/api/requests/R-999999/informed", headers=headers).status_code == 404
    assert client.post(f"/api/requests/{ref}/informed").status_code == 401
    assert client.get("/api/requests", params={"flag": "uninformed"}).status_code == 401


def test_an_unknown_flag_is_422(
    client: TestClient, headers: dict[str, str], clock: MovableClock
) -> None:
    assert client.get("/api/requests", headers=headers, params={"flag": "x"}).status_code == 422


def test_the_open_queue_is_unchanged_by_uninformed_requests(
    client: TestClient, db_session: Session, headers: dict[str, str], clock: MovableClock
) -> None:
    open_ref = _acknowledged(client, db_session, headers)
    _resolved(client, db_session, headers, clock)
    clock.now = JUST_PAST

    queue = client.get("/api/requests", headers=headers).json()["requests"]

    assert [r["ref"] for r in queue] == [open_ref]
