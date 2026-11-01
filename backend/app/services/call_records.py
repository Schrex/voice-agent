"""A Call's post-call record for the dashboard: transcript and recording (ticket #29). Read-only."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Call
from app.integrations.elevenlabs import ElevenLabsAudio, Recording


@dataclass(frozen=True)
class Turn:
    role: str  # "agent" | "user" (the Foreman), as ElevenLabs delivers it
    message: str
    at_s: int | float  # seconds into the call


@dataclass(frozen=True)
class CallRecord:
    id: int
    started_at: datetime
    ended_at: datetime | None
    duration_s: int | None
    transcript: list[Turn]


def call_record(session: Session, call_id: int) -> CallRecord | None:
    """The Call's transcript, start, end and duration; None if there is no such Call.

    The transcript keeps only what was said: turns without a message (tool calls) are left out.
    Before the post-call record arrives the transcript is empty.
    """
    call = session.get(Call, call_id)
    if call is None:
        return None
    return CallRecord(
        id=call.id,
        started_at=call.started_at,
        ended_at=call.ended_at,
        duration_s=call.duration_s,
        transcript=[turn for t in call.transcript or [] if (turn := _turn(t))],
    )


def call_audio(session: Session, call_id: int, audio: ElevenLabsAudio) -> Recording | None:
    """The Call's recording streamed from ElevenLabs; None if there is no such Call.

    Raises `RecordingNotFound` / `RecordingUnavailable` from the ElevenLabs client.
    """
    call = session.get(Call, call_id)
    if call is None:
        return None
    return audio.open(call.conversation_id)


def _turn(raw: dict[str, Any]) -> Turn | None:
    message = raw.get("message")
    if not isinstance(message, str) or not message.strip():
        return None
    return Turn(role=str(raw.get("role")), message=message, at_s=raw.get("time_in_call_secs") or 0)
