"""POST /tools/find_jobs: a spoken Job → up to three active Jobs, empty = Unmatched (ticket #13).

Matching itself is covered by `tests/unit/test_jobs_match.py`; these check the tool contract
against the seeded Job list (names, aliases, active flag) and its auth.
"""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import get_clock
from app.db.models import Job
from app.main import app
from app.services.roster import load_roster_file, seed_roster

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "elevenlabs"
SAMPLE_ROSTER = ROOT / "backend" / "seed" / "sample_roster.json"

HOOK_SECRET = "test-hook-secret"
TOOL_SECRET = "test-tool-secret"
NOW = datetime(2026, 11, 1, 20, 4, tzinfo=UTC)
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


def _find(
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
    return client.post("/tools/find_jobs", json=body, headers=headers)


def _job_id(session: Session, name: str) -> int:
    return session.scalars(select(Job.id).where(Job.name == name)).one()


def test_alias_returns_the_canonical_job_name_and_id(
    tools: TestClient, db_session: Session
) -> None:
    response = _find(tools, {"query": "the 104 job"})

    assert response.status_code == 200
    [match] = response.json()
    assert match["job_id"] == _job_id(db_session, "Route 104 Widening")
    assert match["name"] == "Route 104 Widening"
    assert isinstance(match["score"], int)


@pytest.mark.parametrize("query", ["the Smith pit", "R-104", ""])
def test_no_confident_match_returns_an_empty_list(tools: TestClient, query: str) -> None:
    response = _find(tools, {"query": query})

    assert response.status_code == 200
    assert response.json() == []


def test_inactive_jobs_are_never_matched(tools: TestClient) -> None:
    # "Lakeside" is the alias of the inactive Lakeside Plaza Site Work.
    assert _find(tools, {"query": "Lakeside"}).json() == []


@pytest.mark.parametrize(
    "body", [{}, {"query": 104}, ["Route 104"]], ids=["no-query", "not-text", "not-an-object"]
)
def test_malformed_body_returns_a_speakable_error(tools: TestClient, body: Any) -> None:
    response = _find(tools, body)

    assert response.status_code == 200
    assert response.json() == {"error": "The Job list could not be searched."}


@pytest.mark.parametrize("secret", [None, "wrong"])
def test_missing_or_wrong_secret_is_rejected(tools: TestClient, secret: str | None) -> None:
    assert _find(tools, {"query": "Route 104"}, secret=secret).status_code == 401


@pytest.mark.parametrize("conversation_id", [None, "conv_never_started"])
def test_unknown_conversation_is_rejected(tools: TestClient, conversation_id: str | None) -> None:
    response = _find(tools, {"query": "Route 104"}, conversation_id=conversation_id)
    assert response.status_code == 403
