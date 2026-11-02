"""Merge duplicates (ticket #33; spec J2 "Coordinators can also merge duplicates", J9).

Request A merged into Request B: A is Resolved with a pointer to B, both carry the merge in
their history, and a status lookup of A reports B.
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
from app.services.merges import status_request
from app.services.requests import NewItem, RequestNotFound, submit_requests
from app.services.roster import load_roster_file, seed_roster
from app.services.uninformed import uninformed_requests

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


def _merge(
    client: TestClient,
    headers: dict[str, str],
    ref: str,
    into: str,
    outcome: str | None = "Withdrawn",
    explanation: str | None = "Same trucks as the other request",
) -> Any:
    return client.post(
        f"/api/requests/{ref}/merge",
        headers=headers,
        json={"into": into, "outcome": outcome, "explanation": explanation},
    )


def test_merge_resolves_a_with_a_pointer_to_b_and_records_history_on_both(
    client: TestClient, db_session: Session, headers: dict[str, str], staff: Staff, dispatch: Owner
) -> None:
    a = _record(db_session)
    b = _acknowledged(client, db_session, headers, dispatch)

    response = _merge(client, headers, a, b)

    assert response.status_code == 200
    detail_a = _detail(client, headers, a)
    assert response.json() == detail_a
    assert detail_a["status"] == "Resolved"
    assert detail_a["outcome"] == "Withdrawn"
    assert detail_a["explanation"] == "Same trucks as the other request"
    assert detail_a["resolved_at"] == "2026-11-01T14:45:10Z"
    assert detail_a["merged_into"] == b
    actor = {"type": "staff", "id": str(staff.id), "name": "Pat Lee"}
    assert detail_a["events"][-1] == {
        "at": "2026-11-01T14:45:10Z",
        "actor": actor,
        "kind": "merged",
        "before": {
            "status": "Recorded",
            "outcome": None,
            "explanation": None,
            "resolved_at": None,
            "merged_into": None,
        },
        "after": {
            "status": "Resolved",
            "outcome": "Withdrawn",
            "explanation": "Same trucks as the other request",
            "resolved_at": "2026-11-01T14:45:10Z",
            "merged_into": b,
        },
    }
    detail_b = _detail(client, headers, b)
    assert detail_b["status"] == "Acknowledged"
    assert detail_b["merged_into"] is None
    assert detail_b["events"][-1] == {
        "at": "2026-11-01T14:45:10Z",
        "actor": actor,
        "kind": "merged_in",
        "before": {"merged_from": None},
        "after": {"merged_from": a},
    }
    queue = [r["ref"] for r in client.get("/api/requests", headers=headers).json()["requests"]]
    assert a not in queue and b in queue


def test_cannot_merge_into_a_resolved_request(
    client: TestClient, db_session: Session, headers: dict[str, str]
) -> None:
    a = _record(db_session)
    b = _record(db_session)
    assert (
        client.post(
            f"/api/requests/{b}/resolve",
            headers=headers,
            json={"outcome": "Fulfilled", "explanation": "Sent"},
        ).status_code
        == 200
    )
    before_a, before_b = _detail(client, headers, a), _detail(client, headers, b)

    response = _merge(client, headers, a, b)

    assert response.status_code == 422
    assert _detail(client, headers, a) == before_a
    assert _detail(client, headers, b) == before_b


def test_cannot_merge_into_itself(
    client: TestClient, db_session: Session, headers: dict[str, str]
) -> None:
    a = _record(db_session)
    before = _detail(client, headers, a)

    response = _merge(client, headers, a, a)

    assert response.status_code == 422
    assert _detail(client, headers, a) == before


def test_a_merged_request_cannot_be_merged_again_and_nothing_merges_into_it(
    client: TestClient, db_session: Session, headers: dict[str, str]
) -> None:
    a, b, c = _record(db_session), _record(db_session), _record(db_session)
    assert _merge(client, headers, a, b).status_code == 200

    assert _merge(client, headers, a, c).status_code == 422
    assert _merge(client, headers, c, a).status_code == 422
    assert _kinds(client, headers, c) == ["recorded"]
    assert _detail(client, headers, a)["merged_into"] == b


@pytest.mark.parametrize(
    ("outcome", "explanation"),
    [(None, "Duplicate"), ("Withdrawn", None), ("Withdrawn", "  "), ("Merged", "Duplicate")],
)
def test_merge_needs_an_outcome_and_explanation_like_resolve(
    client: TestClient,
    db_session: Session,
    headers: dict[str, str],
    outcome: str | None,
    explanation: str | None,
) -> None:
    a, b = _record(db_session), _record(db_session)

    response = _merge(client, headers, a, b, outcome, explanation)

    assert response.status_code == 422
    assert _kinds(client, headers, a) == ["recorded"]
    assert _kinds(client, headers, b) == ["recorded"]


def test_merge_unknown_refs_are_404_and_needs_a_staff_token(
    client: TestClient, db_session: Session, headers: dict[str, str]
) -> None:
    a = _record(db_session)

    assert _merge(client, headers, "R-999999", a).status_code == 404
    assert _merge(client, headers, a, "R-999999").status_code == 404
    assert _merge(client, headers, a, "nonsense").status_code == 404
    assert _kinds(client, headers, a) == ["recorded"]
    assert client.post(f"/api/requests/{a}/merge", json={"into": a}).status_code == 401


def test_status_lookup_of_a_merged_ref_reports_the_request_it_was_merged_into(
    client: TestClient, db_session: Session, headers: dict[str, str]
) -> None:
    a, b, c = _record(db_session), _record(db_session), _record(db_session)
    assert _merge(client, headers, a, b).status_code == 200
    assert _merge(client, headers, b, c).status_code == 200

    assert status_request(db_session, a).ref_display == c
    assert status_request(db_session, b).ref_display == c
    assert status_request(db_session, c).ref_display == c
    with pytest.raises(RequestNotFound):
        status_request(db_session, "R-999999")


def test_a_merged_request_never_shows_uninformed(
    client: TestClient, db_session: Session, headers: dict[str, str], dispatch: Owner
) -> None:
    """Product owner decision on #32/#33: the surviving Request carries the flag."""
    a = _record(db_session)
    b = _acknowledged(client, db_session, headers, dispatch)
    assert _merge(client, headers, a, b).status_code == 200

    later = NOW + timedelta(hours=3)
    assert [row.ref for row in uninformed_requests(db_session, later)] == []
    assert _detail(client, headers, a)["uninformed"] is False
