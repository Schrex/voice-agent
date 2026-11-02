"""The ack window a Request gets when it is Recorded (ticket #22; spec §4, AC9.3)."""

from sqlalchemy.orm import Session

from app.db.models import Request
from app.domain.sla import ack_due_at
from app.domain.urgency import Urgency
from app.services.settings import ack_windows


def set_ack_due_at(session: Session, request: Request) -> None:
    """Start the ack window of a Request just Recorded: its `recorded_at` plus the office's
    window for its Urgency; Emergency and no Urgency get the Today window (`domain.sla.ack_due_at`).

    Does not commit: the caller writes it with the Request's `recorded` event.
    """
    if request.recorded_at is None:
        raise ValueError("Only a Recorded Request has an ack window")
    urgency = None if request.urgency is None else Urgency(request.urgency)
    request.ack_due_at = ack_due_at(urgency, request.recorded_at, ack_windows(session))
