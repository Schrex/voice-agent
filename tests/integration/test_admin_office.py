"""Admin: owners, category defaults, staff, duty roster, settings (#35). Open to every staff member
(one Staff role, ADR 0006)."""

import time
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.clock import get_clock
from app.db.models import CategoryOwnerDefault, DutyRoster, Staff
from app.main import app
from app.services.settings import ack_windows

SECRET = "test-jwt-secret-at-least-32-bytes-long"
# 2026-11-01 08:00 in New York (EST since 1 Nov 2026 02:00).
NOW = datetime(2026, 11, 1, 13, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    app.dependency_overrides[get_clock] = lambda: lambda: NOW
    yield


def _staff(session: Session, label: str, name: str | None = None) -> Staff:
    staff = Staff(id=uuid.uuid4(), name=name or f"Pat {label}", email=f"{uuid.uuid4().hex}@x.com")
    session.add(staff)
    session.flush()
    return staff


def _headers(staff: Staff) -> dict[str, str]:
    claims: dict[str, Any] = {
        "sub": str(staff.id),
        "aud": "authenticated",
        "exp": int(time.time()) + 3600,
    }
    return {"Authorization": f"Bearer {jwt.encode(claims, SECRET, algorithm='HS256')}"}


@pytest.fixture
def admin(db_session: Session) -> dict[str, str]:
    return _headers(_staff(db_session, "admin", "Avery Admin"))


@pytest.fixture
def coordinator(db_session: Session) -> dict[str, str]:
    return _headers(_staff(db_session, "coordinator"))


def default_owner_id(session: Session, category: str) -> int | None:
    session.expire_all()
    default = session.get(CategoryOwnerDefault, category)
    return default.owner_id if default else None


# --- Access ------------------------------------------------------------------------------

ADMIN_CALLS = [
    ("GET", "/api/admin/owners", None),
    ("POST", "/api/admin/owners", {"name": "Dispatch"}),
    ("PATCH", "/api/admin/owners/1", {"name": "Dispatch"}),
    ("GET", "/api/admin/category-defaults", None),
    ("PUT", "/api/admin/category-defaults/Trucking", {"owner_id": 1}),
    ("GET", "/api/admin/staff", None),
    ("POST", "/api/admin/staff", {"id": str(uuid.uuid4()), "name": "A", "email": "a@x.com"}),
    ("PATCH", f"/api/admin/staff/{uuid.uuid4()}", {"name": "A"}),
    ("GET", "/api/admin/duty", None),
    ("PUT", "/api/admin/duty/2026-11-02", {"on_duty_staff_id": str(uuid.uuid4())}),
    ("DELETE", "/api/admin/duty/2026-11-02", None),
    ("GET", "/api/admin/settings", None),
    ("PATCH", "/api/admin/settings", {"ack_window_today_min": 30}),
]


@pytest.mark.parametrize(("method", "path", "body"), ADMIN_CALLS)
def test_every_staff_member_can_use_admin_office_endpoints(
    client: TestClient, coordinator: dict[str, str], method: str, path: str, body: Any
) -> None:
    """One Staff role (ADR 0006): no staff member gets 403 here."""
    response = client.request(method, path, json=body, headers=coordinator)
    assert response.status_code not in (401, 403)


@pytest.mark.parametrize(("method", "path", "body"), ADMIN_CALLS)
def test_admin_office_endpoints_need_a_token(
    client: TestClient, method: str, path: str, body: Any
) -> None:
    assert client.request(method, path, json=body).status_code == 401


# --- Settings: office line and acknowledgment windows ------------------------------------


def test_settings_start_at_the_spec_defaults(client: TestClient, admin: dict[str, str]) -> None:
    response = client.get("/api/admin/settings", headers=admin)
    assert response.status_code == 200
    assert response.json() == {
        "office_line_e164": None,
        "ack_window_today_min": 15,
        "ack_window_planned_min": 120,
    }


def test_changing_the_today_window_changes_the_ack_window(
    client: TestClient, admin: dict[str, str], db_session: Session
) -> None:
    assert ack_windows(db_session).today == timedelta(minutes=15)

    response = client.patch("/api/admin/settings", json={"ack_window_today_min": 30}, headers=admin)

    assert response.status_code == 200
    assert response.json()["ack_window_today_min"] == 30
    assert response.json()["ack_window_planned_min"] == 120
    windows = ack_windows(db_session)
    assert windows.today == timedelta(minutes=30)
    assert windows.planned == timedelta(hours=2)


def test_admin_sets_the_planned_window_and_office_line(
    client: TestClient, admin: dict[str, str], db_session: Session
) -> None:
    body = {"ack_window_planned_min": 240, "office_line_e164": "+15855550100"}
    response = client.patch("/api/admin/settings", json=body, headers=admin)
    assert response.status_code == 200
    assert client.get("/api/admin/settings", headers=admin).json() == {
        "office_line_e164": "+15855550100",
        "ack_window_today_min": 15,
        "ack_window_planned_min": 240,
    }
    assert ack_windows(db_session).planned == timedelta(hours=4)

    cleared = client.patch("/api/admin/settings", json={"office_line_e164": None}, headers=admin)
    assert cleared.json()["office_line_e164"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"ack_window_today_min": 0},
        {"ack_window_today_min": -5},
        {"ack_window_planned_min": 0},
        {"ack_window_today_min": None},
        {"office_line_e164": "585-555-0100"},
    ],
)
def test_invalid_settings_are_422_and_change_nothing(
    client: TestClient, admin: dict[str, str], body: dict[str, Any]
) -> None:
    before = client.get("/api/admin/settings", headers=admin).json()
    assert client.patch("/api/admin/settings", json=body, headers=admin).status_code == 422
    assert client.get("/api/admin/settings", headers=admin).json() == before


