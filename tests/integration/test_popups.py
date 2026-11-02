"""Incoming-transfer pop-ups on the dashboard (ticket #25; spec J5 step 2, AC5.3).

`GET /api/popups?since` lists pop-ups nobody has dismissed; `POST /api/popups/{id}/dismiss`
hides one for everybody (`alerts.seen_at`). The pop-ups come from `/tools/transfer_to_office`.
"""

import json
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import get_clock
from app.db.models import Alert, Staff
from app.http.sms import get_sms_sender
from app.main import app
from app.services.roster import load_roster_file, seed_roster

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_ROSTER = ROOT / "backend" / "seed" / "sample_roster.json"
ROSTERED = json.loads((ROOT / "tests/fixtures/elevenlabs/call_start_rostered.json").read_text())
HOOK_SECRET = "test-hook-secret"
TOOL_SECRET = "test-tool-secret"
JWT_SECRET = "test-jwt-secret-at-least-32-bytes-long"
NOW = datetime(2026, 11, 1, 20, 4, tzinfo=UTC)
RITA = {**ROSTERED, "caller_id": "+15855550103", "conversation_id": "conv_synthetic_rita_0001"}


@dataclass
class Now:
    at: datetime = NOW


@dataclass
class NoSms:
    sent: list[tuple[str, str]] = field(default_factory=list)

    def send(self, to: str, body: str) -> str:
        self.sent.append((to, body))
        return "SM1"


@pytest.fixture
def now() -> Now:
    return Now()


@pytest.fixture
def api(
    client: TestClient, db_session: Session, now: Now, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch.setenv("HOOK_SECRET", HOOK_SECRET)
    monkeypatch.setenv("TOOL_SECRET", TOOL_SECRET)
    monkeypatch.setenv("OFFICE_MAIN_NUMBER", "585-555-0100")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", JWT_SECRET)
    seed_roster(db_session, load_roster_file(SAMPLE_ROSTER))
    app.dependency_overrides[get_clock] = lambda: lambda: now.at
    sms = NoSms()
    app.dependency_overrides[get_sms_sender] = lambda: sms
    for start in (ROSTERED, RITA):
        started = client.post(
            "/hooks/call-start", json=start, headers={"X-Hook-Secret": HOOK_SECRET}
        )
        assert started.status_code == 200
    yield client


@pytest.fixture
def coordinator(db_session: Session) -> dict[str, str]:
    staff = Staff(id=uuid.uuid4(), name="Casey", email="casey@example.com")
    db_session.add(staff)
    db_session.flush()
    claims = {"sub": str(staff.id), "aud": "authenticated", "exp": int(time.time()) + 3600}
    return {"Authorization": f"Bearer {jwt.encode(claims, JWT_SECRET, algorithm='HS256')}"}


def _transfer(client: TestClient, conversation: str, body: dict[str, Any]) -> None:
    response = client.post(
        "/tools/transfer_to_office",
        json=body,
        headers={"X-Tool-Secret": TOOL_SECRET, "X-Conversation-Id": conversation},
    )
    assert response.json() == {"ok": True}


def test_ac5_3_a_transfer_shows_as_a_pop_up_naming_foreman_job_and_need(
    api: TestClient, coordinator: dict[str, str]
) -> None:
    assert api.get("/api/popups", headers=coordinator).json() == {"popups": []}

    _transfer(api, ROSTERED["conversation_id"], {"reason": "a loader", "job_spoken": "the quarry"})

    [popup] = api.get("/api/popups", headers=coordinator).json()["popups"]
    assert popup == {
        "id": popup["id"],
        "kind": "transfer",
        "text": "Incoming transfer: Dale Kramer, “the quarry” (Unmatched), about: a loader",
        "at": "2026-11-01T20:04:00Z",
    }


def test_pop_ups_are_newest_first_and_since_returns_only_later_ones(
    api: TestClient, coordinator: dict[str, str], now: Now
) -> None:
    _transfer(api, ROSTERED["conversation_id"], {})
    now.at = NOW + timedelta(minutes=3)
    _transfer(api, RITA["conversation_id"], {})

    every = api.get("/api/popups", headers=coordinator).json()["popups"]
    later = api.get(
        "/api/popups", params={"since": "2026-11-01T20:05:00Z"}, headers=coordinator
    ).json()["popups"]

    assert [p["text"].split(",")[0] for p in every] == [
        "Incoming transfer: Rita Owens",
        "Incoming transfer: Dale Kramer",
    ]
    assert [p["at"] for p in later] == ["2026-11-01T20:07:00Z"]


def test_ac5_3_a_dismissed_pop_up_is_gone_for_everyone(
    api: TestClient, coordinator: dict[str, str], db_session: Session, now: Now
) -> None:
    _transfer(api, ROSTERED["conversation_id"], {})
    _transfer(api, RITA["conversation_id"], {})
    first, second = api.get("/api/popups", headers=coordinator).json()["popups"]
    now.at = NOW + timedelta(minutes=1)

    dismissed = api.post(f"/api/popups/{first['id']}/dismiss", headers=coordinator)

    assert dismissed.status_code == 204
    assert api.get("/api/popups", headers=coordinator).json()["popups"] == [second]
    seen_at = db_session.scalars(select(Alert.seen_at).where(Alert.id == first["id"])).one()
    assert seen_at == NOW + timedelta(minutes=1)


def test_dismissing_twice_keeps_the_first_time(
    api: TestClient, coordinator: dict[str, str], db_session: Session, now: Now
) -> None:
    _transfer(api, ROSTERED["conversation_id"], {})
    [popup] = api.get("/api/popups", headers=coordinator).json()["popups"]
    api.post(f"/api/popups/{popup['id']}/dismiss", headers=coordinator)
    now.at = NOW + timedelta(minutes=5)

    again = api.post(f"/api/popups/{popup['id']}/dismiss", headers=coordinator)

    assert again.status_code == 204
    seen_at = db_session.scalars(select(Alert.seen_at).where(Alert.id == popup["id"])).one()
    assert seen_at == NOW


def test_only_pop_ups_can_be_dismissed(
    api: TestClient, coordinator: dict[str, str], db_session: Session
) -> None:
    _transfer(api, ROSTERED["conversation_id"], {})
    sms_id = db_session.scalars(select(Alert.id).where(Alert.channel == "sms")).one()

    assert api.post(f"/api/popups/{sms_id}/dismiss", headers=coordinator).status_code == 404
    assert api.post("/api/popups/999999/dismiss", headers=coordinator).status_code == 404


def test_pop_ups_need_a_staff_token(api: TestClient) -> None:
    _transfer(api, ROSTERED["conversation_id"], {})

    assert api.get("/api/popups").status_code == 401
    assert api.post("/api/popups/1/dismiss").status_code == 401
