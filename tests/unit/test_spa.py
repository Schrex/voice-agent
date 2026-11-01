"""The backend serves the built dashboard at `/` (architecture §1) without shadowing the API."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.http import spa

INDEX = "<!doctype html><title>Dashboard</title>"


def _client(dist: Path) -> TestClient:
    app = FastAPI()

    @app.get("/api/thing")
    def thing() -> dict[str, str]:
        return {"ok": "yes"}

    spa.mount(app, dist)
    return TestClient(app)


def _dist(tmp_path: Path) -> Path:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(INDEX)
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    return tmp_path


def test_root_and_client_routes_get_index_html(tmp_path: Path) -> None:
    client = _client(_dist(tmp_path))
    for path in ["/", "/login", "/queue"]:
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.text == INDEX


def test_built_assets_are_served(tmp_path: Path) -> None:
    response = _client(_dist(tmp_path)).get("/assets/app.js")
    assert response.status_code == 200
    assert response.text == "console.log(1)"


def test_api_routes_still_win_and_unknown_api_paths_404(tmp_path: Path) -> None:
    client = _client(_dist(tmp_path))
    assert client.get("/api/thing").json() == {"ok": "yes"}
    for path in ["/api/nope", "/hooks/nope", "/tools/nope", "/assets/missing.js"]:
        assert client.get(path).status_code == 404, path


def test_missing_build_serves_nothing(tmp_path: Path) -> None:
    client = _client(tmp_path / "no-build-here")
    assert client.get("/").status_code == 404
    assert client.get("/api/thing").status_code == 200
