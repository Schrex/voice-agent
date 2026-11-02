"""Admin: roster and jobs (#34). `/api/admin/foremen` and `/api/admin/jobs`.

Open to every staff member (one Staff role, ADR 0006).
"""

import re
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Staff
from app.services.roster import load_roster_file, seed_roster

SAMPLE_ROSTER = Path(__file__).resolve().parents[2] / "backend" / "seed" / "sample_roster.json"
SECRET = "test-jwt-secret-at-least-32-bytes-long"


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    monkeypatch.setenv("HOOK_SECRET", "test-hook-secret")
    monkeypatch.setenv("OFFICE_MAIN_NUMBER", "585-555-0100")
    yield


def _headers_for(session: Session, role: str) -> dict[str, str]:
    staff = Staff(id=uuid.uuid4(), name=f"Pat {role}", email="pat@example.com")
    session.add(staff)
    session.flush()
    claims: dict[str, Any] = {
        "sub": str(staff.id),
        "aud": "authenticated",
        "exp": int(time.time()) + 3600,
    }
    return {"Authorization": f"Bearer {jwt.encode(claims, SECRET, algorithm='HS256')}"}


@pytest.fixture
def admin(db_session: Session) -> dict[str, str]:
    return _headers_for(db_session, "admin")


@pytest.fixture
def coordinator(db_session: Session) -> dict[str, str]:
    return _headers_for(db_session, "coordinator")


@pytest.fixture
def seeded(db_session: Session) -> None:
    seed_roster(db_session, load_roster_file(SAMPLE_ROSTER))


def _call_start(client: TestClient, caller_e164: str) -> dict[str, Any]:
    response = client.post(
        "/hooks/call-start",
        json={"caller_id": caller_e164, "conversation_id": f"conv_admin_{uuid.uuid4().hex}"},
        headers={"X-Hook-Secret": "test-hook-secret"},
    )
    assert response.status_code == 200
    variables: dict[str, Any] = response.json()["dynamic_variables"]
    return variables


def _offered_jobs(client: TestClient) -> list[str]:
    """Job names the agent gets at call start ("<name> (job_id <id>)", joined by "; ")."""
    jobs: str = _call_start(client, "+15855550101")["jobs"]
    return [re.sub(r" \(job_id \d+\)$", "", job) for job in jobs.split("; ")]


# --- Access ------------------------------------------------------------------------------

ADMIN_CALLS = [
    ("GET", "/api/admin/foremen", None),
    ("POST", "/api/admin/foremen", {"first_name": "A", "last_name": "B", "phones": []}),
    ("PATCH", "/api/admin/foremen/1", {"active": False}),
    ("POST", "/api/admin/foremen/1/phones", {"e164": "+15855550190"}),
    ("DELETE", "/api/admin/foremen/1/phones/1", None),
    ("GET", "/api/admin/jobs", None),
    ("POST", "/api/admin/jobs", {"name": "New Job", "aliases": []}),
    ("PATCH", "/api/admin/jobs/1", {"active": False}),
    ("POST", "/api/admin/jobs/1/aliases", {"alias": "new"}),
    ("DELETE", "/api/admin/jobs/1/aliases/1", None),
]


@pytest.mark.parametrize(("method", "path", "body"), ADMIN_CALLS)
def test_every_staff_member_can_use_admin_endpoints(
    client: TestClient, coordinator: dict[str, str], method: str, path: str, body: Any
) -> None:
    """One Staff role (ADR 0006): no staff member gets 403 here."""
    response = client.request(method, path, json=body, headers=coordinator)
    assert response.status_code not in (401, 403)


@pytest.mark.parametrize(("method", "path", "body"), ADMIN_CALLS)
def test_admin_endpoints_need_a_token(
    client: TestClient, method: str, path: str, body: Any
) -> None:
    assert client.request(method, path, json=body).status_code == 401


# --- Foremen -----------------------------------------------------------------------------


def _foreman(client: TestClient, admin: dict[str, str], last_name: str) -> dict[str, Any]:
    foremen = client.get("/api/admin/foremen", headers=admin).json()
    [match] = [f for f in foremen if f["last_name"] == last_name]
    return dict(match)


def _phones(foreman: dict[str, Any]) -> list[str]:
    return [p["e164"] for p in foreman["phones"]]


