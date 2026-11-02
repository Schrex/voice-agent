from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.main import app

# Nothing listens on port 1, so connecting fails fast like a down database.
UNREACHABLE_DB = "postgresql+psycopg://postgres:postgres@localhost:1/none?connect_timeout=2"


def test_healthz_reports_db_reachable(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}


def test_healthz_is_not_200_when_db_is_down() -> None:
    engine = create_engine(UNREACHABLE_DB)

    def down_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = down_session
    try:
        response = TestClient(app).get("/healthz")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 503
    assert response.json() == {"status": "error", "db": "unreachable"}
