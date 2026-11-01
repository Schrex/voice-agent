"""Calls: start (roster check, agent context; spec J8, architecture §3.1) and post-call record
(architecture §3.4).

The first delivery for a conversation records a Call bound to the caller's Foreman (or to no
Foreman, outcome `rejected`, for an unrostered number or a deactivated Foreman's number).
Later deliveries for the same conversation reuse that row, so a conversation can never be
rebound to another number.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import Call, CallRequest, Foreman, ForemanPhone, Job
from app.domain.call_outcome import call_outcome
from app.domain.draft import DraftItem
from app.domain.local_time import speakable_local_time
from app.services.drafts import save_draft
from app.services.duplicates import open_requests_for_call_start
from app.services.settings import office_line


@dataclass(frozen=True)
class CallStart:
    """What the agent may know at call start. Empty for a rejected (unrostered) caller."""

    rejected: bool
    foreman_first_name: str = ""
    jobs: list[str] = field(default_factory=list)
    """Active Job names, sorted."""
    now_local: str = ""
    office_line_e164: str = ""
    """The Office Line a Transfer dials (`settings`); empty if not set (ticket #25)."""
    open_requests: str = ""
    """The Foreman's open Requests, one per line (ticket #18, spec J2)."""


def rejection_line(main_number: str) -> str:
    """Spec J8, verbatim."""
    return f"This line is for registered crew leaders. Please call the office at {main_number}."


def _bind_call(
    session: Session,
    *,
    conversation_id: str,
    caller_e164: str,
    call_sid: str | None,
    started_at: datetime,
) -> None:
    """Insert the Call bound to the caller's Foreman, unless the conversation already has one.

    A deactivated Foreman's numbers stay on file but are refused like unrostered ones.
    """
    foreman_id = session.scalar(
        select(ForemanPhone.foreman_id)
        .join(Foreman)
        .where(ForemanPhone.e164 == caller_e164, Foreman.active)
    )
    session.execute(
        insert(Call)
        .values(
            conversation_id=conversation_id,
            call_sid=call_sid,
            caller_e164=caller_e164,
            foreman_id=foreman_id,
            started_at=started_at,
            outcome=None if foreman_id is not None else "rejected",
        )
        .on_conflict_do_nothing(index_elements=[Call.conversation_id])
    )


def start_call(
    session: Session,
    *,
    conversation_id: str,
    caller_e164: str,
    call_sid: str | None,
    now: datetime,
) -> CallStart:
    _bind_call(
        session,
        conversation_id=conversation_id,
        caller_e164=caller_e164,
        call_sid=call_sid,
        started_at=now,
    )
    session.commit()

    call = session.scalars(select(Call).where(Call.conversation_id == conversation_id)).one()
    if call.foreman is None:
        return CallStart(rejected=True)
    jobs = session.scalars(select(Job.name).where(Job.active).order_by(Job.name)).all()
    return CallStart(
        rejected=False,
        foreman_first_name=call.foreman.first_name,
        jobs=list(jobs),
        now_local=speakable_local_time(now),
        office_line_e164=office_line(session) or "",
        open_requests=open_requests_for_call_start(session, call.foreman.id),
    )


@dataclass(frozen=True)
class Caller:
    """The verified Foreman on a call, as bound at call start."""

    call_id: int
    foreman_id: int


def caller_for_conversation(session: Session, conversation_id: str) -> Caller | None:
    """The rostered Foreman bound to this conversation; None if unknown or rejected."""
    row = session.execute(
        select(Call.id, Call.foreman_id).where(Call.conversation_id == conversation_id)
    ).one_or_none()
    if row is None or row.foreman_id is None:
        return None
    return Caller(call_id=row.id, foreman_id=row.foreman_id)


@dataclass(frozen=True)
class PostCall:
    """What the post-call webhook reports about one conversation (architecture §3.4)."""

    conversation_id: str
    started_at: datetime
    duration_s: int
    termination_reason: str | None
    transcript: list[dict[str, Any]]
    summary: str | None
    # Names of the tools the agent called during the conversation, in order.
    tools_called: list[str]
    # Used only when no call-start created the Call for this conversation.
    caller_e164: str | None = None
    call_sid: str | None = None
    # The need the call analysis found, if any; saved as a Draft when nothing was submitted.
    draft: DraftItem | None = None


class PostCallResult(StrEnum):
    RECORDED = "recorded"
    DUPLICATE = "duplicate"  # the Call already has its record; nothing written
    UNKNOWN_CALL = "unknown_call"  # no Call and no caller number to create one; nothing written


def record_post_call(session: Session, post_call: PostCall, *, now: datetime) -> PostCallResult:
    """Store the post-call record and outcome on the Call. Idempotent: the first delivery wins.

    A conversation without a Call (its call-start never arrived) gets one here, bound to the
    caller's Foreman by the same roster rule as call start. When a rostered Foreman's call
    submitted no Request but the analysis found a need, a Draft linked to the call is saved in
    the same transaction (architecture §3.4 step 4).
    """
    if post_call.caller_e164 is not None:
        _bind_call(
            session,
            conversation_id=post_call.conversation_id,
            caller_e164=post_call.caller_e164,
            call_sid=post_call.call_sid,
            started_at=post_call.started_at,
        )
    call = session.scalars(
        select(Call).where(Call.conversation_id == post_call.conversation_id).with_for_update()
    ).one_or_none()
    if call is None:
        session.rollback()
        return PostCallResult.UNKNOWN_CALL
    if call.ended_at is not None:
        session.rollback()
        return PostCallResult.DUPLICATE
    call.ended_at = post_call.started_at + timedelta(seconds=post_call.duration_s)
    call.duration_s = post_call.duration_s
    call.termination_reason = post_call.termination_reason
    call.transcript = post_call.transcript
    call.summary = post_call.summary
    submitted = session.scalar(
        select(exists().where(CallRequest.call_id == call.id, CallRequest.relation == "created"))
    )
    drafted = False
    if not submitted and call.foreman_id is not None and post_call.draft is not None:
        save_draft(
            session, call_id=call.id, foreman_id=call.foreman_id, item=post_call.draft, now=now
        )
        drafted = True
    call.outcome = call_outcome(
        rejected=call.outcome == "rejected",
        submitted=bool(submitted),
        tools_called=post_call.tools_called,
        drafted=drafted,
        looked_up=bool(
            session.scalar(
                select(
                    exists().where(
                        CallRequest.call_id == call.id, CallRequest.relation == "looked_up"
                    )
                )
            )
        ),
    )
    session.commit()
    return PostCallResult.RECORDED
