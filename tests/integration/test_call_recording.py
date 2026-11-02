"""Linked calls on a Request: transcript (`GET /api/calls/{id}`) and audio streamed from
ElevenLabs through the backend (`GET /api/calls/{id}/audio`), staff only (ticket #29).

ElevenLabs is never reached: its HTTP API is an `httpx.MockTransport`.
"""

import time
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import Call, CallRequest, Foreman, Job, Request, Staff
from app.http.api_calls import elevenlabs_audio
from app.integrations.elevenlabs import ElevenLabsAudio
from app.main import app
from app.services.calls import Caller
from app.services.requests import NewItem, submit_requests
from app.services.roster import load_roster_file, seed_roster

SAMPLE_ROSTER = Path(__file__).resolve().parents[2] / "backend" / "seed" / "sample_roster.json"

SECRET = "test-jwt-secret-at-least-32-bytes-long"
T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
AUDIO = b"ID3" + bytes(range(256)) * 64  # 16 KiB of "mp3"

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    yield


class FakeElevenLabs:
    """ElevenLabs' HTTP API as seen by the backend; records every request it gets."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.respond: Handler = lambda request: httpx.Response(
            200, content=AUDIO, headers={"content-type": "audio/mpeg"}
        )

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.respond(request)


@pytest.fixture
def elevenlabs(client: TestClient) -> Iterator[FakeElevenLabs]:
    fake = FakeElevenLabs()
    http = httpx.Client(transport=httpx.MockTransport(fake), base_url="https://el.test")
    app.dependency_overrides[elevenlabs_audio] = lambda: ElevenLabsAudio(http, api_key="el-key")
    yield fake
    http.close()


def _staff(session: Session) -> Staff:
    staff = Staff(id=uuid.uuid4(), name="Pat Lee", email="pat@example.com")
    session.add(staff)
    session.flush()
    return staff


def _token(sub: uuid.UUID) -> dict[str, str]:
    claims = {"sub": str(sub), "aud": "authenticated", "exp": int(time.time()) + 3600}
    return {"Authorization": f"Bearer {jwt.encode(claims, SECRET, algorithm='HS256')}"}


@pytest.fixture
def coordinator(db_session: Session) -> dict[str, str]:
    seed_roster(db_session, load_roster_file(SAMPLE_ROSTER))
    return _token(_staff(db_session).id)


TRANSCRIPT: list[dict[str, Any]] = [
    {
        "role": "agent",
        "message": "This call is recorded. What do you need?",
        "time_in_call_secs": 0,
    },
    {"role": "user", "message": "Two dump trucks at Route 104.", "time_in_call_secs": 4},
    {
        "role": "agent",
        "message": None,
        "time_in_call_secs": 9,
        "tool_calls": [{"type": "webhook", "tool_name": "submit_requests"}],
    },
    {"role": "agent", "message": "That's recorded as R-1000.", "time_in_call_secs": 10},
]


def _call(session: Session, *, ended: bool = True, at: datetime = T0) -> Call:
    """A rostered Call from Dale; with its post-call record unless `ended` is False."""
    dale = session.scalars(select(Foreman).where(Foreman.first_name == "Dale")).one()
    call = Call(
        conversation_id=f"conv_{uuid.uuid4().hex}",
        caller_e164="+15855550101",
        foreman_id=dale.id,
        started_at=at,
    )
    if ended:
        call.ended_at = at + timedelta(seconds=26)
        call.duration_s = 26
        call.termination_reason = "end_call tool was called."
        call.transcript = TRANSCRIPT
        call.summary = "Dale asked for two dump trucks at Route 104."
        call.outcome = "submitted"
    session.add(call)
    session.flush()
    return call


def _record(session: Session, call: Call) -> str:
    """A Request recorded on `call` through the submit service (writes the `created` link)."""
    assert call.foreman_id is not None
    job_id = session.scalars(select(Job.id).where(Job.name == "Route 104 Widening")).one()
    [recorded] = submit_requests(
        session,
        caller=Caller(call_id=call.id, foreman_id=call.foreman_id),
        items=[
            NewItem(
                job_id=job_id,
                job_spoken="the 104 job",
                category="Trucking",
                need="dump trucks",
                quantity=None,
                unit=None,
                needed_by_spoken=None,
            )
        ],
        now=call.started_at,
    )
    return recorded.ref


# --- audio -------------------------------------------------------------------------------


def test_audio_endpoint_refuses_non_staff(
    client: TestClient, db_session: Session, elevenlabs: FakeElevenLabs
) -> None:
    seed_roster(db_session, load_roster_file(SAMPLE_ROSTER))
    call = _call(db_session)
    not_staff = _token(uuid.uuid4())  # a valid Supabase token without a staff row

    no_token = client.get(f"/api/calls/{call.id}/audio")
    bad_token = client.get(
        f"/api/calls/{call.id}/audio", headers={"Authorization": "Bearer not-a-jwt"}
    )
    not_on_staff = client.get(f"/api/calls/{call.id}/audio", headers=not_staff)

    assert (no_token.status_code, bad_token.status_code) == (401, 401)
    assert not_on_staff.status_code == 403
    assert elevenlabs.requests == []  # ElevenLabs is never asked for a refused caller


def test_staff_get_the_recording_streamed_from_elevenlabs(
    client: TestClient, db_session: Session, elevenlabs: FakeElevenLabs
) -> None:
    seed_roster(db_session, load_roster_file(SAMPLE_ROSTER))
    call = _call(db_session)

    response = client.get(f"/api/calls/{call.id}/audio", headers=_token(_staff(db_session).id))

    assert response.status_code == 200
    assert response.content == AUDIO
    assert response.headers["content-type"] == "audio/mpeg"
    [sent] = elevenlabs.requests
    assert sent.method == "GET"
    assert sent.url.path == f"/v1/convai/conversations/{call.conversation_id}/audio"
    assert sent.headers["xi-api-key"] == "el-key"


def test_audio_of_an_unknown_call_is_404(
    client: TestClient, coordinator: dict[str, str], elevenlabs: FakeElevenLabs
) -> None:
    assert client.get("/api/calls/999999/audio", headers=coordinator).status_code == 404
    assert elevenlabs.requests == []


def test_recording_elevenlabs_no_longer_has_is_404(
    client: TestClient,
    db_session: Session,
    coordinator: dict[str, str],
    elevenlabs: FakeElevenLabs,
) -> None:
    call = _call(db_session)
    elevenlabs.respond = lambda request: httpx.Response(404, json={"detail": "not found"})

    assert client.get(f"/api/calls/{call.id}/audio", headers=coordinator).status_code == 404


@pytest.mark.parametrize("failure", ["500", "401", "unreachable"])
def test_elevenlabs_failure_is_502(
    client: TestClient,
    db_session: Session,
    coordinator: dict[str, str],
    elevenlabs: FakeElevenLabs,
    failure: str,
) -> None:
    call = _call(db_session)

    def respond(request: httpx.Request) -> httpx.Response:
        if failure == "unreachable":
            raise httpx.ConnectError("no route", request=request)
        return httpx.Response(int(failure), json={"detail": "nope"})

    elevenlabs.respond = respond

    assert client.get(f"/api/calls/{call.id}/audio", headers=coordinator).status_code == 502


def test_audio_without_an_elevenlabs_api_key_is_502(
    client: TestClient, db_session: Session, coordinator: dict[str, str]
) -> None:
    call = _call(db_session)
    fake = FakeElevenLabs()
    http = httpx.Client(transport=httpx.MockTransport(fake), base_url="https://el.test")
    app.dependency_overrides[elevenlabs_audio] = lambda: ElevenLabsAudio(http, api_key=None)

    assert client.get(f"/api/calls/{call.id}/audio", headers=coordinator).status_code == 502
    assert fake.requests == []


# --- transcript --------------------------------------------------------------------------


def test_call_transcript_requires_staff(client: TestClient, db_session: Session) -> None:
    seed_roster(db_session, load_roster_file(SAMPLE_ROSTER))
    call = _call(db_session)

    assert client.get(f"/api/calls/{call.id}").status_code == 401
    assert client.get(f"/api/calls/{call.id}", headers=_token(uuid.uuid4())).status_code == 403


def test_call_returns_its_transcript_and_post_call_record(
    client: TestClient, db_session: Session, coordinator: dict[str, str]
) -> None:
    call = _call(db_session)

    response = client.get(f"/api/calls/{call.id}", headers=coordinator)

    assert response.status_code == 200
    assert response.json() == {
        "id": call.id,
        "started_at": "2026-11-01T12:00:00Z",
        "ended_at": "2026-11-01T12:00:26Z",
        "duration_s": 26,
        # What was said, in order; the tool-call turn has nothing said and is left out.
        "transcript": [
            {"role": "agent", "message": "This call is recorded. What do you need?", "at_s": 0},
            {"role": "user", "message": "Two dump trucks at Route 104.", "at_s": 4},
            {"role": "agent", "message": "That's recorded as R-1000.", "at_s": 10},
        ],
    }


def test_call_without_a_post_call_record_has_no_transcript_yet(
    client: TestClient, db_session: Session, coordinator: dict[str, str]
) -> None:
    call = _call(db_session, ended=False)

    body = client.get(f"/api/calls/{call.id}", headers=coordinator).json()

    assert (body["ended_at"], body["duration_s"]) == (None, None)
    assert body["transcript"] == []


def test_unknown_call_is_404(client: TestClient, coordinator: dict[str, str]) -> None:
    assert client.get("/api/calls/999999", headers=coordinator).status_code == 404


# --- linked calls on the Request detail ----------------------------------------------------


def test_request_detail_lists_its_linked_calls(
    client: TestClient, db_session: Session, coordinator: dict[str, str]
) -> None:
    first = _call(db_session)
    ref = _record(db_session, first)
    later = _call(db_session, at=T0 + timedelta(hours=3))
    request_id = db_session.scalars(select(Request.id).where(Request.ref == int(ref[2:]))).one()
    db_session.add(CallRequest(call_id=later.id, request_id=request_id, relation="looked_up"))
    _record(db_session, _call(db_session))  # another Request's call: not listed
    db_session.flush()

    calls = client.get(f"/api/requests/{ref}", headers=coordinator).json()["calls"]

    assert calls == [
        {"id": first.id, "started_at": "2026-11-01T12:00:00Z", "relation": "created"},
        {"id": later.id, "started_at": "2026-11-01T15:00:00Z", "relation": "looked_up"},
    ]


def test_request_without_a_call_lists_none(
    client: TestClient, db_session: Session, coordinator: dict[str, str]
) -> None:
    ref = _record(db_session, _call(db_session))
    db_session.execute(delete(CallRequest))
    db_session.flush()

    assert client.get(f"/api/requests/{ref}", headers=coordinator).json()["calls"] == []
