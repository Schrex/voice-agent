"""The agent's tools fit the backend's `/tools/*` routes (tickets #6, #7, #13).

ElevenLabs builds each tool call from `backend/agent/tools/<name>.json`: URL, headers and a body
shaped by its schema. The Job id comes from what `find_jobs` returned, never from the call-start
variables. These tests drive the backend exactly that way, so the config and the endpoints
cannot drift.
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
from app.db.models import Job, Request
from app.http.tools import Category, FindJobsBody, ResolveNeededByBody, SubmitItem
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


def _tool(name: str) -> dict[str, Any]:
    (tool,) = [t for t in desired_tools(ENV) if t["tool_config"]["name"] == name]
    config: dict[str, Any] = tool["tool_config"]
    return config


def _item_schema() -> dict[str, Any]:
    body = _tool("submit_requests")["api_schema"]["request_body_schema"]
    items: dict[str, Any] = body["properties"]["items"]
    assert items["type"] == "array"
    schema: dict[str, Any] = items["items"]
    return schema


@pytest.mark.parametrize("name", ["find_jobs", "resolve_needed_by", "submit_requests"])
def test_tool_url_is_the_backend_route(name: str) -> None:
    api = _tool(name)["api_schema"]
    path = api["url"].removeprefix(BACKEND)

    assert path == f"/tools/{name}"
    assert api["method"].lower() in app.openapi()["paths"][path]


def test_find_jobs_fields_match_what_the_backend_accepts() -> None:
    schema = _tool("find_jobs")["api_schema"]["request_body_schema"]
    fields = FindJobsBody.model_fields

    assert set(schema["properties"]) == set(fields)
    assert set(schema["required"]) == {name for name, f in fields.items() if f.is_required()}


def test_resolve_needed_by_fields_match_what_the_backend_accepts() -> None:
    schema = _tool("resolve_needed_by")["api_schema"]["request_body_schema"]
    fields = ResolveNeededByBody.model_fields

    assert set(schema["properties"]) == set(fields)
    assert set(schema["required"]) == {name for name, f in fields.items() if f.is_required()}


def test_submit_item_fields_match_what_the_backend_accepts() -> None:
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


def _call_tool(client: TestClient, name: str, body: dict[str, Any]) -> Any:
    """POST as ElevenLabs would: resolved header locators, URL from the config."""
    api = _tool(name)["api_schema"]
    resolved = {"secret_id": TOOL_SECRET, "variable_name": ROSTERED["conversation_id"]}
    headers = {
        header: resolved[next(iter(locator))] for header, locator in api["request_headers"].items()
    }
    response = client.post(api["url"].removeprefix(BACKEND), json=body, headers=headers)
    assert response.status_code == 200
    return response.json()


def _item(**job: Any) -> dict[str, Any]:
    return {
        **job,
        "category": "Trucking",
        "need": "tri-axle dump trucks",
        "quantity": 2,
        "unit": "trucks",
        "needed_by_spoken": "tomorrow at 7 AM",
    }


def test_call_start_jobs_are_names_only_so_the_agent_cannot_pick_an_id(
    started_call: tuple[TestClient, dict[str, Any]],
) -> None:
    _, variables = started_call

    assert variables["jobs"] == "Penfield Sewer Replacement; Route 104 Widening"


def test_alias_found_by_find_jobs_is_submitted_on_its_canonical_job(
    started_call: tuple[TestClient, dict[str, Any]], db_session: Session
) -> None:
    client, _ = started_call

    [match] = _call_tool(client, "find_jobs", {"query": "the 104 job"})
    assert match["name"] == "Route 104 Widening"
    [result] = _call_tool(
        client,
        "submit_requests",
        {"items": [_item(job_id=match["job_id"], job_spoken="the 104 job")]},
    )

    assert re.fullmatch(r"R-\d{4,}", result["ref"])
    request = db_session.scalars(select(Request)).one()
    assert request.ref_display == result["ref"]
    assert request.status == "Recorded"
    route_104 = db_session.scalars(select(Job.id).where(Job.name == "Route 104 Widening")).one()
    assert (request.job_id, request.job_spoken) == (route_104, "the 104 job")
    assert request.quantity == 2


def test_unknown_job_is_submitted_unmatched_with_what_the_foreman_said(
    started_call: tuple[TestClient, dict[str, Any]], db_session: Session
) -> None:
    client, _ = started_call

    assert _call_tool(client, "find_jobs", {"query": "the Smith pit"}) == []
    [result] = _call_tool(client, "submit_requests", {"items": [_item(job_spoken="the Smith pit")]})

    request = db_session.scalars(select(Request)).one()
    assert request.ref_display == result["ref"]
    assert (request.job_id, request.job_spoken, request.status) == (
        None,
        "the Smith pit",
        "Recorded",
    )
