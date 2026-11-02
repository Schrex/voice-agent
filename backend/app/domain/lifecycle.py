"""Request lifecycle guards (architecture §5, GLOSSARY "Lifecycle"). Pure: no I/O.

Statuses and Outcomes are the glossary words, stored verbatim. Each move has one guard:
- `transition`: Draft → Recorded (no requirement).
- `acknowledge`: Recorded → Acknowledged, Owner required.
- `start`: Acknowledged → In Progress.
- `resolve`: any non-Resolved status → Resolved, Outcome and explanation required.
- `merge`: Request A merged into Request B (ticket #33): A is resolved as `resolve` requires;
  B must be another Request that is not Resolved.
- `edit`: not a move; a coordinator may edit fields or fix the Job of any non-Resolved Request.
- `reassign`: not a move; a coordinator gives an Acknowledged or In Progress Request another
  Owner (spec J9 "Reassign owner").
- `may_amend`: not a move; a Foreman's change by phone applies only before In Progress (spec J4,
  ticket #19); from In Progress on it becomes a note and a Change requested flag instead.
- `withdraw`: the agent's narrower right (§5; ticket #20): only Recorded or Acknowledged →
  Resolved with Outcome Withdrawn and the explanation "Withdrawn by foreman". From In Progress on
  the Foreman's withdrawal is a Change requested flag instead (`may_withdraw` is False).
Any other move raises `TransitionNotAllowed`.
`mark_informed` (Foreman Informed, not a status) is allowed on a Resolved request, once.
"""

from collections.abc import Callable
from datetime import datetime
from enum import StrEnum


class Status(StrEnum):
    DRAFT = "Draft"
    RECORDED = "Recorded"
    ACKNOWLEDGED = "Acknowledged"
    IN_PROGRESS = "In Progress"
    RESOLVED = "Resolved"


class Outcome(StrEnum):
    """How a Resolved request ended (GLOSSARY "Outcome")."""

    FULFILLED = "Fulfilled"
    PARTIALLY_FULFILLED = "Partially Fulfilled"
    DENIED = "Denied"
    WITHDRAWN = "Withdrawn"


class TransitionNotAllowed(ValueError):
    def __init__(self, current: Status, target: Status) -> None:
        super().__init__(f"{current.value} → {target.value} is not allowed")
        self.current = current
        self.target = target


class OwnerRequired(ValueError):
    """Acknowledged means a coordinator set an Owner (GLOSSARY); there is none (AC9.1)."""

    def __init__(self) -> None:
        super().__init__("An Owner is required to acknowledge a request")


class NotEditable(ValueError):
    """A Resolved request is finished; its fields are no longer edited (ticket #31)."""

    def __init__(self, current: "Status") -> None:
        super().__init__(f"A {current.value} request cannot be edited")
        self.current = current


class OutcomeRequired(ValueError):
    """Resolved means the request carries an Outcome (GLOSSARY); there is none (AC9.2)."""

    def __init__(self) -> None:
        super().__init__("An Outcome is required to resolve a request")


class ExplanationRequired(ValueError):
    """Resolved means the request carries an explanation (GLOSSARY); there is none (AC9.2)."""

    def __init__(self) -> None:
        super().__init__("An explanation is required to resolve a request")


class MergeIntoItself(ValueError):
    """A Request cannot be merged into itself (ticket #33)."""

    def __init__(self) -> None:
        super().__init__("A request cannot be merged into itself")


# Statuses of a Request still in the queue: confirmed by the Foreman, not yet Resolved.
OPEN_STATUSES: frozenset[Status] = frozenset(
    {Status.RECORDED, Status.ACKNOWLEDGED, Status.IN_PROGRESS}
)

_ALLOWED: frozenset[tuple[Status, Status]] = frozenset({(Status.DRAFT, Status.RECORDED)})


def transition(current: Status, target: Status) -> Status:
    """Return `target` if the request may move there from `current`; else raise."""
    if (current, target) not in _ALLOWED:
        raise TransitionNotAllowed(current, target)
    return target


def acknowledge(current: Status, owner_id: int | None) -> Status:
    """Recorded → Acknowledged, only with an Owner; from any other status it raises."""
    if current is not Status.RECORDED:
        raise TransitionNotAllowed(current, Status.ACKNOWLEDGED)
    if owner_id is None:
        raise OwnerRequired()
    return Status.ACKNOWLEDGED


def start(current: Status) -> Status:
    """Acknowledged → In Progress (the Owner is acting); from any other status it raises."""
    if current is not Status.ACKNOWLEDGED:
        raise TransitionNotAllowed(current, Status.IN_PROGRESS)
    return Status.IN_PROGRESS


