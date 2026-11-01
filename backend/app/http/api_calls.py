"""Calls on the dashboard (`/api/calls/*`, architecture §4.3): transcript and recording.

Recordings are for staff only (coordinators and admins, spec §4 "Recording access"): every
route requires a staff token, and the audio is streamed from ElevenLabs through the backend.
"""

from datetime import UTC, datetime
from functools import cache
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import elevenlabs_api_base, elevenlabs_api_key
from app.db.session import get_session
from app.http.auth import CurrentStaff
from app.integrations.elevenlabs import ElevenLabsAudio, RecordingNotFound, RecordingUnavailable
from app.services.call_records import call_audio, call_record

router = APIRouter(prefix="/api/calls")


@cache
def _elevenlabs_client(base_url: str) -> httpx.Client:
    # Connect fast; between audio chunks allow a slow ElevenLabs.
    return httpx.Client(base_url=base_url, timeout=httpx.Timeout(30.0, connect=5.0))


def elevenlabs_audio() -> ElevenLabsAudio:
    return ElevenLabsAudio(_elevenlabs_client(elevenlabs_api_base()), elevenlabs_api_key())


class TurnOut(BaseModel):
    role: str  # agent | user (the Foreman)
    message: str
    at_s: int | float  # seconds into the call


class CallOut(BaseModel):
    id: int
    started_at: str  # UTC, ISO 8601 with "Z"
    ended_at: str | None  # null until the post-call record arrives
    duration_s: int | None
    transcript: list[TurnOut]  # what was said, in order


@router.get("/{call_id}")
def call(
    call_id: int, staff: CurrentStaff, session: Annotated[Session, Depends(get_session)]
) -> CallOut:
    """One Call's transcript and post-call record."""
    found = call_record(session, call_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such call")
    return CallOut(
        id=found.id,
        started_at=_utc(found.started_at),
        ended_at=_utc(found.ended_at) if found.ended_at else None,
        duration_s=found.duration_s,
        transcript=[TurnOut(role=t.role, message=t.message, at_s=t.at_s) for t in found.transcript],
    )


@router.get("/{call_id}/audio", response_class=StreamingResponse)
def audio(
    call_id: int,
    staff: CurrentStaff,
    session: Annotated[Session, Depends(get_session)],
    elevenlabs: Annotated[ElevenLabsAudio, Depends(elevenlabs_audio)],
) -> StreamingResponse:
    """The Call's recording, streamed from ElevenLabs. 404 when there is none (any more)."""
    try:
        recording = call_audio(session, call_id, elevenlabs)
    except RecordingNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No recording for this call") from exc
    except RecordingUnavailable as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Recording unavailable") from exc
    if recording is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such call")
    return StreamingResponse(
        recording.chunks,
        media_type=recording.content_type,
        headers={"Cache-Control": "private, no-store"},
    )


def _utc(at: datetime) -> str:
    return at.astimezone(UTC).isoformat().replace("+00:00", "Z")
