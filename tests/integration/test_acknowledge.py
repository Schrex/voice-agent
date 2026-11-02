"""POST /api/requests/{ref}/acknowledge: a coordinator acknowledges with an Owner (ticket #11)."""

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
from app.db.models import Call, Foreman, Job, Owner, Staff
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


@pytest.fixture
def dispatch(db_session: Session, staff: Staff) -> Owner:
    """From the sample roster: Dispatch, the default Owner for Trucking and Material."""
    return db_session.scalars(select(Owner).where(Owner.name == "Dispatch")).one()


def _record(session: Session, category: str = "Trucking") -> str:
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
                job_id=job_id,
                job_spoken="Route 104",
                category=category,
                need="tri-axle dump trucks",
            )
        ],
        now=T0,
    )
    return recorded.ref


def _detail(client: TestClient, headers: dict[str, str], ref: str) -> dict[str, Any]:
    response = client.get(f"/api/requests/{ref}", headers=headers)
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


@pytest.mark.parametrize("body", [{}, {"owner_id": None}], ids=["missing", "null"])
def test_acknowledge_without_an_owner_is_422_with_no_change_and_no_event(
    client: TestClient,
    db_session: Session,
    headers: dict[str, str],
    body: dict[str, Any],
) -> None:
    ref = _record(db_session)

    response = client.post(f"/api/requests/{ref}/acknowledge", headers=headers, json=body)

    assert response.status_code == 422
    detail = _detail(client, headers, ref)
    assert detail["status"] == "Recorded"
    assert detail["owner"] is None
    assert detail["acknowledged_at"] is None
    assert [e["kind"] for e in detail["events"]] == ["recorded"]


def test_acknowledge_with_an_unknown_owner_is_422_with_no_change(
    client: TestClient, db_session: Session, headers: dict[str, str]
) -> None:
    ref = _record(db_session)

    response = client.post(
        f"/api/requests/{ref}/acknowledge", headers=headers, json={"owner_id": 999_999}
    )

    assert response.status_code == 422
    detail = _detail(client, headers, ref)
    assert detail["status"] == "Recorded"
    assert [e["kind"] for e in detail["events"]] == ["recorded"]


def test_acknowledge_sets_owner_and_time_and_writes_a_staff_event(
    client: TestClient,
    db_session: Session,
    headers: dict[str, str],
    staff: Staff,
    dispatch: Owner,
) -> None:
    ref = _record(db_session)

    response = client.post(
        f"/api/requests/{ref}/acknowledge", headers=headers, json={"owner_id": dispatch.id}
    )

    assert response.status_code == 200
    detail = _detail(client, headers, ref)
    assert response.json() == detail
    assert detail["status"] == "Acknowledged"
    assert detail["owner"] == {"id": dispatch.id, "name": "Dispatch"}
    assert detail["acknowledged_at"] == "2026-11-01T12:07:30Z"
    recorded, acknowledged = detail["events"]
    assert recorded["kind"] == "recorded"
    assert acknowledged == {
        "at": "2026-11-01T12:07:30Z",
        "actor": {"type": "staff", "id": str(staff.id), "name": "Pat Lee"},
        "kind": "acknowledged",
        "before": {"status": "Recorded", "owner_id": None, "acknowledged_at": None},
        "after": {
            "status": "Acknowledged",
            "owner_id": dispatch.id,
            "acknowledged_at": "2026-11-01T12:07:30Z",
        },
    }


def test_acknowledged_request_cannot_be_acknowledged_again(
    client: TestClient, db_session: Session, headers: dict[str, str], dispatch: Owner
) -> None:
    ref = _record(db_session)
    url = f"/api/requests/{ref}/acknowledge"
    assert client.post(url, headers=headers, json={"owner_id": dispatch.id}).status_code == 200

    response = client.post(url, headers=headers, json={"owner_id": dispatch.id})

    assert response.status_code == 422
    kinds = [e["kind"] for e in _detail(client, headers, ref)["events"]]
    assert kinds == ["recorded", "acknowledged"]


def test_acknowledged_request_stays_in_the_queue_with_its_new_status(
    client: TestClient, db_session: Session, headers: dict[str, str], dispatch: Owner
) -> None:
    ref = _record(db_session)
    client.post(f"/api/requests/{ref}/acknowledge", headers=headers, json={"owner_id": dispatch.id})

    queue = client.get("/api/requests", headers=headers).json()["requests"]

    assert [(r["ref"], r["status"]) for r in queue] == [(ref, "Acknowledged")]


def test_acknowledge_unknown_ref_is_404(
    client: TestClient, headers: dict[str, str], dispatch: Owner
) -> None:
    response = client.post(
        "/api/requests/R-999999/acknowledge", headers=headers, json={"owner_id": dispatch.id}
    )
    assert response.status_code == 404


def test_acknowledge_requires_a_staff_token(
    client: TestClient, db_session: Session, dispatch: Owner
) -> None:
    seed_roster(db_session, load_roster_file(SAMPLE_ROSTER))
    ref = _record(db_session)

    response = client.post(f"/api/requests/{ref}/acknowledge", json={"owner_id": dispatch.id})

    assert response.status_code == 401


def test_detail_offers_the_category_default_owner(
    client: TestClient, db_session: Session, headers: dict[str, str], dispatch: Owner
) -> None:
    trucking = _record(db_session, category="Trucking")
    labor = _record(db_session, category="Labor")

    assert _detail(client, headers, trucking)["default_owner_id"] == dispatch.id
    assert _detail(client, headers, labor)["default_owner_id"] is None


def test_owners_are_listed_by_name_for_staff(
    client: TestClient, db_session: Session, headers: dict[str, str]
) -> None:
    db_session.add(Owner(name="Accounts"))
    db_session.flush()

    assert client.get("/api/owners").status_code == 401
    response = client.get("/api/owners", headers=headers)

    assert response.status_code == 200
    assert [o["name"] for o in response.json()["owners"]] == [
        "Accounts",
        "Dispatch",
        "Equipment Manager",
    ]
    assert set(response.json()["owners"][0]) == {"id", "name"}
