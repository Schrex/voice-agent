"""ElevenLabs → backend webhooks (architecture §4.1)."""

import hmac
import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.clock import Clock, get_clock
from app.config import elevenlabs_webhook_secret, hook_secret, office_main_number
from app.db.session import get_session
from app.http.signature import signature_is_valid
from app.services.calls import (
    PostCall,
    PostCallResult,
    record_post_call,
    rejection_line,
    start_call,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/hooks")


def require_hook_secret(
    x_hook_secret: Annotated[str | None, Header()] = None,
) -> None:
    """401 unless `X-Hook-Secret` matches `HOOK_SECRET`. Runs before the body is read."""
    expected = hook_secret()
    if expected is None:
        log.error("HOOK_SECRET is not set; rejecting call-start webhook")
    if (
        expected is None
        or x_hook_secret is None
        or not hmac.compare_digest(x_hook_secret.encode(), expected.encode())
    ):
        raise HTTPException(status_code=401, detail="unauthorized")


class CallStartPayload(BaseModel):
    """ElevenLabs conversation-initiation webhook body for an inbound Twilio call."""

    caller_id: str
    conversation_id: str
    call_sid: str | None = None
    called_number: str | None = None
    agent_id: str | None = None


@router.post("/call-start", dependencies=[Depends(require_hook_secret)])
def call_start(
    payload: CallStartPayload,
    session: Annotated[Session, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> dict[str, Any]:
    started = start_call(
        session,
        conversation_id=payload.conversation_id,
        caller_e164=payload.caller_id,
        call_sid=payload.call_sid,
        now=clock(),
    )
    log.info(
        "call_start",
        extra={"conversation_id": payload.conversation_id, "rejected": started.rejected},
    )
    # ElevenLabs requires every dynamic variable the agent defines, so a rejected caller
    # gets the same keys, empty.
    response: dict[str, Any] = {
        "type": "conversation_initiation_client_data",
        "dynamic_variables": {
            "rejected": started.rejected,
            "foreman_first_name": started.foreman_first_name,
            # The agent reads back the name and passes the id to submit_requests.
            "jobs": "; ".join(f"{name} (job_id {job_id})" for job_id, name in started.jobs),
            "now_local": started.now_local,
        },
    }
    if started.rejected:
        response["conversation_config_override"] = {
            "agent": {"first_message": rejection_line(office_main_number())}
        }
    return response


async def verified_body(request: Request, clock: Annotated[Clock, Depends(get_clock)]) -> bytes:
    """The raw body, once its `ElevenLabs-Signature` checks out; 401 otherwise."""
    secret = elevenlabs_webhook_secret()
    if secret is None:
        log.error("ELEVENLABS_WEBHOOK_SECRET is not set; rejecting post-call webhook")
    body = await request.body()
    header = request.headers.get("ElevenLabs-Signature")
    if secret is None or not signature_is_valid(body, header, secret, clock()):
        raise HTTPException(status_code=401, detail="unauthorized")
    return body


class _PhoneCall(BaseModel):
    external_number: str | None = None
    call_sid: str | None = None


class _Metadata(BaseModel):
    start_time_unix_secs: int
    call_duration_secs: int
    termination_reason: str | None = None
    phone_call: _PhoneCall | None = None


class _Analysis(BaseModel):
    transcript_summary: str | None = None


class _Transcription(BaseModel):
    conversation_id: str
    transcript: list[dict[str, Any]]
    metadata: _Metadata
    analysis: _Analysis | None = None


def _tools_called(transcript: list[dict[str, Any]]) -> list[str]:
    """Tool names from the transcript turns' `tool_calls` (`[{tool_name, ...}]`)."""
    return [
        tool_call["tool_name"]
        for turn in transcript
        for tool_call in turn.get("tool_calls") or []
        if isinstance(tool_call, dict) and isinstance(tool_call.get("tool_name"), str)
    ]


class _Event(BaseModel):
    type: str
    data: dict[str, Any]


@router.post("/post-call")
def post_call(
    body: Annotated[bytes, Depends(verified_body)],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, str]:
    try:
        event = _Event.model_validate_json(body)
        if event.type != "post_call_transcription":
            return {"status": "ignored"}
        data = _Transcription.model_validate(event.data)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail="invalid post-call payload") from error
    phone_call = data.metadata.phone_call
    result = record_post_call(
        session,
        PostCall(
            conversation_id=data.conversation_id,
            started_at=datetime.fromtimestamp(data.metadata.start_time_unix_secs, UTC),
            duration_s=data.metadata.call_duration_secs,
            termination_reason=data.metadata.termination_reason,
            transcript=data.transcript,
            summary=data.analysis.transcript_summary if data.analysis else None,
            tools_called=_tools_called(data.transcript),
            caller_e164=phone_call.external_number if phone_call else None,
            call_sid=phone_call.call_sid if phone_call else None,
        ),
    )
    if result is PostCallResult.UNKNOWN_CALL:
        log.warning("post_call_unknown_call", extra={"conversation_id": data.conversation_id})
    else:
        log.info("post_call", extra={"conversation_id": data.conversation_id, "result": result})
    # Always 200 once signed: ElevenLabs may disable a webhook that keeps failing.
    return {"status": result.value}
