"""Serves the built dashboard (Vite output) at `/`; client-side routes get `index.html`.

Registered after every other router. Paths under the backend's own prefixes never fall back to
the dashboard, so an unknown `/api/...` is a 404, not an HTML page.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

_BACKEND_PREFIXES = ("api", "hooks", "tools", "assets", "healthz")


def mount(app: FastAPI, dist: Path) -> None:
    """Serve `dist` if it holds a build; without one (backend-only dev, tests) do nothing."""
    index = dist / "index.html"
    if not index.is_file():
        return
    root = dist.resolve()
    if (root / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def dashboard(path: str) -> FileResponse:
        if path.split("/", 1)[0] in _BACKEND_PREFIXES:
            raise HTTPException(status_code=404)
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        # index.html names hashed assets, so it must never be served stale.
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
