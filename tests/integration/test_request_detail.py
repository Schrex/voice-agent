"""GET /api/requests/{ref}: one Request's fields and its audit history (ticket #10)."""

import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Call, Foreman, Job, RequestEvent, Staff
from app.services.calls import Caller
from app.services.requests import NewItem, submit_requests
from app.services.roster import load_roster_file, seed_roster

SAMPLE_ROSTER = Path(__file__).resolve().parents[2] / "backend" / "seed" / "sample_roster.json"

SECRET = "test-jwt-secret-at-least-32-bytes-long"
T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    yield


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


def _record_by_call(session: Session) -> str:
    """A Request recorded the way the agent records one: through the submit service."""
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
    [ref] = submit_requests(
        session,
        caller=Caller(call_id=call.id, foreman_id=dale.id),
        items=[
            NewItem(
                job_id=job_id,
                category="Trucking",
                need="tri-axle dump trucks",
                quantity=None,
                unit=None,
                needed_by_spoken="tomorrow at seven",
            )
        ],
        now=T0,
    )
    return ref


def test_detail_requires_a_staff_token(client: TestClient, db_session: Session) -> None:
    seed_roster(db_session, load_roster_file(SAMPLE_ROSTER))
    ref = _record_by_call(db_session)

    assert client.get(f"/api/requests/{ref}").status_code == 401


def test_unknown_ref_is_404(client: TestClient, headers: dict[str, str]) -> None:
    assert client.get("/api/requests/R-999999", headers=headers).status_code == 404
    assert client.get("/api/requests/not-a-ref", headers=headers).status_code == 404


def test_detail_returns_the_request_fields(
    client: TestClient, db_session: Session, headers: dict[str, str]
) -> None:
    ref = _record_by_call(db_session)

    response = client.get(f"/api/requests/{ref}", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert {k: v for k, v in body.items() if k not in ("events", "calls")} == {
        "ref": ref,
        "foreman": "Dale Kramer",
        "job": "Route 104 Widening",
        "category": "Trucking",
        "need": "tri-axle dump trucks",
        "quantity": None,
        "unit": None,
        "needed_by": "tomorrow at seven",
        "urgency": None,
        "status": "Recorded",
        "source": "ai_call",
        "recorded_at": "2026-11-01T12:00:00Z",
    }


def test_recorded_event_has_the_agent_as_actor_and_the_recorded_fields(
    client: TestClient, db_session: Session, headers: dict[str, str]
) -> None:
    ref = _record_by_call(db_session)

    [event] = client.get(f"/api/requests/{ref}", headers=headers).json()["events"]

    assert event["at"] == "2026-11-01T12:00:00Z"
    assert event["actor"] == {"type": "agent", "id": None, "name": None}
    assert event["kind"] == "recorded"
    assert event["before"] is None
    assert event["after"]["ref"] == ref
    assert event["after"]["status"] == "Recorded"
    assert event["after"]["need"] == "tri-axle dump trucks"


def test_events_come_oldest_first_with_actor_and_before_after(
    client: TestClient, db_session: Session, headers: dict[str, str], staff: Staff
) -> None:
    ref = _record_by_call(db_session)
    recorded = db_session.scalars(select(RequestEvent)).one()
    # Later changes as later tickets will write them; inserted newest first on purpose.
    db_session.add_all(
        [
            RequestEvent(
                request_id=recorded.request_id,
                at=T0 + timedelta(hours=2),
                actor_type="system",
                actor_id=None,
                kind="flagged",
                before={"overdue": False},
                after={"overdue": True},
            ),
            RequestEvent(
                request_id=recorded.request_id,
                at=T0 + timedelta(minutes=5),
                actor_type="staff",
                actor_id=str(staff.id),
                kind="edited",
                before={"unit": None},
                after={"unit": "trucks"},
            ),
        ]
    )
    db_session.flush()

    events = client.get(f"/api/requests/{ref}", headers=headers).json()["events"]

    assert [(e["at"], e["kind"]) for e in events] == [
        ("2026-11-01T12:00:00Z", "recorded"),
        ("2026-11-01T12:05:00Z", "edited"),
        ("2026-11-01T14:00:00Z", "flagged"),
    ]
    assert events[1]["actor"] == {"type": "staff", "id": str(staff.id), "name": "Pat Lee"}
    assert (events[1]["before"], events[1]["after"]) == ({"unit": None}, {"unit": "trucks"})
    assert events[2]["actor"] == {"type": "system", "id": None, "name": None}
    assert (events[2]["before"], events[2]["after"]) == ({"overdue": False}, {"overdue": True})


def test_events_of_other_requests_are_not_shown(
    client: TestClient, db_session: Session, headers: dict[str, str]
) -> None:
    ref = _record_by_call(db_session)
    other = _record_by_call(db_session)

    events = client.get(f"/api/requests/{ref}", headers=headers).json()["events"]

    assert [e["after"]["ref"] for e in events] == [ref]
    assert other != ref
