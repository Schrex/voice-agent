"""POST /hooks/call-start: roster check at call start (ticket #4, spec J8, architecture §3.1).

Payload fixtures in tests/fixtures/elevenlabs/ are synthetic (built from the documented
shape) until real ElevenLabs payloads are recorded.
"""

import json
import math
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import get_clock
from app.db.models import Call, Job, Settings, Staff
from app.domain.lifecycle import Outcome
from app.main import app
from app.services.calls import Caller
from app.services.requests import NewItem, resolve_request, submit_requests
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
            # Lakeside Plaza Site Work is inactive in the seed, so it is not offered. Names
            # only: the Job id comes from find_jobs (ticket #13), never from this list.
            "jobs": "Penfield Sewer Replacement; Route 104 Widening",
            "now_local": "Sunday, November 1, 2026, 3:04 PM",
            "office_line_e164": "",
            # No Requests on file yet (ticket #18 fills it).
            "open_requests": "",
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
            "office_line_e164": "",
            "open_requests": "",
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
    # No request data: open_requests is sent empty (EL needs every key) and no request ref.
    assert '"open_requests":""' in body
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


def test_rostered_caller_gets_the_office_line_from_settings(
    hook: TestClient, db_session: Session
) -> None:
    """Ticket #25: the Transfer dials `settings.office_line_e164`, the number the Admin keeps."""
    settings = db_session.get_one(Settings, 1)
    settings.office_line_e164 = "+15855550150"
    db_session.flush()

    rostered = _post(hook, _fixture("call_start_rostered.json")).json()
    rejected = _post(hook, _fixture("call_start_unrostered.json")).json()

    assert rostered["dynamic_variables"]["office_line_e164"] == "+15855550150"
    # A caller not on the Roster gets no Transfer (spec J8), so no office line.
    assert rejected["dynamic_variables"]["office_line_e164"] == ""


def test_office_line_not_set_is_sent_empty(hook: TestClient) -> None:
    body = _post(hook, _fixture("call_start_rostered.json")).json()

    assert body["dynamic_variables"]["office_line_e164"] == ""


def test_the_office_line_the_admin_sets_is_the_one_call_start_sends(
    hook: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#35 x #25: `PATCH /api/admin/settings` `office_line_e164` is the number the next call's
    Transfer dials (one source, `settings.office_line_e164`); clearing it sends it empty."""
    jwt_secret = "test-jwt-secret-at-least-32-bytes-long"
    monkeypatch.setenv("SUPABASE_JWT_SECRET", jwt_secret)
    admin = Staff(id=uuid.uuid4(), name="Avery Admin", email="avery@example.com")
    db_session.add(admin)
    db_session.flush()
    claims = {"sub": str(admin.id), "aud": "authenticated", "exp": int(time.time()) + 3600}
    headers = {"Authorization": f"Bearer {jwt.encode(claims, jwt_secret, algorithm='HS256')}"}

    changed = hook.patch(
        "/api/admin/settings", json={"office_line_e164": "+15855550150"}, headers=headers
    )
    assert changed.status_code == 200
    body = _post(hook, _fixture("call_start_rostered.json")).json()
    assert body["dynamic_variables"]["office_line_e164"] == "+15855550150"

    cleared = hook.patch("/api/admin/settings", json={"office_line_e164": None}, headers=headers)
    assert cleared.status_code == 200
    body = _post(hook, _fixture("call_start_rostered.json")).json()
    assert body["dynamic_variables"]["office_line_e164"] == ""


def test_deactivated_foremans_number_is_rejected_at_call_start(
    hook: TestClient, db_session: Session
) -> None:
    # Marco Bellini is on the roster with +15855550104 but inactive in the seed (#34).
    payload = _fixture("call_start_rostered.json") | {"caller_id": "+15855550104"}

    body = _post(hook, payload).json()

    assert body["dynamic_variables"] == {
        "rejected": True,
        "foreman_first_name": "",
        "jobs": "",
        "now_local": "",
        "office_line_e164": "",
        "open_requests": "",
    }
    assert body["conversation_config_override"]["agent"]["first_message"] == (
        "This line is for registered crew leaders. Please call the office at 585-555-0100."
    )
    [call] = _calls(db_session)
    assert call.caller_e164 == "+15855550104"
    assert call.foreman_id is None
    assert call.outcome == "rejected"


# --- open_requests (ticket #18, spec J2) ---


def _record_for(session: Session, conversation_id: str, at: datetime, **item: Any) -> str:
    """A Recorded Request of the Foreman bound to `conversation_id`; returns its ref."""
    call = session.scalars(select(Call).where(Call.conversation_id == conversation_id)).one()
    assert call.foreman_id is not None
    job_id = session.scalars(select(Job.id).where(Job.name == "Route 104 Widening")).one()
    fields: dict[str, Any] = {
        "job_id": job_id,
        "job_spoken": "the 104 job",
        "category": "Trucking",
        "need": "tri-axle dump trucks",
    } | item
    [recorded] = submit_requests(
        session,
        caller=Caller(call_id=call.id, foreman_id=call.foreman_id),
        items=[NewItem(**fields)],
        now=at,
    )
    return recorded.ref


def test_rostered_caller_gets_their_open_requests_newest_first(
    hook: TestClient, db_session: Session
) -> None:
    """The agent knows the caller's open Requests from the first turn (J2 duplicate check)."""
    dale = _fixture("call_start_rostered.json")
    rita = dale | {"caller_id": "+15855550103", "conversation_id": "conv_synthetic_rita_0001"}
    _post(hook, dale)
    _post(hook, rita)
    saturday = datetime(2026, 10, 31, 10, 45, tzinfo=UTC)  # 6:45 AM in New York
    trucks = _record_for(
        db_session,
        dale["conversation_id"],
        saturday,
        quantity=3,
        unit="trucks",
        needed_by_spoken="monday at seven",
    )
    stone = _record_for(
        db_session, dale["conversation_id"], NOW, category="Material", need="#2 stone"
    )
    resolved = _record_for(db_session, dale["conversation_id"], NOW, need="a lowboy")
    resolve_request(
        db_session,
        ref=resolved,
        outcome=Outcome.FULFILLED,
        explanation="Sent.",
        staff_id=uuid.uuid4(),
        now=NOW,
    )
    _record_for(db_session, "conv_synthetic_rita_0001", NOW, need="a water truck")

    later_call = dale | {"conversation_id": "conv_synthetic_rostered_0002"}
    sent = _post(hook, later_call).json()["dynamic_variables"]["open_requests"]

    assert sent == (
        f"{stone}: Material at Route 104 Widening, #2 stone, "
        "recorded Sunday, November 1 at 3:04 PM\n"
        f"{trucks}: Trucking at Route 104 Widening, 3 trucks tri-axle dump trucks, "
        "needed by Monday, November 2 at 7:00 AM, recorded Saturday, October 31 at 6:45 AM"
    )


def test_unrostered_caller_gets_no_open_requests_even_when_requests_exist(
    hook: TestClient, db_session: Session
) -> None:
    dale = _fixture("call_start_rostered.json")
    _post(hook, dale)
    _record_for(db_session, dale["conversation_id"], NOW)

    body = _post(hook, _fixture("call_start_unrostered.json")).json()

    assert body["dynamic_variables"]["open_requests"] == ""