# --- Owners and category defaults --------------------------------------------------------


def _add_owner(client: TestClient, admin: dict[str, str], name: str, **extra: Any) -> int:
    response = client.post("/api/admin/owners", json={"name": name, **extra}, headers=admin)
    assert response.status_code == 201, response.text
    owner_id: int = response.json()["id"]
    return owner_id


def test_admin_adds_owners_and_they_are_offered_for_acknowledge(
    client: TestClient, admin: dict[str, str]
) -> None:
    _add_owner(client, admin, "Equipment Manager")
    _add_owner(client, admin, "Dispatch", phone_e164="+15855550111", email="dispatch@x.com")

    listed = client.get("/api/admin/owners", headers=admin).json()
    assert [(o["name"], o["phone_e164"], o["email"]) for o in listed] == [
        ("Dispatch", "+15855550111", "dispatch@x.com"),
        ("Equipment Manager", None, None),
    ]
    offered = client.get("/api/owners", headers=admin).json()["owners"]
    assert [o["name"] for o in offered] == ["Dispatch", "Equipment Manager"]


def test_admin_renames_an_owner_and_clears_a_phone(
    client: TestClient, admin: dict[str, str]
) -> None:
    owner_id = _add_owner(client, admin, "Dispatch", phone_e164="+15855550111")
    response = client.patch(
        f"/api/admin/owners/{owner_id}",
        json={"name": "Trucking Dispatch", "phone_e164": None},
        headers=admin,
    )
    assert response.status_code == 200
    assert response.json() == {
        "id": owner_id,
        "name": "Trucking Dispatch",
        "phone_e164": None,
        "email": None,
    }


def test_owner_names_are_unique(client: TestClient, admin: dict[str, str]) -> None:
    first = _add_owner(client, admin, "Dispatch")
    second = _add_owner(client, admin, "Yard")
    assert (
        client.post("/api/admin/owners", json={"name": "Dispatch"}, headers=admin).status_code
        == 409
    )
    renamed = client.patch(f"/api/admin/owners/{second}", json={"name": "Dispatch"}, headers=admin)
    assert renamed.status_code == 409
    # Renaming an Owner to its own name is not a clash.
    same = client.patch(f"/api/admin/owners/{first}", json={"name": "Dispatch"}, headers=admin)
    assert same.status_code == 200


@pytest.mark.parametrize(
    "body", [{"name": "  "}, {"name": "A", "phone_e164": "5855550111"}, {"name": "A", "email": "x"}]
)
def test_invalid_owner_is_422(client: TestClient, admin: dict[str, str], body: Any) -> None:
    assert client.post("/api/admin/owners", json=body, headers=admin).status_code == 422


def test_unknown_owner_is_404(client: TestClient, admin: dict[str, str]) -> None:
    assert (
        client.patch("/api/admin/owners/999999", json={"name": "X"}, headers=admin).status_code
        == 404
    )


