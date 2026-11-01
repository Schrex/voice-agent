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
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.clock import Clock, get_clock
from app.config import tool_secret
from app.db.session import get_session
from app.services.calls import Caller, caller_for_conversation
from app.services.jobs import find_jobs
from app.services.requests import NewItem, submit_requests

log = logging.getLogger(__name__)

NOT_SAVED = "The request could not be saved."
JOBS_NOT_SEARCHED = "The Job list could not be searched."


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
    # One item per call until ticket #15 adds multiple items.
    items: list[SubmitItem] = Field(min_length=1, max_length=1)


class FindJobsBody(BaseModel):
    query: str


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
    x_conversation_id: Annotated[str | None, Header()] = None,
) -> Any:
    log_ctx = {"conversation_id": x_conversation_id}
    try:
        parsed = SubmitBody.model_validate(body)
    except ValidationError:
        log.warning("submit_requests_invalid", extra=log_ctx)
        return {"error": NOT_SAVED}
    items = [NewItem(**item.model_dump()) for item in parsed.items]
    try:
        refs = submit_requests(session, caller=caller, items=items, now=clock())
    except Exception:
        session.rollback()
        log.exception("submit_requests_failed", extra=log_ctx)
        return {"error": NOT_SAVED}
    log.info("submit_requests", extra={**log_ctx, "ref": refs})
    return [{"ref": ref} for ref in refs]
