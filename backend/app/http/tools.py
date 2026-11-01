"""Agent tools, `POST /tools/*` (architecture §4.2).

Every call carries `X-Tool-Secret` and `X-Conversation-Id`. The Foreman is resolved from the
conversation (bound at call start), never from the body (ADR 0004). A bad secret is 401 and an
unknown or rejected conversation is 403, with nothing written. Anything else that goes wrong
returns HTTP 200 with a speakable `{"error": ...}` so the agent can tell the Foreman (spec §8).
"""

import hmac
import logging
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from pydantic import BaseModel, Field, StringConstraints, ValidationError
from sqlalchemy.orm import Session

from app.clock import Clock, get_clock
from app.config import tool_secret
from app.db.session import get_session
from app.domain.urgency import Urgency
from app.http.sms import get_sms_sender
from app.integrations.twilio_sms import SmsSender
from app.services.alerts import alert_callback, alert_new_today, alert_transfer
from app.services.callbacks import create_callback_request
from app.services.calls import Caller, caller_for_conversation
from app.services.duplicates import find_duplicates
from app.services.emergencies import EmergencyReport, start_emergency
from app.services.jobs import find_jobs
from app.services.notes import NoteRequestNotFound, add_note_for_caller
from app.services.requests import NewItem, resolve_needed_by, submit_requests
from app.services.status_lookup import find_open_requests

log = logging.getLogger(__name__)

NOT_SAVED = "The request could not be saved."
JOBS_NOT_SEARCHED = "The Job list could not be searched."
TIME_NOT_READ = "The needed-by time could not be worked out."


def require_tool_secret(
    x_tool_secret: Annotated[str | None, Header()] = None,
) -> None:
    """401 unless `X-Tool-Secret` matches `TOOL_SECRET`. Runs before the body is read."""
    expected = tool_secret()
    if expected is None:
        log.error("TOOL_SECRET is not set; rejecting tool call")
    if (
        expected is None
        or x_tool_secret is None
        or not hmac.compare_digest(x_tool_secret.encode(), expected.encode())
    ):
        raise HTTPException(status_code=401, detail="unauthorized")


def get_caller(
    session: Annotated[Session, Depends(get_session)],
    x_conversation_id: Annotated[str | None, Header()] = None,
) -> Caller:
    """The verified Foreman of this conversation; 403 if unknown or not rostered."""
    caller = caller_for_conversation(session, x_conversation_id) if x_conversation_id else None
    if caller is None:
        raise HTTPException(status_code=403, detail="unknown conversation")
    return caller


router = APIRouter(prefix="/tools", dependencies=[Depends(require_tool_secret)])

Category = Literal[
    "Trucking",
    "Equipment",
    "Equipment Repair",
    "Material",
    "Labor",
    "Information",
    "Callback",
    "Other",
]


class SubmitItem(BaseModel):
    """One confirmed need. Unknown fields (such as a foreman id) are ignored."""

    job_id: int | None = None
    """From `find_jobs`; omitted when it found no Job (the Request is Unmatched)."""
    job_spoken: str = Field(min_length=1)
    category: Category
    need: str = Field(min_length=1)
    quantity: Decimal | None = None
    unit: str | None = None
    needed_by_spoken: str | None = None


class SubmitBody(BaseModel):
    """Every need the Foreman confirmed together; recorded all or none (ticket #15)."""

    items: list[SubmitItem] = Field(min_length=1)


class FindJobsBody(BaseModel):
    query: str


class ResolveNeededByBody(BaseModel):
    needed_by_spoken: str


@router.post("/find_jobs")
def find_jobs_tool(
    body: Annotated[Any, Body()],
    caller: Annotated[Caller, Depends(get_caller)],
    session: Annotated[Session, Depends(get_session)],
    x_conversation_id: Annotated[str | None, Header()] = None,
) -> Any:
    """Up to three `{job_id, name, score}`; an empty list means no confident match."""
    log_ctx = {"conversation_id": x_conversation_id}
    try:
        parsed = FindJobsBody.model_validate(body, strict=True)
    except ValidationError:
        log.warning("find_jobs_invalid", extra=log_ctx)
        return {"error": JOBS_NOT_SEARCHED}
    try:
        matches = find_jobs(session, parsed.query)
    except Exception:
        log.exception("find_jobs_failed", extra=log_ctx)
        return {"error": JOBS_NOT_SEARCHED}
    log.info("find_jobs", extra={**log_ctx, "matches": len(matches)})
    return [{"job_id": m.job_id, "name": m.name, "score": m.score} for m in matches]