def resolve(current: Status, outcome: Outcome | None, explanation: str | None) -> Status:
    """Any non-Resolved status → Resolved, only with an Outcome and a non-blank explanation."""
    if current is Status.RESOLVED:
        raise TransitionNotAllowed(current, Status.RESOLVED)
    if outcome is None:
        raise OutcomeRequired()
    if explanation is None or not explanation.strip():
        raise ExplanationRequired()
    return Status.RESOLVED


def merge(
    source: Status,
    target: Status,
    *,
    same: bool,
    outcome: Outcome | None,
    explanation: str | None,
) -> Status:
    """Merge a Request (`source`) into another (`target`); returns the source's new status.

    Not into itself, not into a Resolved Request; the source is resolved exactly as `resolve`
    requires (not already Resolved, Outcome and explanation given).
    """
    if same:
        raise MergeIntoItself()
    if target is Status.RESOLVED:
        raise TransitionNotAllowed(target, Status.RESOLVED)
    return resolve(source, outcome, explanation)


def edit(current: Status) -> Status:
    """The status is unchanged by an edit; a Resolved request cannot be edited."""
    if current is Status.RESOLVED:
        raise NotEditable(current)
    return current


# Before In Progress: what the Foreman changes by phone is applied (spec J4).
AMENDABLE_STATUSES: frozenset[Status] = frozenset({Status.RECORDED, Status.ACKNOWLEDGED})


def may_amend(current: Status) -> bool:
    """Whether the Foreman's change is applied (Recorded or Acknowledged); else it is only
    flagged Change requested for the office."""
    return current in AMENDABLE_STATUSES


# The explanation the agent records when the Foreman withdraws a Request (ticket #20).
WITHDRAWN_BY_FOREMAN = "Withdrawn by foreman"


def may_withdraw(current: Status) -> bool:
    """Whether the agent may resolve the Request as Withdrawn (Recorded or Acknowledged, §5)."""
    return current in AMENDABLE_STATUSES


def withdraw(current: Status) -> tuple[Status, Outcome, str]:
    """Recorded/Acknowledged → Resolved, Outcome Withdrawn, "Withdrawn by foreman"; else raises."""
    if not may_withdraw(current):
        raise TransitionNotAllowed(current, Status.RESOLVED)
    return Status.RESOLVED, Outcome.WITHDRAWN, WITHDRAWN_BY_FOREMAN


class NotReassignable(ValueError):
    """Only a Request that has an Owner and is not finished gets a new Owner (spec J9)."""

    def __init__(self, current: Status) -> None:
        super().__init__(f"A {current.value} request has no Owner to reassign")
        self.current = current


# Statuses with an Owner that is still acting or about to (set at Acknowledge).
REASSIGNABLE_STATUSES: frozenset[Status] = frozenset({Status.ACKNOWLEDGED, Status.IN_PROGRESS})


def reassign(current: Status, owner_id: int | None) -> Status:
    """Reassign owner (spec J9): Acknowledged or In Progress only, with an Owner; the status is
    unchanged. A Recorded request gets its first Owner by `acknowledge`."""
    if current not in REASSIGNABLE_STATUSES:
        raise NotReassignable(current)
    if owner_id is None:
        raise OwnerRequired()
    return current


def allowed_actions(current: Status, *, foreman_informed_at: datetime | None) -> list[str]:
    """The coordinator actions the guards above allow on a Request now, in a fixed order, for
    the dashboard to offer (ADR 0004: the rules live here, not in the UI). Each is worked out
    by asking its guard; "note" is always allowed."""
    checks: list[tuple[str, Callable[[], object]]] = [
        ("acknowledge", lambda: acknowledge(current, 0)),
        ("start", lambda: start(current)),
        ("reassign", lambda: reassign(current, 0)),
        ("resolve", lambda: resolve(current, Outcome.FULFILLED, "-")),
        (
            "merge",
            lambda: merge(
                current, Status.RECORDED, same=False, outcome=Outcome.FULFILLED, explanation="-"
            ),
        ),
        ("edit", lambda: edit(current)),
        ("mark_informed", lambda: mark_informed(current, foreman_informed_at)),
    ]
    allowed = []
    for name, check in checks:
        try:
            check()
        except ValueError:
            continue
        allowed.append(name)
    return [*allowed, "note"]


class NotResolved(ValueError):
    """Foreman Informed marks that the foreman was told the outcome of a Resolved request."""

    def __init__(self, current: Status) -> None:
        super().__init__(f"Only a Resolved request can be marked Foreman Informed, not {current}")


class AlreadyInformed(ValueError):
    def __init__(self) -> None:
        super().__init__("This request is already marked Foreman Informed")


def mark_informed(current: Status, foreman_informed_at: datetime | None) -> None:
    """Mark Foreman Informed (ticket #32): Resolved only, and only once."""
    if current is not Status.RESOLVED:
        raise NotResolved(current)
    if foreman_informed_at is not None:
        raise AlreadyInformed()
