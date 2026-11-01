"""The agent in backend/agent/ accepts what POST /hooks/call-start returns (tickets #4, #5).

ElevenLabs only applies a call-start response when the agent defines every dynamic variable
it sends and allows every config field it overrides; otherwise the greeting (AC1.1) or the
rejection line (AC8.1) would not be spoken. These tests hold the two sides together.
"""

import json
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from agent.push import desired_agent
from app.clock import get_clock
from app.main import app
from app.services.roster import load_roster_file, seed_roster

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "elevenlabs"
SAMPLE_ROSTER = ROOT / "backend" / "seed" / "sample_roster.json"
SECRET = "test-hook-secret"
ENV = {
    "agent_name": "x",
    "backend_url": "https://b.example.test",
    "hook_secret_id": "s",
    "tool_secret_id": "t",
}
TOOL_IDS = {
    "find_jobs": "tool_find",
    "resolve_needed_by": "tool_resolve",
    "submit_requests": "tool_submit",
    "find_open_requests": "tool_status",
    "create_callback_request": "tool_callback",
    "add_note": "tool_note",
    "amend_request": "tool_amend",
}


@pytest.fixture
def hook(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch.setenv("HOOK_SECRET", SECRET)
    monkeypatch.setenv("OFFICE_MAIN_NUMBER", "585-555-0100")
    seed_roster(db_session, load_roster_file(SAMPLE_ROSTER))
    app.dependency_overrides[get_clock] = lambda: lambda: datetime(2026, 11, 1, 20, 4, tzinfo=UTC)
    yield client


def _call_start(client: TestClient, fixture: str) -> dict[str, Any]:
    payload = json.loads((FIXTURES / fixture).read_text())
    response = client.post("/hooks/call-start", json=payload, headers={"X-Hook-Secret": SECRET})
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def _allowed_overrides(agent: dict[str, Any]) -> dict[str, Any]:
    overrides: dict[str, Any] = agent["platform_settings"]["overrides"]
    assert overrides["enable_conversation_initiation_client_data_from_webhook"] is True
    allowed: dict[str, Any] = overrides["conversation_config_override"]
    return allowed


def _assert_allowed(override: dict[str, Any], allowed: dict[str, Any], path: str = "") -> None:
    for key, value in override.items():
        where = f"{path}.{key}" if path else key
        assert key in allowed, f"agent does not allow overriding {where}"
        if isinstance(value, dict):
            _assert_allowed(value, allowed[key], where)
        else:
            assert allowed[key] is True, f"agent does not allow overriding {where}"


@pytest.mark.parametrize("fixture", ["call_start_rostered.json", "call_start_unrostered.json"])
def test_agent_defines_exactly_the_dynamic_variables_call_start_sends(
    hook: TestClient, fixture: str
) -> None:
    sent = _call_start(hook, fixture)["dynamic_variables"]
    agent = desired_agent(ENV, TOOL_IDS)
    placeholders = agent["conversation_config"]["agent"]["dynamic_variables"][
        "dynamic_variable_placeholders"
    ]

    assert set(placeholders) == set(sent)
    for name, value in sent.items():
        assert type(placeholders[name]) is type(value), name


def test_agent_allows_the_overrides_the_rejection_response_uses(hook: TestClient) -> None:
    response = _call_start(hook, "call_start_unrostered.json")

    _assert_allowed(
        response["conversation_config_override"], _allowed_overrides(desired_agent(ENV, TOOL_IDS))
    )


def test_prompt_and_first_message_use_only_defined_variables() -> None:
    agent = desired_agent(ENV, TOOL_IDS)["conversation_config"]["agent"]
    defined = set(agent["dynamic_variables"]["dynamic_variable_placeholders"])
    text = agent["first_message"] + agent["prompt"]["prompt"]

    used = set(re.findall(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}", text))
    assert used - defined == set()
    assert {"rejected", "foreman_first_name"} <= used