def test_category_defaults_list_every_category(client: TestClient, admin: dict[str, str]) -> None:
    listed = client.get("/api/admin/category-defaults", headers=admin).json()
    assert [d["category"] for d in listed] == [
        "Trucking",
        "Equipment",
        "Equipment Repair",
        "Material",
        "Labor",
        "Information",
        "Callback",
        "Other",
    ]
    assert all(d["owner_id"] is None for d in listed)


def test_admin_sets_a_category_default_and_acknowledge_offers_it(
    client: TestClient, admin: dict[str, str], db_session: Session
) -> None:
    dispatch = _add_owner(client, admin, "Dispatch")
    yard = _add_owner(client, admin, "Yard")

    put = client.put(
        "/api/admin/category-defaults/Trucking", json={"owner_id": dispatch}, headers=admin
    )
    assert put.status_code == 200
    assert put.json() == {"category": "Trucking", "owner_id": dispatch}
    client.put("/api/admin/category-defaults/Trucking", json={"owner_id": yard}, headers=admin)

    listed = {
        d["category"]: d["owner_id"]
        for d in client.get("/api/admin/category-defaults", headers=admin).json()
    }
    assert listed["Trucking"] == yard
    assert listed["Material"] is None

    assert default_owner_id(db_session, "Trucking") == yard

    cleared = client.put(
        "/api/admin/category-defaults/Trucking", json={"owner_id": None}, headers=admin
    )
    assert cleared.status_code == 200
    assert default_owner_id(db_session, "Trucking") is None


def test_category_default_needs_a_known_category_and_owner(
    client: TestClient, admin: dict[str, str]
) -> None:
    dispatch = _add_owner(client, admin, "Dispatch")
    unknown_category = client.put(
        "/api/admin/category-defaults/Snacks", json={"owner_id": dispatch}, headers=admin
    )
    assert unknown_category.status_code == 404
    unknown_owner = client.put(
        "/api/admin/category-defaults/Trucking", json={"owner_id": 999999}, headers=admin
    )
    assert unknown_owner.status_code == 422


# --- Staff -------------------------------------------------------------------------------


def test_admin_adds_staff_who_can_then_sign_in(client: TestClient, admin: dict[str, str]) -> None:
    user_id = uuid.uuid4()
    body = {
        "id": str(user_id),
        "name": "Casey Coordinator",
        "email": "casey@x.com",
        "phone_e164": "+15855550123",
    }
    response = client.post("/api/admin/staff", json=body, headers=admin)
    assert response.status_code == 201
    assert response.json() == body

    claims: dict[str, Any] = {
        "sub": str(user_id),
        "aud": "authenticated",
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(claims, SECRET, algorithm="HS256")
    me = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200

    names = [s["name"] for s in client.get("/api/admin/staff", headers=admin).json()]
    assert names == ["Avery Admin", "Casey Coordinator"]


def test_staff_phone_defaults_to_none(client: TestClient, admin: dict[str, str]) -> None:
    body = {"id": str(uuid.uuid4()), "name": "Jo", "email": "jo@x.com"}
    response = client.post("/api/admin/staff", json=body, headers=admin)
    assert response.json() == {**body, "phone_e164": None}


def test_admin_edits_staff_name_and_phone(
    client: TestClient, admin: dict[str, str], db_session: Session
) -> None:
    staff = _staff(db_session, "coordinator", "Jo")
    response = client.patch(
        f"/api/admin/staff/{staff.id}",
        json={"phone_e164": "+15855550124", "name": "Jo Smith"},
        headers=admin,
    )
    assert response.status_code == 200
    assert response.json()["phone_e164"] == "+15855550124"
    assert response.json()["name"] == "Jo Smith"

    cleared = client.patch(f"/api/admin/staff/{staff.id}", json={"phone_e164": None}, headers=admin)
    assert cleared.json()["phone_e164"] is None
    assert cleared.json()["name"] == "Jo Smith"


def test_staff_id_already_on_the_list_is_409(
    client: TestClient, admin: dict[str, str], db_session: Session
) -> None:
    staff = _staff(db_session, "coordinator")
    body = {"id": str(staff.id), "name": "Again", "email": "a@x.com"}
    assert client.post("/api/admin/staff", json=body, headers=admin).status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {"id": "not-a-uuid", "name": "A", "email": "a@x.com"},
        {"id": "00000000-0000-0000-0000-000000000001", "name": " ", "email": "a@x.com"},
        {"id": "00000000-0000-0000-0000-000000000001", "name": "A", "email": "nope"},
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "name": "A",
            "email": "a@x.com",
            "phone_e164": "585-555-0123",
        },
    ],
)
def test_invalid_staff_is_422(client: TestClient, admin: dict[str, str], body: Any) -> None:
    assert client.post("/api/admin/staff", json=body, headers=admin).status_code == 422


