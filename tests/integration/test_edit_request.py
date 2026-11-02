"""Edit fields / fix the Job (ticket #31; spec J9, architecture §4.3 `PATCH /api/requests/{ref}`).

Every edit writes a `request_events` row with the changed fields before and after, in the same
transaction. Resolved Requests are not editable.
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
from app.db.models import Call, Foreman, Job, Owner, Staff
from app.main import app
from app.services.calls import Caller
from app.services.requests import NewItem, submit_requests
from app.services.roster import load_roster_file, seed_roster

SAMPLE_ROSTER = Path(__file__).resolve().parents[2] / "backend" / "seed" / "sample_roster.json"

SECRET = "test-jwt-secret-at-least-32-bytes-long"
T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
NOW = datetime(2026, 11, 1, 14, 45, 10, tzinfo=UTC)


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


def _job_id(session: Session, name: str) -> int:
    return session.scalars(select(Job.id).where(Job.name == name)).one()


def _record(session: Session, *, job_id: int | None, job_spoken: str) -> str:
    dale = session.scalars(select(Foreman).where(Foreman.first_name == "Dale")).one()
    call = Call(
        conversation_id=f"conv_{uuid.uuid4().hex}",
        caller_e164="+15855550101",
        foreman_id=dale.id,
        started_at=T0,
    )
    session.add(call)
    session.flush()
    [recorded] = submit_requests(
        session,
        caller=Caller(call_id=call.id, foreman_id=dale.id),
        items=[
            NewItem(
                job_id=job_id,
                job_spoken=job_spoken,
                category="Trucking",
                need="tri-axle dumps",
                quantity=None,
                unit=None,
            )
        ],
        now=T0,
    )
    return recorded.ref


def _unmatched(session: Session) -> str:
    return _record(session, job_id=None, job_spoken="the Smith pit")


def _matched(session: Session) -> str:
    return _record(session, job_id=_job_id(session, "Route 104 Widening"), job_spoken="Route 104")


def _detail(client: TestClient, headers: dict[str, str], ref: str) -> dict[str, Any]:
    response = client.get(f"/api/requests/{ref}", headers=headers)
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def _resolved(client: TestClient, session: Session, headers: dict[str, str]) -> str:
    ref = _unmatched(session)
    body = {"outcome": "Denied", "explanation": "No trucks free"}
    assert (
        client.post(f"/api/requests/{ref}/resolve", headers=headers, json=body).status_code == 200
    )
    return ref


# --- Fix the Job -----------------------------------------------------------------------------


def test_fixing_the_job_of_an_unmatched_request_writes_a_staff_event_with_before_and_after(
    client: TestClient, db_session: Session, headers: dict[str, str], staff: Staff
) -> None:
    ref = _unmatched(db_session)
    penfield = _job_id(db_session, "Penfield Sewer Replacement")

    response = client.patch(f"/api/requests/{ref}", headers=headers, json={"job_id": penfield})

    assert response.status_code == 200
    detail = _detail(client, headers, ref)
    assert response.json() == detail
    assert detail["job"] == "Penfield Sewer Replacement"
    assert detail["job_id"] == penfield
    assert detail["job_spoken"] == "the Smith pit"  # what the Foreman said is kept
    assert detail["events"][-1] == {
        "at": "2026-11-01T14:45:10Z",
        "actor": {"type": "staff", "id": str(staff.id), "name": "Pat Lee"},
        "kind": "edited",
        "before": {"job_id": None},
        "after": {"job_id": penfield},
    }


def test_a_fixed_request_is_no_longer_unmatched_in_the_queue(
    client: TestClient, db_session: Session, headers: dict[str, str]
) -> None:
    ref = _unmatched(db_session)
    penfield = _job_id(db_session, "Penfield Sewer Replacement")

    client.patch(f"/api/requests/{ref}", headers=headers, json={"job_id": penfield})

    [row] = [r for r in client.get("/api/requests", headers=headers).json()["requests"]]
    assert row["ref"] == ref
    assert row["job"] == "Penfield Sewer Replacement"


def test_a_matched_job_can_be_corrected_to_another_job(
    client: TestClient, db_session: Session, headers: dict[str, str]
) -> None:
    ref = _matched(db_session)
    route = _job_id(db_session, "Route 104 Widening")
    penfield = _job_id(db_session, "Penfield Sewer Replacement")

    response = client.patch(f"/api/requests/{ref}", headers=headers, json={"job_id": penfield})

    assert response.status_code == 200
    event = response.json()["events"][-1]
    assert (event["before"], event["after"]) == ({"job_id": route}, {"job_id": penfield})


@pytest.mark.parametrize(
    "job",
    [
        pytest.param("Lakeside Plaza Site Work", id="inactive"),
        pytest.param(None, id="unknown"),
    ],
)
def test_fixing_to_an_inactive_or_unknown_job_is_422_with_no_change(
    client: TestClient, db_session: Session, headers: dict[str, str], job: str | None
) -> None:
    ref = _unmatched(db_session)
    job_id = 999_999 if job is None else _job_id(db_session, job)

    response = client.patch(f"/api/requests/{ref}", headers=headers, json={"job_id": job_id})

    assert response.status_code == 422
    detail = _detail(client, headers, ref)
    assert detail["job"] is None
    assert [e["kind"] for e in detail["events"]] == ["recorded"]


def test_a_job_cannot_be_set_back_to_unmatched(
    client: TestClient, db_session: Session, headers: dict[str, str]
) -> None:
    ref = _matched(db_session)

    response = client.patch(f"/api/requests/{ref}", headers=headers, json={"job_id": None})

    assert response.status_code == 422
    detail = _detail(client, headers, ref)
    assert detail["job"] == "Route 104 Widening"
    assert [e["kind"] for e in detail["events"]] == ["recorded"]


# --- Edit fields -----------------------------------------------------------------------------


def test_editing_fields_records_only_the_changed_fields_before_and_after(
    client: TestClient, db_session: Session, headers: dict[str, str]
) -> None:
    ref = _matched(db_session)
    body = {
        "category": "Material",
        "need": "#2 stone",
        "quantity": "40",
        "unit": "tons",
        "job_id": _job_id(db_session, "Route 104 Widening"),  # unchanged: not in the event
    }

    response = client.patch(f"/api/requests/{ref}", headers=headers, json=body)

    assert response.status_code == 200
    detail = response.json()
    assert (detail["category"], detail["need"], detail["quantity"], detail["unit"]) == (
        "Material",
        "#2 stone",
        "40",
        "tons",
    )
    event = detail["events"][-1]
    assert event["kind"] == "edited"
    assert event["before"] == {
        "category": "Trucking",
        "need": "tri-axle dumps",
        "quantity": None,
        "unit": None,
    }
    assert event["after"] == {
        "category": "Material",
        "need": "#2 stone",
        "quantity": "40",
        "unit": "tons",
    }


def test_quantity_and_unit_can_be_cleared(
    client: TestClient, db_session: Session, headers: dict[str, str]
) -> None:
    ref = _matched(db_session)
    client.patch(f"/api/requests/{ref}", headers=headers, json={"quantity": "3", "unit": "trucks"})

    response = client.patch(
        f"/api/requests/{ref}", headers=headers, json={"quantity": None, "unit": None}
    )

    assert response.status_code == 200
    event = response.json()["events"][-1]
    assert event["before"] == {"quantity": "3", "unit": "trucks"}
    assert event["after"] == {"quantity": None, "unit": None}


def test_each_edit_is_its_own_event(
    client: TestClient, db_session: Session, headers: dict[str, str]
) -> None:
    ref = _unmatched(db_session)

    client.patch(f"/api/requests/{ref}", headers=headers, json={"need": "lowboy"})
    client.patch(f"/api/requests/{ref}", headers=headers, json={"need": "lowboy trailer"})

    events = _detail(client, headers, ref)["events"]
    assert [(e["kind"], e["before"], e["after"]) for e in events[1:]] == [
        ("edited", {"need": "tri-axle dumps"}, {"need": "lowboy"}),
        ("edited", {"need": "lowboy"}, {"need": "lowboy trailer"}),
    ]


def test_an_edit_that_changes_nothing_writes_no_event(
    client: TestClient, db_session: Session, headers: dict[str, str]
) -> None:
    ref = _matched(db_session)

    response = client.patch(
        f"/api/requests/{ref}", headers=headers, json={"need": "tri-axle dumps"}
    )

    assert response.status_code == 200
    assert [e["kind"] for e in response.json()["events"]] == ["recorded"]


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"category": "Snacks"}, id="category-not-in-glossary"),
        pytest.param({"category": None}, id="category-null"),
        pytest.param({"need": ""}, id="need-empty"),
        pytest.param({"need": "   "}, id="need-blank"),
        pytest.param({"need": None}, id="need-null"),
        pytest.param({"quantity": "lots"}, id="quantity-not-a-number"),
        pytest.param({"status": "Resolved"}, id="status-has-its-own-action"),
        pytest.param({"owner_id": 1}, id="owner-has-its-own-action"),
        pytest.param({"job_spoken": "Penfield"}, id="what-the-foreman-said-is-kept"),
    ],
)
def test_an_invalid_edit_is_422_with_no_change_and_no_event(
    client: TestClient, db_session: Session, headers: dict[str, str], body: dict[str, Any]
) -> None:
    ref = _matched(db_session)
    before = _detail(client, headers, ref)

    response = client.patch(f"/api/requests/{ref}", headers=headers, json=body)

    assert response.status_code == 422
    assert _detail(client, headers, ref) == before


# --- Not editable once Resolved --------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"need": "something else"}, id="field"),
        pytest.param({"job_id": "PENFIELD"}, id="job"),
    ],
)
def test_a_resolved_request_is_not_editable(
    client: TestClient, db_session: Session, headers: dict[str, str], body: dict[str, Any]
) -> None:
    ref = _resolved(client, db_session, headers)
    if body.get("job_id") == "PENFIELD":
        body = {"job_id": _job_id(db_session, "Penfield Sewer Replacement")}
    before = _detail(client, headers, ref)

    response = client.patch(f"/api/requests/{ref}", headers=headers, json=body)

    assert response.status_code == 422
    after = _detail(client, headers, ref)
    assert after == before
    assert [e["kind"] for e in after["events"]] == ["recorded", "resolved"]


def test_acknowledged_and_in_progress_requests_are_editable(
    client: TestClient, db_session: Session, headers: dict[str, str]
) -> None:
    ref = _unmatched(db_session)
    dispatch = db_session.scalars(select(Owner).where(Owner.name == "Dispatch")).one()
    client.post(f"/api/requests/{ref}/acknowledge", headers=headers, json={"owner_id": dispatch.id})
    assert client.patch(f"/api/requests/{ref}", headers=headers, json={"need": "a"}).is_success
    client.post(f"/api/requests/{ref}/start", headers=headers)

    response = client.patch(f"/api/requests/{ref}", headers=headers, json={"need": "b"})

    assert response.status_code == 200
    assert response.json()["status"] == "In Progress"
    assert [e["kind"] for e in response.json()["events"]] == [
        "recorded",
        "acknowledged",
        "edited",
        "in_progress",
        "edited",
    ]


# --- Access ----------------------------------------------------------------------------------


def test_edit_of_an_unknown_ref_is_404(client: TestClient, headers: dict[str, str]) -> None:
    for ref in ("R-999999", "nonsense"):
        response = client.patch(f"/api/requests/{ref}", headers=headers, json={"need": "x"})
        assert response.status_code == 404


def test_edit_requires_a_staff_token(client: TestClient, db_session: Session, staff: Staff) -> None:
    ref = _unmatched(db_session)

    response = client.patch(f"/api/requests/{ref}", json={"need": "x"})

    assert response.status_code == 401


def test_active_jobs_are_listed_by_name_for_staff(
    client: TestClient, db_session: Session, headers: dict[str, str]
) -> None:
    response = client.get("/api/jobs", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "jobs": [
            {
                "id": _job_id(db_session, "Penfield Sewer Replacement"),
                "name": "Penfield Sewer Replacement",
            },
            {"id": _job_id(db_session, "Route 104 Widening"), "name": "Route 104 Widening"},
        ]
    }
    assert client.get("/api/jobs").status_code == 401
