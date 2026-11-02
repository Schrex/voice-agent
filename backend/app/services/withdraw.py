"""Withdraw a Request by phone (ticket #20; spec J4, AC4.1; architecture §4.2 `withdraw_request`).

Before In Progress (Recorded, Acknowledged; `domain.lifecycle.withdraw`, the agent's narrower
right of §5) the Request is resolved with Outcome Withdrawn and the explanation "Withdrawn by
foreman", with a `resolved` event by the agent. At or after In Progress nothing is changed: a
note says the Foreman asked to withdraw it and the Request is flagged Change requested, as an
amend is (`amend.flag_change_requested`). Either way the call is linked to the Request
(`call_requests` relation `amended`). It is all one transaction.
"""

import logging
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import CallRequest, Request
from app.domain.lifecycle import Status, may_withdraw, withdraw
from app.integrations.twilio_sms import SmsSender
from app.services.alerts import alert_withdrawn
from app.services.amend import flag_change_requested
from app.services.calls import Caller
from app.services.events import agent_event, iso
from app.services.notes import NoteRequestNotFound, own_request

WITHDRAW_NOTE = "Change requested: withdraw"

log = logging.getLogger(__name__)


class WithdrawRequestNotFound(Exception):
    """No Request of the caller's has this ref (unknown, a Draft, or another Foreman's)."""


def withdraw_request(
    session: Session, sms: SmsSender, *, caller: Caller, ref: str, now: datetime
) -> bool:
    """Withdraw the caller's Request `ref`, or flag it; True when it was withdrawn.

    The Request must be the caller's own and not a Draft; a merged one is withdrawn on its final
    target, as the lookup reports it. Otherwise WithdrawRequestNotFound, with nothing written.
    A withdrawal then texts the on-duty Coordinator (AC4.1); an alert problem is logged.
    """
    try:
        request = own_request(session, caller, ref)
    except NoteRequestNotFound as e:
        raise WithdrawRequestNotFound(ref) from e
    applied = may_withdraw(Status(request.status))
    if applied:
        _resolve_withdrawn(session, request, now)
    else:
        flag_change_requested(session, request, WITHDRAW_NOTE, now)
    session.execute(
        insert(CallRequest)
        .values(call_id=caller.call_id, request_id=request.id, relation="amended")
        .on_conflict_do_nothing()
    )
    session.commit()
    if applied:
        try:
            alert_withdrawn(session, sms, ref=request.ref_display, now=now)
        except Exception:
            session.rollback()
            log.exception("withdrawn_alert_failed", extra={"ref": request.ref_display})
    return applied


def _resolve_withdrawn(session: Session, request: Request, now: datetime) -> None:
    """Resolved, Outcome Withdrawn, "Withdrawn by foreman", and the `resolved` event."""
    status, outcome, explanation = withdraw(Status(request.status))
    before = {
        "status": request.status,
        "outcome": request.outcome,
        "explanation": request.explanation,
        "resolved_at": iso(request.resolved_at),
    }
    request.status = status.value
    request.outcome = outcome.value
    request.explanation = explanation
    request.resolved_at = now
    after = {
        "status": status.value,
        "outcome": outcome.value,
        "explanation": explanation,
        "resolved_at": iso(now),
    }
    agent_event(session, request, now, "resolved", before, after)