@router.post("/submit_requests")
def submit_requests_tool(
    body: Annotated[Any, Body()],
    caller: Annotated[Caller, Depends(get_caller)],
    session: Annotated[Session, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
    sms: Annotated[SmsSender, Depends(get_sms_sender)],
    x_conversation_id: Annotated[str | None, Header()] = None,
) -> Any:
    """Records the confirmed items; a Today Request texts the on-duty Coordinator (AC1.9)."""
    log_ctx = {"conversation_id": x_conversation_id}
    try:
        parsed = SubmitBody.model_validate(body)
    except ValidationError:
        log.warning("submit_requests_invalid", extra=log_ctx)
        return {"error": NOT_SAVED}
    items = [NewItem(**item.model_dump()) for item in parsed.items]
    try:
        recorded = submit_requests(session, caller=caller, items=items, now=clock())
    except Exception:
        session.rollback()
        log.exception("submit_requests_failed", extra=log_ctx)
        return {"error": NOT_SAVED}
    log.info("submit_requests", extra={**log_ctx, "ref": [r.ref for r in recorded]})
    now = clock()
    for r in recorded:
        if r.needed_by.urgency != Urgency.TODAY.value:
            continue
        # The Request is saved; an alert problem must not turn into a spoken error.
        try:
            alert_new_today(session, sms, ref=r.ref, now=now)
        except Exception:
            session.rollback()
            log.exception("today_alert_failed", extra={**log_ctx, "ref": r.ref})
    return [
        {
            "ref": r.ref,
            "needed_by_resolved": r.needed_by.needed_by_resolved,
            "urgency": r.needed_by.urgency,
        }
        for r in recorded
    ]


@router.post("/resolve_needed_by")
def resolve_needed_by_tool(
    body: Annotated[Any, Body()],
    caller: Annotated[Caller, Depends(get_caller)],
    clock: Annotated[Clock, Depends(get_clock)],
    x_conversation_id: Annotated[str | None, Header()] = None,
) -> Any:
    """The spoken needed-by as the agent must read it back, before the Foreman confirms.

    `{"needed_by_resolved": "Monday, November 2 at 7:00 AM", "urgency": "Planned"}`; both null
    when the words are not understood (the agent then reads them back as said). Writes nothing.
    """
    log_ctx = {"conversation_id": x_conversation_id}
    try:
        parsed = ResolveNeededByBody.model_validate(body, strict=True)
    except ValidationError:
        log.warning("resolve_needed_by_invalid", extra=log_ctx)
        return {"error": TIME_NOT_READ}
    resolved = resolve_needed_by(parsed.needed_by_spoken, clock())
    log.info("resolve_needed_by", extra={**log_ctx, "resolved": resolved.urgency is not None})
    return {"needed_by_resolved": resolved.needed_by_resolved, "urgency": resolved.urgency}


# --- find_open_requests (ticket #16, spec J3) ---

NOT_LOOKED_UP = "Your Requests could not be looked up."


class FindOpenRequestsBody(BaseModel):
    """Both optional. Unknown fields (such as a foreman id) are ignored."""

    job_id: int | None = None
    """From `find_jobs`."""
    category: Category | None = None


@router.post("/find_open_requests")
def find_open_requests_tool(
    body: Annotated[Any, Body()],
    caller: Annotated[Caller, Depends(get_caller)],
    session: Annotated[Session, Depends(get_session)],
    x_conversation_id: Annotated[str | None, Header()] = None,
) -> Any:
    """The caller's own Requests with their recorded state; `[]` when none match."""
    log_ctx = {"conversation_id": x_conversation_id}
    try:
        parsed = FindOpenRequestsBody.model_validate(body, strict=True)
    except ValidationError:
        log.warning("find_open_requests_invalid", extra=log_ctx)
        return {"error": NOT_LOOKED_UP}
    try:
        found = find_open_requests(
            session, caller=caller, job_id=parsed.job_id, category=parsed.category
        )
    except Exception:
        session.rollback()
        log.exception("find_open_requests_failed", extra=log_ctx)
        return {"error": NOT_LOOKED_UP}
    log.info("find_open_requests", extra={**log_ctx, "ref": [r.ref for r in found]})
    return [
        {
            "ref": r.ref,
            "job": r.job,
            "category": r.category,
            "need": r.need,
            "quantity": _number(r.quantity),
            "unit": r.unit,
            "needed_by": r.needed_by,
            "status": r.status,
            "owner": r.owner,
            "outcome": r.outcome,
            "explanation": r.explanation,
        }
        for r in found
    ]


def _number(quantity: Decimal | None) -> int | float | None:
    """3 rather than "3" or 3.0, so the agent can say it as a number."""
    if quantity is None:
        return None
    return int(quantity) if quantity == quantity.to_integral_value() else float(quantity)


# --- create_callback_request (ticket #24, spec J5 "Callback Request") ---

CALLBACK_NOT_SAVED = "The callback request could not be saved."


class CreateCallbackBody(BaseModel):
    """Unknown fields (such as a foreman id) are ignored."""

    reason: str | None = None
    """The Foreman's answer to "What's it about?"; omitted when they gave none."""


@router.post("/create_callback_request")
def create_callback_request_tool(
    body: Annotated[Any, Body()],
    caller: Annotated[Caller, Depends(get_caller)],
    session: Annotated[Session, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
    sms: Annotated[SmsSender, Depends(get_sms_sender)],
    x_conversation_id: Annotated[str | None, Header()] = None,
) -> Any:
    """Records a Callback Request (Today) and texts the on-duty and backup Coordinators.

    `{"ref": "R-1042"}`. No callback time is returned: there is none to promise.
    """
    log_ctx = {"conversation_id": x_conversation_id}
    try:
        parsed = CreateCallbackBody.model_validate(body, strict=True)
    except ValidationError:
        log.warning("create_callback_request_invalid", extra=log_ctx)
        return {"error": CALLBACK_NOT_SAVED}
    try:
        ref = create_callback_request(session, caller=caller, reason=parsed.reason, now=clock())
    except Exception:
        session.rollback()
        log.exception("create_callback_request_failed", extra=log_ctx)
        return {"error": CALLBACK_NOT_SAVED}
    log.info("create_callback_request", extra={**log_ctx, "ref": ref})
    # The Request is saved; an alert problem must not turn into a spoken error.
    try:
        alert_callback(session, sms, ref=ref, now=clock())
    except Exception:
        session.rollback()
        log.exception("callback_alert_failed", extra={**log_ctx, "ref": ref})
    return {"ref": ref}


# --- add_note (ticket #17, spec J3 step 4) ---

NOTE_NOT_SAVED = "The note could not be saved."
NOTE_REQUEST_NOT_FOUND = "I couldn't find that request."


class AddNoteBody(BaseModel):
    """Unknown fields (such as a foreman id) are ignored."""

    ref: str
    """As `find_open_requests` returned it ("R-1042")."""
    text: str = Field(min_length=1)
    urgent: bool = False


@router.post("/add_note")
def add_note_tool(
    body: Annotated[Any, Body()],
    caller: Annotated[Caller, Depends(get_caller)],
    session: Annotated[Session, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
    x_conversation_id: Annotated[str | None, Header()] = None,
) -> Any:
    """Appends the Foreman's note to one of his own Requests; `{"ok": true}`. Never creates one.

    Another Foreman's Request, a Draft or an unknown ref is "not found", with nothing written.
    """
    log_ctx = {"conversation_id": x_conversation_id}
    try:
        parsed = AddNoteBody.model_validate(body, strict=True)
    except ValidationError:
        log.warning("add_note_invalid", extra=log_ctx)
        return {"error": NOTE_NOT_SAVED}
    try:
        add_note_for_caller(
            session,
            caller=caller,
            ref=parsed.ref,
            text=parsed.text,
            urgent=parsed.urgent,
            now=clock(),
        )
    except NoteRequestNotFound:
        session.rollback()
        log.info("add_note_not_found", extra=log_ctx)
        return {"error": NOTE_REQUEST_NOT_FOUND}
    except Exception:
        session.rollback()
        log.exception("add_note_failed", extra=log_ctx)
        return {"error": NOTE_NOT_SAVED}
    log.info("add_note", extra={**log_ctx, "ref": parsed.ref, "urgent": parsed.urgent})
    return {"ok": True}


# --- find_duplicates (ticket #18, spec J2) ---

NOT_CHECKED = "Your open Requests could not be checked."


class FindDuplicatesBody(BaseModel):
    """The new need's Job and Category. Unknown fields (such as a foreman id) are ignored."""

    job_id: int
    """From `find_jobs`. An Unmatched need has none and is never checked."""
    category: Category


@router.post("/find_duplicates")
def find_duplicates_tool(
    body: Annotated[Any, Body()],
    caller: Annotated[Caller, Depends(get_caller)],
    session: Annotated[Session, Depends(get_session)],
    x_conversation_id: Annotated[str | None, Header()] = None,
) -> Any:
    """The caller's open Requests a new need on this Job and Category duplicates; `[]` if none.

    Writes nothing. The agent asks whether the need is about one of them: yes → `add_note`
    on it, no → `submit_requests`.
    """
    log_ctx = {"conversation_id": x_conversation_id}
    try:
        parsed = FindDuplicatesBody.model_validate(body, strict=True)
    except ValidationError:
        log.warning("find_duplicates_invalid", extra=log_ctx)
        return {"error": NOT_CHECKED}
    try:
        found = find_duplicates(
            session, foreman_id=caller.foreman_id, job_id=parsed.job_id, category=parsed.category
        )
    except Exception:
        session.rollback()
        log.exception("find_duplicates_failed", extra=log_ctx)
        return {"error": NOT_CHECKED}
    log.info("find_duplicates", extra={**log_ctx, "ref": [d.ref for d in found]})
    return [
        {
            "ref": d.ref,
            "job": d.job,
            "category": d.category,
            "need": d.need,
            "quantity": _number(d.quantity),
            "unit": d.unit,
            "needed_by": d.needed_by,
            "recorded_at": d.recorded_at,
        }
        for d in found
    ]


# --- transfer_to_office (ticket #25, spec J5) ---

OFFICE_NOT_TOLD = "The office could not be told you are coming."


class TransferToOfficeBody(BaseModel):
    """All optional: the Foreman need not give a reason (AC5.1). Unknown fields are ignored."""

    reason: str | None = None
    """What the Foreman wants to talk about, in their words, if they said."""
    job_id: int | None = None
    """From `find_jobs`, when the Job is already known on this call."""
    job_spoken: str | None = None
    """The Job in the Foreman's words, if they named one."""


@router.post("/transfer_to_office")
def transfer_to_office_tool(
    body: Annotated[Any, Body()],
    caller: Annotated[Caller, Depends(get_caller)],
    session: Annotated[Session, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
    sms: Annotated[SmsSender, Depends(get_sms_sender)],
    x_conversation_id: Annotated[str | None, Header()] = None,
) -> Any:
    """Pop-up + SMS to the on-duty Coordinator, before the agent transfers (architecture §3.3).

    `{"ok": true}` once the office notice is recorded, even if the SMS could not be sent (that
    alert is recorded as failed). The agent transfers whatever this returns.
    """
    log_ctx = {"conversation_id": x_conversation_id}
    try:
        parsed = TransferToOfficeBody.model_validate(body, strict=True)
    except ValidationError:
        log.warning("transfer_to_office_invalid", extra=log_ctx)
        return {"error": OFFICE_NOT_TOLD}
    try:
        alert_transfer(
            session,
            sms,
            call_id=caller.call_id,
            job_id=parsed.job_id,
            job_spoken=parsed.job_spoken,
            about=parsed.reason,
            now=clock(),
        )
    except Exception:
        session.rollback()
        log.exception("transfer_to_office_failed", extra=log_ctx)
        return {"error": OFFICE_NOT_TOLD}
    log.info("transfer_to_office", extra=log_ctx)
    return {"ok": True}


# --- start_emergency (ticket #26, spec J6) ---

EMERGENCY_NOT_RECORDED = "The emergency could not be recorded."


class StartEmergencyBody(BaseModel):
    """Only what the Foreman already said. Unknown fields (such as a foreman id) are ignored."""

    summary: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    """What happened, in the Foreman's words."""
    job_id: int | None = None
    """From `find_jobs`, when the Job is already known on this call."""
    job_spoken: str | None = None
    """The Job in the Foreman's words, if they named one."""


@router.post("/start_emergency")
def start_emergency_tool(
    body: Annotated[Any, Body()],
    caller: Annotated[Caller, Depends(get_caller)],
    session: Annotated[Session, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
    sms: Annotated[SmsSender, Depends(get_sms_sender)],
    x_conversation_id: Annotated[str | None, Header()] = None,
) -> Any:
    """Emergency Request + pop-up + SMS to every Coordinator, before the agent transfers
    (architecture §3.3). `{"ref": "R-1042"}`, even if an SMS could not be sent (that alert is
    recorded as failed). The agent transfers whatever this returns.
    """
    log_ctx = {"conversation_id": x_conversation_id}
    try:
        parsed = StartEmergencyBody.model_validate(body, strict=True)
    except ValidationError:
        log.warning("start_emergency_invalid", extra=log_ctx)
        return {"error": EMERGENCY_NOT_RECORDED}
    try:
        ref = start_emergency(
            session,
            sms,
            caller=caller,
            report=EmergencyReport(
                summary=parsed.summary, job_id=parsed.job_id, job_spoken=parsed.job_spoken
            ),
            now=clock(),
        )
    except Exception:
        session.rollback()
        log.exception("start_emergency_failed", extra=log_ctx)
        return {"error": EMERGENCY_NOT_RECORDED}
    log.info("start_emergency", extra={**log_ctx, "ref": ref})
    return {"ref": ref}
