"""Call start: roster check and the context the voice agent gets (spec J8, architecture §3.1).

The first delivery for a conversation records a Call bound to the caller's Foreman (or to no
Foreman, outcome `rejected`, for an unrostered number). Later deliveries for the same
conversation reuse that row, so a conversation can never be rebound to another number.
"""

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import Call, ForemanPhone, Job
from app.domain.local_time import speakable_local_time


@dataclass(frozen=True)
class CallStart:
    """What the agent may know at call start. Empty for a rejected (unrostered) caller."""

    rejected: bool
    foreman_first_name: str = ""
    job_names: list[str] = field(default_factory=list)
    now_local: str = ""


def rejection_line(main_number: str) -> str:
    """Spec J8, verbatim."""
    return f"This line is for registered crew leaders. Please call the office at {main_number}."


def start_call(
    session: Session,
    *,
    conversation_id: str,
    caller_e164: str,
    call_sid: str | None,
    now: datetime,
) -> CallStart:
    foreman_id = session.scalar(
        select(ForemanPhone.foreman_id).where(ForemanPhone.e164 == caller_e164)
    )
    session.execute(
        insert(Call)
        .values(
            conversation_id=conversation_id,
            call_sid=call_sid,
            caller_e164=caller_e164,
            foreman_id=foreman_id,
            started_at=now,
            outcome=None if foreman_id is not None else "rejected",
        )
        .on_conflict_do_nothing(index_elements=[Call.conversation_id])
    )
    session.commit()

    call = session.scalars(select(Call).where(Call.conversation_id == conversation_id)).one()
    if call.foreman is None:
        return CallStart(rejected=True)
    job_names = session.scalars(select(Job.name).where(Job.active).order_by(Job.name)).all()
    return CallStart(
        rejected=False,
        foreman_first_name=call.foreman.first_name,
        job_names=list(job_names),
        now_local=speakable_local_time(now),
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
