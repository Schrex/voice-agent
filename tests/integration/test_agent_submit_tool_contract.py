"""The agent's `submit_requests` tool fits POST /tools/submit_requests (tickets #6, #7).

ElevenLabs builds the tool call from `backend/agent/tools/submit_requests.json`: URL, headers
and a body shaped by its schema, with the job id taken from the call-start `jobs` variable.
These tests drive the backend exactly that way, so the config and the endpoint cannot drift.
"""

import json
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.push import desired_tools
from app.clock import get_clock
from app.db.models import Request
from app.http.tools import Category, SubmitItem
from app.main import app
from app.services.roster import load_roster_file, seed_roster

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "elevenlabs"
SAMPLE_ROSTER = ROOT / "backend" / "seed" / "sample_roster.json"
HOOK_SECRET = "test-hook-secret"
TOOL_SECRET = "test-tool-secret"
BACKEND = "https://b.example.test"
ENV = {"agent_name": "x", "backend_url": BACKEND, "hook_secret_id": "s", "tool_secret_id": "t"}
ROSTERED = json.loads((FIXTURES / "call_start_rostered.json").read_text())


def _tool() -> dict[str, Any]:
    (tool,) = [t for t in desired_tools(ENV) if t["tool_config"]["name"] == "submit_requests"]
    config: dict[str, Any] = tool["tool_config"]
    return config


def _item_schema() -> dict[str, Any]:
    items: dict[str, Any] = _tool()["api_schema"]["request_body_schema"]["properties"]["items"]
    assert items["type"] == "array"
    schema: dict[str, Any] = items["items"]
    return schema


def test_tool_url_is_the_backend_submit_route() -> None:
    api = _tool()["api_schema"]
    path = api["url"].removeprefix(BACKEND)

    assert api["method"].lower() in app.openapi()["paths"][path]


def test_tool_item_fields_match_what_the_backend_accepts() -> None:
    schema = _item_schema()
    fields = SubmitItem.model_fields

    assert set(schema["properties"]) == set(fields)
    assert set(schema["required"]) == {name for name, f in fields.items() if f.is_required()}
    assert schema["properties"]["category"]["enum"] == list(get_args(Category))


@pytest.fixture
def started_call(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, dict[str, Any]]]:
    monkeypatch.setenv("HOOK_SECRET", HOOK_SECRET)
    monkeypatch.setenv("TOOL_SECRET", TOOL_SECRET)
    monkeypatch.setenv("OFFICE_MAIN_NUMBER", "585-555-0100")
    seed_roster(db_session, load_roster_file(SAMPLE_ROSTER))
    app.dependency_overrides[get_clock] = lambda: lambda: datetime(2026, 11, 1, 20, 4, tzinfo=UTC)
    response = client.post(
        "/hooks/call-start", json=ROSTERED, headers={"X-Hook-Secret": HOOK_SECRET}
    )
    assert response.status_code == 200
    yield client, response.json()["dynamic_variables"]


def test_tool_call_built_from_the_config_records_the_job_the_agent_was_given(
    started_call: tuple[TestClient, dict[str, Any]], db_session: Session
) -> None:
    client, variables = started_call
    # The agent picks the Job from the `jobs` variable and passes its id.
    jobs = dict(re.findall(r"\s*([^;]+?) \(job_id (\d+)\)", variables["jobs"]))
    assert set(jobs) == {"Penfield Sewer Replacement", "Route 104 Widening"}
    # Headers as ElevenLabs resolves them: the secret's value and system__conversation_id.
    resolved = {"secret_id": TOOL_SECRET, "variable_name": ROSTERED["conversation_id"]}
    headers = {
        name: resolved[next(iter(locator))]
        for name, locator in _tool()["api_schema"]["request_headers"].items()
    }
    body = {
        "items": [
            {
                "job_id": int(jobs["Route 104 Widening"]),
                "category": "Trucking",
                "need": "tri-axle dump trucks",
                "quantity": 2,
                "unit": "trucks",
                "needed_by_spoken": "tomorrow at 7 AM",
            }
        ]
    }

    response = client.post(
        _tool()["api_schema"]["url"].removeprefix(BACKEND), json=body, headers=headers
    )

    assert response.status_code == 200
    [result] = response.json()
    assert re.fullmatch(r"R-\d{4,}", result["ref"])
    request = db_session.scalars(select(Request)).one()
    assert request.ref_display == result["ref"]
    assert request.status == "Recorded"
    assert request.job_id == int(jobs["Route 104 Widening"])
    assert request.quantity == 2