def test_unknown_staff_is_404(client: TestClient, admin: dict[str, str]) -> None:
    response = client.patch(f"/api/admin/staff/{uuid.uuid4()}", json={"name": "X"}, headers=admin)
    assert response.status_code == 404


# --- Duty roster -------------------------------------------------------------------------


def test_admin_sets_tomorrows_on_duty_and_backup(
    client: TestClient, admin: dict[str, str], db_session: Session
) -> None:
    casey = _staff(db_session, "coordinator", "Casey")
    jo = _staff(db_session, "coordinator", "Jo")
    body = {"on_duty_staff_id": str(casey.id), "backup_staff_id": str(jo.id)}

    response = client.put("/api/admin/duty/2026-11-02", json=body, headers=admin)

    assert response.status_code == 200
    expected = {
        "date": "2026-11-02",
        "on_duty": {"id": str(casey.id), "name": "Casey"},
        "backup": {"id": str(jo.id), "name": "Jo"},
    }
    assert response.json() == expected
    assert client.get("/api/admin/duty", headers=admin).json() == [expected]


def test_the_on_duty_coordinator_set_by_admin_gets_the_alerts(
    client: TestClient, admin: dict[str, str], db_session: Session
) -> None:
    from app.services.alerts import on_duty_coordinator

    casey = _staff(db_session, "coordinator", "Casey")
    client.put(
        "/api/admin/duty/2026-11-02", json={"on_duty_staff_id": str(casey.id)}, headers=admin
    )
    on_duty, _ = on_duty_coordinator(db_session, NOW + timedelta(days=1))
    assert on_duty is not None
    assert on_duty.id == casey.id


def test_replacing_and_removing_a_duty_day(
    client: TestClient, admin: dict[str, str], db_session: Session
) -> None:
    casey = _staff(db_session, "coordinator", "Casey")
    jo = _staff(db_session, "coordinator", "Jo")
    path = "/api/admin/duty/2026-11-03"
    client.put(
        path, json={"on_duty_staff_id": str(casey.id), "backup_staff_id": str(jo.id)}, headers=admin
    )
    replaced = client.put(path, json={"on_duty_staff_id": str(jo.id)}, headers=admin)
    assert replaced.json()["on_duty"]["name"] == "Jo"
    assert replaced.json()["backup"] is None

    assert client.delete(path, headers=admin).status_code == 204
    assert client.get("/api/admin/duty", headers=admin).json() == []
    assert client.delete(path, headers=admin).status_code == 404


def test_duty_list_starts_today_in_new_york_and_is_by_date(
    client: TestClient, admin: dict[str, str], db_session: Session
) -> None:
    casey = _staff(db_session, "coordinator", "Casey")
    for day in ["2026-11-05", "2026-10-31", "2026-11-01", "2026-11-02"]:
        client.put(
            f"/api/admin/duty/{day}", json={"on_duty_staff_id": str(casey.id)}, headers=admin
        )

    listed = [d["date"] for d in client.get("/api/admin/duty", headers=admin).json()]
    assert listed == ["2026-11-01", "2026-11-02", "2026-11-05"]

    earlier = client.get("/api/admin/duty", params={"from": "2026-10-31"}, headers=admin).json()
    assert [d["date"] for d in earlier][0] == "2026-10-31"


def test_duty_needs_known_staff_and_a_real_date(
    client: TestClient, admin: dict[str, str], db_session: Session
) -> None:
    casey = _staff(db_session, "coordinator", "Casey")
    path = "/api/admin/duty/2026-11-02"
    unknown = client.put(path, json={"on_duty_staff_id": str(uuid.uuid4())}, headers=admin)
    assert unknown.status_code == 422
    unknown_backup = client.put(
        path,
        json={"on_duty_staff_id": str(casey.id), "backup_staff_id": str(uuid.uuid4())},
        headers=admin,
    )
    assert unknown_backup.status_code == 422
    assert (
        client.put(
            "/api/admin/duty/2026-13-40", json={"on_duty_staff_id": str(casey.id)}, headers=admin
        ).status_code
        == 422
    )
    assert client.get("/api/admin/duty", headers=admin).json() == []


