"""ElevenLabs → backend webhooks (architecture §4.1)."""

import hmac
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.clock import Clock, get_clock
from app.config import hook_secret, office_main_number
from app.db.session import get_session
from app.services.calls import rejection_line, start_call

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
