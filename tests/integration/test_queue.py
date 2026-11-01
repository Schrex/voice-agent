"""GET /api/requests: the queue of open Requests (ticket #9, spec J9)."""

import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Foreman, Job, Request, Staff
from app.services.roster import load_roster_file, seed_roster

SAMPLE_ROSTER = Path(__file__).resolve().parents[2] / "backend" / "seed" / "sample_roster.json"

SECRET = "test-jwt-secret-at-least-32-bytes-long"
T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    yield


@pytest.fixture
def headers(db_session: Session) -> dict[str, str]:
    """A signed-in coordinator, on a seeded roster."""
    seed_roster(db_session, load_roster_file(SAMPLE_ROSTER))
    staff = Staff(id=uuid.uuid4(), name="Pat", email="pat@example.com", role="coordinator")
    db_session.add(staff)
    db_session.flush()
    claims = {"sub": str(staff.id), "aud": "authenticated", "exp": int(time.time()) + 3600}
    return {"Authorization": f"Bearer {jwt.encode(claims, SECRET, algorithm='HS256')}"}


def _add(
    session: Session,
    need: str,
    *,
    status: str = "Recorded",
    urgency: str | None = "Today",
    recorded_at: datetime = T0,
    job: str | None = "Route 104 Widening",
    job_spoken: str | None = None,
) -> Request:
    request = Request(
        foreman_id=session.scalars(select(Foreman.id).where(Foreman.first_name == "Dale")).one(),
        job_id=None
        if job is None
        else session.scalars(select(Job.id).where(Job.name == job)).one(),
        job_spoken=job_spoken or job,
        category="Trucking",
        need=need,
        quantity=Decimal("3"),
        unit="trucks",
        needed_by_spoken="tomorrow at seven",
        needed_by=datetime(2026, 11, 2, 12, 0, tzinfo=UTC),
        urgency=urgency,
        status=status,
        source="ai_call",
        recorded_at=recorded_at,
    )
    if status == "Resolved":  # a Resolved request always carries its Outcome (#12)
        request.outcome, request.explanation, request.resolved_at = "Fulfilled", "Sent", T0
    session.add(request)
    session.flush()
    return request


def _needs(client: TestClient, headers: dict[str, str]) -> list[str]:
    response = client.get("/api/requests", headers=headers)
    assert response.status_code == 200
    return [r["need"] for r in response.json()["requests"]]


def test_queue_requires_a_staff_token(client: TestClient) -> None:
    assert client.get("/api/requests").status_code == 401


def test_queue_lists_the_request_fields(
    client: TestClient, db_session: Session, headers: dict[str, str]
) -> None:
    request = _add(
        db_session, "tri-axle dump trucks", job="Penfield Sewer Replacement", job_spoken="Penfield"
    )

    response = client.get("/api/requests", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "requests": [
            {
                "ref": f"R-{request.ref}",
                "job": "Penfield Sewer Replacement",
                "job_spoken": "Penfield",
                "need": "tri-axle dump trucks",
                "quantity": "3",
                "unit": "trucks",
                "needed_by": "2026-11-02T12:00:00Z",
                "needed_by_spoken": "tomorrow at seven",
                "urgency": "Today",
                "status": "Recorded",
                "recorded_at": "2026-11-01T12:00:00Z",
            }
        ]
    }


def test_queue_excludes_resolved_and_draft(
    client: TestClient, db_session: Session, headers: dict[str, str]
) -> None:
    for status in ("Draft", "Recorded", "Acknowledged", "In Progress", "Resolved"):
        _add(db_session, status, status=status)

    assert sorted(_needs(client, headers)) == ["Acknowledged", "In Progress", "Recorded"]


def test_queue_is_sorted_by_urgency_then_oldest_first(
    client: TestClient, db_session: Session, headers: dict[str, str]
) -> None:
    hour = timedelta(hours=1)
    _add(db_session, "planned, oldest", urgency="Planned", recorded_at=T0 - 5 * hour)
    _add(db_session, "today, newer", urgency="Today", recorded_at=T0)
    _add(db_session, "no urgency yet", urgency=None, recorded_at=T0 - 9 * hour)
    _add(db_session, "emergency, newest", urgency="Emergency", recorded_at=T0 + hour)
    _add(db_session, "today, older", urgency="Today", recorded_at=T0 - hour)
    _add(db_session, "planned, newer", urgency="Planned", recorded_at=T0 - 2 * hour)

    assert _needs(client, headers) == [
        "emergency, newest",
        "today, older",
        "today, newer",
        "planned, oldest",
        "planned, newer",
        "no urgency yet",
    ]


def test_quantity_is_shown_as_said(
    client: TestClient, db_session: Session, headers: dict[str, str]
) -> None:
    whole = _add(db_session, "whole")
    whole.quantity = Decimal("3.000")
    half = _add(db_session, "half", recorded_at=T0 + timedelta(minutes=1))
    half.quantity = Decimal("2.5")
    none = _add(db_session, "none", recorded_at=T0 + timedelta(minutes=2))
    none.quantity = None
    none.unit = None
    db_session.flush()

    rows = client.get("/api/requests", headers=headers).json()["requests"]

    assert [(r["quantity"], r["unit"]) for r in rows] == [
        ("3", "trucks"),
        ("2.5", "trucks"),
        (None, None),
    ]


def test_unmatched_request_is_listed_without_a_job_and_with_what_the_foreman_said(
    client: TestClient, db_session: Session, headers: dict[str, str]
) -> None:
    """Spec J1 step 3 / §5 flags: a Request whose Job matched nothing shows as Unmatched."""
    _add(db_session, "excavator operator", job=None, job_spoken="the Smith pit")
    _add(db_session, "tri-axle dump trucks")

    rows = client.get("/api/requests", headers=headers).json()["requests"]

    assert [(r["need"], r["job"], r["job_spoken"]) for r in rows] == [
        ("excavator operator", None, "the Smith pit"),
        ("tri-axle dump trucks", "Route 104 Widening", "Route 104 Widening"),
    ]
