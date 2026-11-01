"""Dashboard API auth (#8): Supabase access token in, staff role checked by the backend."""

import time
import uuid
from collections.abc import Iterator
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Staff

SECRET = "test-jwt-secret-at-least-32-bytes-long"


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    yield


def token(sub: str, *, secret: str = SECRET, **overrides: Any) -> str:
    """An access token shaped like Supabase's (HS256, aud=authenticated)."""
    claims: dict[str, Any] = {
        "sub": sub,
        "aud": "authenticated",
        "role": "authenticated",
        "email": "someone@example.com",
        "exp": int(time.time()) + 3600,
    }
    claims.update(overrides)
    return jwt.encode(claims, secret, algorithm="HS256")


def bearer(tok: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


def add_staff(session: Session, role: str = "coordinator") -> Staff:
    staff = Staff(id=uuid.uuid4(), name="Pat Coordinator", email="pat@example.com", role=role)
    session.add(staff)
    session.flush()
    return staff


def test_no_token_is_401(client: TestClient) -> None:
    assert client.get("/api/me").status_code == 401


@pytest.mark.parametrize(
    "tok",
    [
        "not-a-jwt",
        token(str(uuid.uuid4()), secret="some-other-secret-at-least-32-bytes"),
        token(str(uuid.uuid4()), exp=int(time.time()) - 10),
        token(str(uuid.uuid4()), aud="something-else"),
        token("not-a-uuid"),
    ],
    ids=["garbage", "wrong-signature", "expired", "wrong-audience", "sub-not-uuid"],
)
def test_invalid_token_is_401(client: TestClient, tok: str) -> None:
    assert client.get("/api/me", headers=bearer(tok)).status_code == 401


def test_token_of_user_not_in_staff_is_403(client: TestClient) -> None:
    response = client.get("/api/me", headers=bearer(token(str(uuid.uuid4()))))
    assert response.status_code == 403


@pytest.mark.parametrize("role", ["coordinator", "admin"])
def test_staff_is_200(client: TestClient, db_session: Session, role: str) -> None:
    staff = add_staff(db_session, role)

    response = client.get("/api/me", headers=bearer(token(str(staff.id))))

    assert response.status_code == 200
    assert response.json() == {
        "id": str(staff.id),
        "name": "Pat Coordinator",
        "email": "pat@example.com",
        "role": role,
    }


def test_unknown_api_path_is_404_not_the_dashboard(client: TestClient) -> None:
    assert client.get("/api/nope").status_code == 404
