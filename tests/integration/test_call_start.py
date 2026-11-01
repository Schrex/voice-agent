"""POST /hooks/call-start: roster check at call start (ticket #4, spec J8, architecture §3.1).

Payload fixtures in tests/fixtures/elevenlabs/ are synthetic (built from the documented
shape) until real ElevenLabs payloads are recorded.
"""

import json
import math
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import get_clock
from app.db.models import Call
from app.main import app
from app.services.roster import load_roster_file, seed_roster

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "elevenlabs"
SAMPLE_ROSTER = ROOT / "backend" / "seed" / "sample_roster.json"

SECRET = "test-hook-secret"
MAIN_NUMBER = "585-555-0100"
# Sunday 1 Nov 2026, 15:04 in New York (EST; DST ended that morning).
NOW = datetime(2026, 11, 1, 20, 4, tzinfo=UTC)


def _fixture(name: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((FIXTURES / name).read_text())
    return payload


@pytest.fixture
def hook(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """Seeded roster, configured secret and main office number, frozen clock."""
    monkeypatch.setenv("HOOK_SECRET", SECRET)
    monkeypatch.setenv("OFFICE_MAIN_NUMBER", MAIN_NUMBER)
    seed_roster(db_session, load_roster_file(SAMPLE_ROSTER))
    app.dependency_overrides[get_clock] = lambda: lambda: NOW
    yield client


def _post(client: TestClient, payload: dict[str, Any], secret: str | None = SECRET) -> Any:
    headers = {} if secret is None else {"X-Hook-Secret": secret}
    return client.post("/hooks/call-start", json=payload, headers=headers)


def _calls(session: Session) -> list[Call]:
    return list(session.scalars(select(Call)))


def test_rostered_caller_gets_first_name_active_jobs_and_local_time(
    hook: TestClient, db_session: Session
) -> None:
    response = _post(hook, _fixture("call_start_rostered.json"))

    assert response.status_code == 200
    assert response.json() == {
        "type": "conversation_initiation_client_data",
        "dynamic_variables": {
            "rejected": False,
            "foreman_first_name": "Dale",
            # Lakeside Plaza Site Work is inactive in the seed, so it is not offered.
            "jobs": "Penfield Sewer Replacement; Route 104 Widening",
            "now_local": "Sunday, November 1, 2026, 3:04 PM",
        },
    }


def test_rostered_call_is_recorded_bound_to_the_conversation(
    hook: TestClient, db_session: Session
) -> None:
    _post(hook, _fixture("call_start_rostered.json"))

    [call] = _calls(db_session)
    assert call.conversation_id == "conv_synthetic_rostered_0001"
    assert call.call_sid == "CA00000000000000000000000000000001"
    assert call.caller_e164 == "+15855550102"
    assert call.foreman is not None
    assert call.foreman.first_name == "Dale"
    assert call.started_at == NOW
    assert call.outcome is None


def test_unrostered_caller_gets_the_rejection_line_and_rejected_flag(hook: TestClient) -> None:
    response = _post(hook, _fixture("call_start_unrostered.json"))

    assert response.status_code == 200
    assert response.json() == {
        "type": "conversation_initiation_client_data",
        "dynamic_variables": {
            "rejected": True,
            "foreman_first_name": "",
            "jobs": "",
            "now_local": "",
        },
        "conversation_config_override": {
            "agent": {
                # Spec J8, verbatim, with the configured main number.
                "first_message": "This line is for registered crew leaders. "
                "Please call the office at 585-555-0100."
            }
        },
    }


def test_unrostered_attempt_is_logged(hook: TestClient, db_session: Session) -> None:
    _post(hook, _fixture("call_start_unrostered.json"))

    [call] = _calls(db_session)
    assert call.conversation_id == "conv_synthetic_unrostered_0001"
    assert call.caller_e164 == "+15855550999"
    assert call.foreman_id is None
    assert call.outcome == "rejected"
    assert call.started_at == NOW


def test_unrostered_response_discloses_no_foreman_job_or_request_data(
    hook: TestClient, db_session: Session
) -> None:
    body = _post(hook, _fixture("call_start_unrostered.json")).text

    roster = load_roster_file(SAMPLE_ROSTER)
    for foreman in roster.foremen:
        assert foreman.first_name not in body
        assert foreman.last_name not in body
        for phone in foreman.phones:
            assert phone not in body
    for job in roster.jobs:
        assert job.name not in body
        for alias in job.aliases:
            assert alias not in body
    # No request data: no open_requests variable and no request ref.
    assert "open_requests" not in body
    assert "R-" not in body


@pytest.mark.parametrize("secret", [None, "wrong-secret", ""])
def test_missing_or_wrong_secret_is_401_and_writes_nothing(
    hook: TestClient, db_session: Session, secret: str | None
) -> None:
    for fixture in ("call_start_rostered.json", "call_start_unrostered.json"):
        response = _post(hook, _fixture(fixture), secret=secret)

        assert response.status_code == 401
        assert "Dale" not in response.text
    assert _calls(db_session) == []


def test_unset_server_secret_rejects_every_request(
    hook: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HOOK_SECRET")

    response = _post(hook, _fixture("call_start_rostered.json"), secret="")

    assert response.status_code == 401
    assert _calls(db_session) == []


@pytest.mark.parametrize("fixture", ["call_start_rostered.json", "call_start_unrostered.json"])
def test_same_conversation_twice_records_one_call(
    hook: TestClient, db_session: Session, fixture: str
) -> None:
    first = _post(hook, _fixture(fixture))
    second = _post(hook, _fixture(fixture))

    assert second.status_code == 200
    assert second.json() == first.json()
    assert db_session.scalar(select(func.count()).select_from(Call)) == 1


def test_conversation_stays_bound_to_the_first_caller(
    hook: TestClient, db_session: Session
) -> None:
    """A repeat delivery for a known conversation cannot rebind it to another number."""
    _post(hook, _fixture("call_start_unrostered.json"))
    spoofed = _fixture("call_start_rostered.json") | {
        "conversation_id": "conv_synthetic_unrostered_0001"
    }

    response = _post(hook, spoofed)

    assert response.json()["dynamic_variables"]["rejected"] is True
    [call] = _calls(db_session)
    assert call.foreman_id is None


def test_response_time_p95_under_500ms_over_50_calls(hook: TestClient) -> None:
    timings_ms: list[float] = []
    for i in range(50):
        fixture = "call_start_rostered.json" if i % 2 == 0 else "call_start_unrostered.json"
        payload = _fixture(fixture) | {"conversation_id": f"conv_perf_{i:03d}"}
        started = time.perf_counter()
        response = _post(hook, payload)
        timings_ms.append((time.perf_counter() - started) * 1000)
        assert response.status_code == 200

    timings_ms.sort()
    p95 = timings_ms[math.ceil(0.95 * len(timings_ms)) - 1]  # nearest rank
    print(
        f"call-start over {len(timings_ms)} local calls: "
        f"p50={timings_ms[len(timings_ms) // 2 - 1]:.1f} ms p95={p95:.1f} ms "
        f"max={timings_ms[-1]:.1f} ms"
    )
    assert p95 < 500
