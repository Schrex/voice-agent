"""POST /tools/resolve_needed_by: the read-back of a spoken needed-by, before submit (ticket #14).

Parsing itself is covered by `tests/unit/test_timeparse.py`; these check the tool contract:
the backend (not the agent) works out the day and time against the call's clock, the result
matches what `submit_requests` stores, and nothing is written.
"""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import get_clock
from app.db.models import Request, RequestEvent
from app.main import app
from app.services.roster import load_roster_file, seed_roster

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "elevenlabs"
SAMPLE_ROSTER = ROOT / "backend" / "seed" / "sample_roster.json"

HOOK_SECRET = "test-hook-secret"
TOOL_SECRET = "test-tool-secret"
# Saturday, October 31, 2026, 11:50 PM EDT: a late-night call the night DST ends.
NOW = datetime(2026, 11, 1, 3, 50, tzinfo=UTC)
ROSTERED = json.loads((FIXTURES / "call_start_rostered.json").read_text())
CONVERSATION = ROSTERED["conversation_id"]


@pytest.fixture
def tools(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """Seeded roster, secrets set, frozen clock, and Dale's call started."""
    monkeypatch.setenv("HOOK_SECRET", HOOK_SECRET)
    monkeypatch.setenv("TOOL_SECRET", TOOL_SECRET)
    monkeypatch.setenv("OFFICE_MAIN_NUMBER", "585-555-0100")
    seed_roster(db_session, load_roster_file(SAMPLE_ROSTER))
    app.dependency_overrides[get_clock] = lambda: lambda: NOW
    started = client.post(
        "/hooks/call-start", json=ROSTERED, headers={"X-Hook-Secret": HOOK_SECRET}
    )
    assert started.status_code == 200
    yield client


def _resolve(
    client: TestClient,
    body: Any,
    *,
    secret: str | None = TOOL_SECRET,
    conversation_id: str | None = CONVERSATION,
) -> Any:
    headers = {}
    if secret is not None:
        headers["X-Tool-Secret"] = secret
    if conversation_id is not None:
        headers["X-Conversation-Id"] = conversation_id
    return client.post("/tools/resolve_needed_by", json=body, headers=headers)


def test_spoken_time_is_read_back_as_weekday_date_and_time_with_its_urgency(
    tools: TestClient,
) -> None:
    response = _resolve(tools, {"needed_by_spoken": "tomorrow at seven"})

    assert response.status_code == 200
    assert response.json() == {
        "needed_by_resolved": "Sunday, November 1 at 7:00 AM",
        "urgency": "Planned",
    }


def test_words_not_understood_resolve_to_nothing(tools: TestClient) -> None:
    response = _resolve(tools, {"needed_by_spoken": "whenever you can"})

    assert response.json() == {"needed_by_resolved": None, "urgency": None}


def test_the_read_back_is_what_submit_stores(tools: TestClient, db_session: Session) -> None:
    said = "first thing"
    read_back = _resolve(tools, {"needed_by_spoken": said}).json()

    submitted = tools.post(
        "/tools/submit_requests",
        json={
            "items": [
                {
                    "job_spoken": "the Smith pit",
                    "category": "Material",
                    "need": "stone",
                    "needed_by_spoken": said,
                }
            ]
        },
        headers={"X-Tool-Secret": TOOL_SECRET, "X-Conversation-Id": CONVERSATION},
    ).json()

    assert submitted[0]["needed_by_resolved"] == read_back["needed_by_resolved"]
    assert submitted[0]["urgency"] == read_back["urgency"]


def test_nothing_is_written(tools: TestClient, db_session: Session) -> None:
    _resolve(tools, {"needed_by_spoken": "tomorrow at seven"})

    for model in (Request, RequestEvent):
        assert db_session.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize(
    "body", [{}, {"needed_by_spoken": 7}, ["tomorrow"]], ids=["missing", "not-text", "not-object"]
)
def test_malformed_body_returns_a_speakable_error(tools: TestClient, body: Any) -> None:
    response = _resolve(tools, body)

    assert response.status_code == 200
    assert response.json() == {"error": "The needed-by time could not be worked out."}


def test_wrong_secret_is_rejected(tools: TestClient) -> None:
    assert _resolve(tools, {"needed_by_spoken": "today"}, secret="wrong").status_code == 401


def test_unknown_conversation_is_rejected(tools: TestClient) -> None:
    response = _resolve(tools, {"needed_by_spoken": "today"}, conversation_id="conv_unknown")

    assert response.status_code == 403
