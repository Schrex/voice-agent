"""Dashboard API auth (#8): Supabase access token in, staff list checked by the backend."""

import time
import uuid
from collections.abc import Iterator
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Staff
from app.services import staff as staff_service

SECRET = "test-jwt-secret-at-least-32-bytes-long"


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("VITE_SUPABASE_URL", raising=False)
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


def add_staff(session: Session) -> Staff:
    staff = Staff(id=uuid.uuid4(), name="Pat Coordinator", email="pat@example.com")
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


def test_staff_is_200(client: TestClient, db_session: Session) -> None:
    staff = add_staff(db_session)

    response = client.get("/api/me", headers=bearer(token(str(staff.id))))

    assert response.status_code == 200
    assert response.json() == {
        "id": str(staff.id),
        "name": "Pat Coordinator",
        "email": "pat@example.com",
    }


def test_unknown_api_path_is_404_not_the_dashboard(client: TestClient) -> None:
    assert client.get("/api/nope").status_code == 404


# --- New Supabase signing keys (ES256 via the project's JWKS) -------------------------------

PROJECT_URL = "https://abcd1234.supabase.co"
JWKS_URL = f"{PROJECT_URL}/auth/v1/.well-known/jwks.json"


def _ec_key() -> Any:
    from cryptography.hazmat.primitives.asymmetric import ec

    return ec.generate_private_key(ec.SECP256R1())


PROJECT_KEY = _ec_key()
OTHER_KEY = _ec_key()


def es256_token(sub: str, *, key: Any = PROJECT_KEY, kid: str = "key-1", **overrides: Any) -> str:
    """An access token shaped like a new Supabase project's (ES256, `kid` in the header)."""
    claims: dict[str, Any] = {
        "sub": sub,
        "aud": "authenticated",
        "role": "authenticated",
        "exp": int(time.time()) + 3600,
    }
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm="ES256", headers={"kid": kid})


@pytest.fixture
def supabase_jwks(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """The project's JWKS endpoint, faked at the HTTP fetch; yields the URLs fetched."""
    jwk = jwt.algorithms.ECAlgorithm.to_jwk(PROJECT_KEY.public_key(), as_dict=True)
    jwks = {"keys": [{**jwk, "kid": "key-1", "alg": "ES256", "use": "sig"}]}
    fetched: list[str] = []

    def fetch_data(client: jwt.PyJWKClient) -> Any:
        fetched.append(client.uri)
        return jwks

    staff_service._jwks_client.cache_clear()
    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", fetch_data)
    monkeypatch.setenv("SUPABASE_URL", PROJECT_URL)
    yield fetched
    staff_service._jwks_client.cache_clear()


def test_new_key_token_of_staff_is_200(
    client: TestClient, db_session: Session, supabase_jwks: list[str]
) -> None:
    staff = add_staff(db_session)

    first = client.get("/api/me", headers=bearer(es256_token(str(staff.id))))
    second = client.get("/api/me", headers=bearer(es256_token(str(staff.id))))

    assert (first.status_code, second.status_code) == (200, 200)
    assert first.json()["id"] == str(staff.id)
    assert supabase_jwks == [JWKS_URL]  # fetched once, then cached


@pytest.mark.parametrize(
    "make",
    [
        lambda sub: es256_token(sub, key=OTHER_KEY),
        lambda sub: es256_token(sub, kid="unknown-key"),
        lambda sub: es256_token(sub, exp=int(time.time()) - 10),
        lambda sub: es256_token(sub, aud="something-else"),
    ],
    ids=["not-the-projects-key", "unknown-kid", "expired", "wrong-audience"],
)
def test_bad_new_key_token_is_401(
    client: TestClient, db_session: Session, supabase_jwks: list[str], make: Any
) -> None:
    staff = add_staff(db_session)
    assert client.get("/api/me", headers=bearer(make(str(staff.id)))).status_code == 401


def test_new_key_token_of_a_non_staff_user_is_403(
    client: TestClient, supabase_jwks: list[str]
) -> None:
    response = client.get("/api/me", headers=bearer(es256_token(str(uuid.uuid4()))))
    assert response.status_code == 403


def test_new_key_token_without_a_project_url_is_401(
    client: TestClient, db_session: Session
) -> None:
    staff = add_staff(db_session)
    assert client.get("/api/me", headers=bearer(es256_token(str(staff.id)))).status_code == 401


def test_legacy_token_without_the_jwt_secret_is_401(
    client: TestClient,
    db_session: Session,
    supabase_jwks: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SUPABASE_JWT_SECRET")
    staff = add_staff(db_session)
    assert client.get("/api/me", headers=bearer(token(str(staff.id)))).status_code == 401


def test_both_kinds_of_token_work_side_by_side(
    client: TestClient, db_session: Session, supabase_jwks: list[str]
) -> None:
    """A project moving to new keys: tokens signed before the switch stay valid until expiry."""
    staff = add_staff(db_session)
    legacy = client.get("/api/me", headers=bearer(token(str(staff.id))))
    new = client.get("/api/me", headers=bearer(es256_token(str(staff.id))))
    assert (legacy.status_code, new.status_code) == (200, 200)


def test_the_project_url_comes_from_the_dashboard_build_var_too(
    client: TestClient,
    db_session: Session,
    supabase_jwks: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Render already sets VITE_SUPABASE_URL for the build; the backend uses it if needed."""
    monkeypatch.delenv("SUPABASE_URL")
    monkeypatch.setenv("VITE_SUPABASE_URL", PROJECT_URL + "/")
    staff = add_staff(db_session)
    assert client.get("/api/me", headers=bearer(es256_token(str(staff.id)))).status_code == 200
    assert supabase_jwks == [JWKS_URL]