def test_admin_lists_foremen_with_phones_and_active_flag(
    client: TestClient, admin: dict[str, str], seeded: None
) -> None:
    response = client.get("/api/admin/foremen", headers=admin)

    assert response.status_code == 200
    summary = [(f["first_name"], f["last_name"], f["active"], _phones(f)) for f in response.json()]
    # Sorted by last name, then first name.
    assert summary == [
        ("Marco", "Bellini", False, ["+15855550104"]),
        ("Dale", "Kramer", True, ["+15855550101", "+15855550102"]),
        ("Rita", "Owens", True, ["+15855550103"]),
    ]


def test_admin_adds_a_foreman_whose_number_is_then_rostered(
    client: TestClient, admin: dict[str, str]
) -> None:
    response = client.post(
        "/api/admin/foremen",
        json={"first_name": "Lena", "last_name": "Ortiz", "phones": ["+15855550120"]},
        headers=admin,
    )

    assert response.status_code == 201
    created = response.json()
    assert (created["first_name"], created["active"], _phones(created)) == (
        "Lena",
        True,
        ["+15855550120"],
    )
    assert _foreman(client, admin, "Ortiz")["id"] == created["id"]
    assert _call_start(client, "+15855550120")["foreman_first_name"] == "Lena"


def test_deactivated_foreman_is_rejected_at_the_next_call_start(
    client: TestClient, admin: dict[str, str], seeded: None
) -> None:
    rita = _foreman(client, admin, "Owens")

    response = client.patch(
        f"/api/admin/foremen/{rita['id']}", json={"active": False}, headers=admin
    )

    assert response.status_code == 200
    assert response.json()["active"] is False
    variables = _call_start(client, "+15855550103")
    assert variables["rejected"] is True
    assert variables["foreman_first_name"] == ""


def test_reactivated_foreman_is_accepted_again(
    client: TestClient, admin: dict[str, str], seeded: None
) -> None:
    marco = _foreman(client, admin, "Bellini")

    client.patch(f"/api/admin/foremen/{marco['id']}", json={"active": True}, headers=admin)

    assert _call_start(client, "+15855550104")["foreman_first_name"] == "Marco"


def test_admin_renames_a_foreman(client: TestClient, admin: dict[str, str], seeded: None) -> None:
    dale = _foreman(client, admin, "Kramer")

    response = client.patch(
        f"/api/admin/foremen/{dale['id']}", json={"first_name": "Dallas"}, headers=admin
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["first_name"], body["last_name"], body["active"]) == ("Dallas", "Kramer", True)


def test_a_number_already_on_the_roster_is_refused(
    client: TestClient, admin: dict[str, str], seeded: None
) -> None:
    rita = _foreman(client, admin, "Owens")

    on_new = client.post(
        "/api/admin/foremen",
        json={"first_name": "Lena", "last_name": "Ortiz", "phones": ["+15855550101"]},
        headers=admin,
    )
    on_existing = client.post(
        f"/api/admin/foremen/{rita['id']}/phones", json={"e164": "+15855550101"}, headers=admin
    )

    assert on_new.status_code == 409
    assert on_existing.status_code == 409
    foremen = client.get("/api/admin/foremen", headers=admin).json()
    assert [f["last_name"] for f in foremen] == ["Bellini", "Kramer", "Owens"]
    assert _phones(_foreman(client, admin, "Owens")) == ["+15855550103"]


@pytest.mark.parametrize("e164", ["585-555-0120", "+0123", "", "+1585555012012345678"])
def test_a_number_not_in_e164_is_422(
    client: TestClient, admin: dict[str, str], seeded: None, e164: str
) -> None:
    rita = _foreman(client, admin, "Owens")

    response = client.post(
        f"/api/admin/foremen/{rita['id']}/phones", json={"e164": e164}, headers=admin
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"first_name": " ", "last_name": "Ortiz", "phones": []},
        {"first_name": "Lena", "last_name": "", "phones": []},
    ],
)
def test_blank_foreman_name_is_422(
    client: TestClient, admin: dict[str, str], body: dict[str, Any]
) -> None:
    assert client.post("/api/admin/foremen", json=body, headers=admin).status_code == 422