# --- Removing a person from the staff list ----------------------------------------------


def _me_status(client: TestClient, staff: Staff) -> int:
    status: int = client.get("/api/me", headers=_headers(staff)).status_code
    return status


def test_admin_removes_a_person_who_then_loses_access_at_once(
    client: TestClient, db_session: Session
) -> None:
    avery = _staff(db_session, "admin", "Avery Admin")
    jo = _staff(db_session, "coordinator", "Jo")
    assert _me_status(client, jo) == 200

    response = client.delete(f"/api/admin/staff/{jo.id}", headers=_headers(avery))

    assert response.status_code == 204
    assert _me_status(client, jo) == 403
    names = [s["name"] for s in client.get("/api/admin/staff", headers=_headers(avery)).json()]
    assert names == ["Avery Admin"]
    db_session.refresh(jo)
    assert jo.removed_at == NOW  # the row stays: the audit history keeps the name


def test_nobody_can_remove_themselves(client: TestClient, db_session: Session) -> None:
    avery = _staff(db_session, "admin", "Avery Admin")
    response = client.delete(f"/api/admin/staff/{avery.id}", headers=_headers(avery))
    assert response.status_code == 409
    assert response.json()["detail"] == "You can't remove yourself."
    assert _me_status(client, avery) == 200


@pytest.mark.parametrize("as_backup", [False, True])
def test_a_person_on_todays_or_a_later_duty_day_cannot_be_removed(
    client: TestClient, db_session: Session, as_backup: bool
) -> None:
    avery = _staff(db_session, "admin", "Avery Admin")
    jo = _staff(db_session, "coordinator", "Jo")
    on_duty, backup = (avery, jo) if as_backup else (jo, avery)
    db_session.add(
        DutyRoster(day=date(2026, 11, 3), on_duty_staff_id=on_duty.id, backup_staff_id=backup.id)
    )
    db_session.flush()

    response = client.delete(f"/api/admin/staff/{jo.id}", headers=_headers(avery))

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Jo is on the duty roster for Tue, Nov 3. Change the duty roster first."
    )
    assert _me_status(client, jo) == 200


def test_a_past_duty_day_does_not_block_removal(client: TestClient, db_session: Session) -> None:
    avery = _staff(db_session, "admin", "Avery Admin")
    jo = _staff(db_session, "coordinator", "Jo")
    db_session.add(DutyRoster(day=date(2026, 10, 31), on_duty_staff_id=jo.id))
    db_session.flush()

    assert client.delete(f"/api/admin/staff/{jo.id}", headers=_headers(avery)).status_code == 204


def test_removing_an_unknown_or_already_removed_person_is_404(
    client: TestClient, db_session: Session
) -> None:
    avery = _staff(db_session, "admin", "Avery Admin")
    jo = _staff(db_session, "coordinator", "Jo")
    headers = _headers(avery)
    assert client.delete(f"/api/admin/staff/{uuid.uuid4()}", headers=headers).status_code == 404
    assert client.delete(f"/api/admin/staff/{jo.id}", headers=headers).status_code == 204
    assert client.delete(f"/api/admin/staff/{jo.id}", headers=headers).status_code == 404


def test_a_removed_person_is_not_offered_for_duty(client: TestClient, db_session: Session) -> None:
    avery = _staff(db_session, "admin", "Avery Admin")
    jo = _staff(db_session, "coordinator", "Jo")
    headers = _headers(avery)
    client.delete(f"/api/admin/staff/{jo.id}", headers=headers)

    response = client.put(
        "/api/admin/duty/2026-11-04", json={"on_duty_staff_id": str(jo.id)}, headers=headers
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "No such staff member."


def test_adding_a_removed_person_again_restores_them(
    client: TestClient, db_session: Session
) -> None:
    avery = _staff(db_session, "admin", "Avery Admin")
    jo = _staff(db_session, "coordinator", "Jo")
    headers = _headers(avery)
    client.delete(f"/api/admin/staff/{jo.id}", headers=headers)

    body = {"id": str(jo.id), "name": "Jo Smith", "email": "jo@x.com", "phone_e164": None}
    response = client.post("/api/admin/staff", json=body, headers=headers)

    assert response.status_code == 201
    assert response.json() == body
    assert _me_status(client, jo) == 200