def test_admin_adds_and_removes_a_phone(
    client: TestClient, admin: dict[str, str], seeded: None
) -> None:
    rita = _foreman(client, admin, "Owens")

    added = client.post(
        f"/api/admin/foremen/{rita['id']}/phones", json={"e164": "+15855550130"}, headers=admin
    )
    assert added.status_code == 201
    assert _phones(added.json()) == ["+15855550103", "+15855550130"]

    old = next(p for p in added.json()["phones"] if p["e164"] == "+15855550103")
    removed = client.delete(f"/api/admin/foremen/{rita['id']}/phones/{old['id']}", headers=admin)
    assert removed.status_code == 200
    assert _phones(removed.json()) == ["+15855550130"]

    assert _call_start(client, "+15855550103")["rejected"] is True
    assert _call_start(client, "+15855550130")["foreman_first_name"] == "Rita"


def test_removing_another_foremans_phone_is_404(
    client: TestClient, admin: dict[str, str], seeded: None
) -> None:
    rita = _foreman(client, admin, "Owens")
    dale_phone = _foreman(client, admin, "Kramer")["phones"][0]

    response = client.delete(
        f"/api/admin/foremen/{rita['id']}/phones/{dale_phone['id']}", headers=admin
    )

    assert response.status_code == 404
    assert len(_foreman(client, admin, "Kramer")["phones"]) == 2


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("PATCH", "/api/admin/foremen/999999", {"active": False}),
        ("POST", "/api/admin/foremen/999999/phones", {"e164": "+15855550190"}),
        ("DELETE", "/api/admin/foremen/999999/phones/1", None),
        ("PATCH", "/api/admin/jobs/999999", {"active": False}),
        ("POST", "/api/admin/jobs/999999/aliases", {"alias": "x"}),
        ("DELETE", "/api/admin/jobs/999999/aliases/1", None),
    ],
)
def test_unknown_foreman_or_job_is_404(
    client: TestClient, admin: dict[str, str], method: str, path: str, body: Any
) -> None:
    assert client.request(method, path, json=body, headers=admin).status_code == 404


# --- Jobs --------------------------------------------------------------------------------


def _job(client: TestClient, admin: dict[str, str], name: str) -> dict[str, Any]:
    jobs = client.get("/api/admin/jobs", headers=admin).json()
    [match] = [j for j in jobs if j["name"] == name]
    return dict(match)


def _aliases(job: dict[str, Any]) -> list[str]:
    return [a["alias"] for a in job["aliases"]]


def test_admin_lists_jobs_with_aliases_and_active_flag(
    client: TestClient, admin: dict[str, str], seeded: None
) -> None:
    response = client.get("/api/admin/jobs", headers=admin)

    assert response.status_code == 200
    assert [(j["name"], j["active"], _aliases(j)) for j in response.json()] == [
        ("Lakeside Plaza Site Work", False, ["Lakeside"]),
        ("Penfield Sewer Replacement", True, ["Penfield sewer"]),
        ("Route 104 Widening", True, ["Route 104", "104 job"]),
    ]


def test_admin_adds_a_job_offered_at_the_next_call_start(
    client: TestClient, admin: dict[str, str], seeded: None
) -> None:
    response = client.post(
        "/api/admin/jobs", json={"name": "Brighton Culvert", "aliases": ["culvert"]}, headers=admin
    )

    assert response.status_code == 201
    assert (response.json()["active"], _aliases(response.json())) == (True, ["culvert"])
    assert _offered_jobs(client) == [
        "Brighton Culvert",
        "Penfield Sewer Replacement",
        "Route 104 Widening",
    ]


def test_deactivated_job_is_not_offered_at_call_start(
    client: TestClient, admin: dict[str, str], seeded: None
) -> None:
    penfield = _job(client, admin, "Penfield Sewer Replacement")

    response = client.patch(
        f"/api/admin/jobs/{penfield['id']}", json={"active": False}, headers=admin
    )

    assert response.status_code == 200
    assert response.json()["active"] is False
    assert _offered_jobs(client) == ["Route 104 Widening"]


def test_admin_renames_a_job(client: TestClient, admin: dict[str, str], seeded: None) -> None:
    route = _job(client, admin, "Route 104 Widening")

    response = client.patch(
        f"/api/admin/jobs/{route['id']}", json={"name": "Route 104 Reconstruction"}, headers=admin
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Route 104 Reconstruction"
    assert _aliases(response.json()) == ["Route 104", "104 job"]


def test_duplicate_job_name_is_409(client: TestClient, admin: dict[str, str], seeded: None) -> None:
    penfield = _job(client, admin, "Penfield Sewer Replacement")

    created = client.post(
        "/api/admin/jobs", json={"name": "Route 104 Widening", "aliases": []}, headers=admin
    )
    renamed = client.patch(
        f"/api/admin/jobs/{penfield['id']}", json={"name": "Route 104 Widening"}, headers=admin
    )

    assert created.status_code == 409
    assert renamed.status_code == 409
    assert len(client.get("/api/admin/jobs", headers=admin).json()) == 3
    assert _job(client, admin, "Penfield Sewer Replacement")["id"] == penfield["id"]


def test_admin_adds_and_removes_an_alias(
    client: TestClient, admin: dict[str, str], seeded: None
) -> None:
    penfield = _job(client, admin, "Penfield Sewer Replacement")

    added = client.post(
        f"/api/admin/jobs/{penfield['id']}/aliases", json={"alias": "the sewer job"}, headers=admin
    )
    assert added.status_code == 201
    assert _aliases(added.json()) == ["Penfield sewer", "the sewer job"]

    old = added.json()["aliases"][0]
    removed = client.delete(f"/api/admin/jobs/{penfield['id']}/aliases/{old['id']}", headers=admin)
    assert removed.status_code == 200
    assert _aliases(removed.json()) == ["the sewer job"]
    assert _aliases(_job(client, admin, "Penfield Sewer Replacement")) == ["the sewer job"]


def test_an_alias_the_admin_adds_is_matched_by_find_jobs_on_the_next_call(
    client: TestClient, admin: dict[str, str], seeded: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#34 DoD: "add alias → spoken alias matches on next call" (via #13's `find_jobs`)."""
    monkeypatch.setenv("TOOL_SECRET", "test-tool-secret")
    conversation = f"conv_admin_{uuid.uuid4().hex}"
    started = client.post(
        "/hooks/call-start",
        json={"caller_id": "+15855550101", "conversation_id": conversation},
        headers={"X-Hook-Secret": "test-hook-secret"},
    )
    assert started.status_code == 200
    tool_headers = {"X-Tool-Secret": "test-tool-secret", "X-Conversation-Id": conversation}

    def find(spoken: str) -> Any:
        response = client.post("/tools/find_jobs", json={"query": spoken}, headers=tool_headers)
        assert response.status_code == 200
        return response.json()

    assert find("the Fairport lift station") == []
    penfield = _job(client, admin, "Penfield Sewer Replacement")

    added = client.post(
        f"/api/admin/jobs/{penfield['id']}/aliases",
        json={"alias": "the Fairport lift station"},
        headers=admin,
    )
    assert added.status_code == 201

    [match] = find("the Fairport lift station")
    assert (match["job_id"], match["name"]) == (penfield["id"], "Penfield Sewer Replacement")


def test_duplicate_alias_on_the_same_job_is_409(
    client: TestClient, admin: dict[str, str], seeded: None
) -> None:
    penfield = _job(client, admin, "Penfield Sewer Replacement")

    response = client.post(
        f"/api/admin/jobs/{penfield['id']}/aliases",
        json={"alias": "Penfield sewer"},
        headers=admin,
    )

    assert response.status_code == 409


def test_removing_another_jobs_alias_is_404(
    client: TestClient, admin: dict[str, str], seeded: None
) -> None:
    penfield = _job(client, admin, "Penfield Sewer Replacement")
    route_alias = _job(client, admin, "Route 104 Widening")["aliases"][0]

    response = client.delete(
        f"/api/admin/jobs/{penfield['id']}/aliases/{route_alias['id']}", headers=admin
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "body", [{"name": "  ", "aliases": []}, {"name": "Brighton Culvert", "aliases": [""]}]
)
def test_blank_job_name_or_alias_is_422(
    client: TestClient, admin: dict[str, str], body: dict[str, Any]
) -> None:
    assert client.post("/api/admin/jobs", json=body, headers=admin).status_code == 422
