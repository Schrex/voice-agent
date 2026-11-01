"""Request lifecycle guards (architecture §5, GLOSSARY "Lifecycle"). Pure: no I/O.

Statuses and Outcomes are the glossary words, stored verbatim. Each move has one guard:
- `transition`: Draft → Recorded (no requirement).
- `acknowledge`: Recorded → Acknowledged, Owner required.
- `start`: Acknowledged → In Progress.
- `resolve`: any non-Resolved status → Resolved, Outcome and explanation required.
Any other move raises `TransitionNotAllowed`. The agent's narrower right (only Recorded or
Acknowledged → Resolved/Withdrawn) is left to the ticket that builds the agent's withdrawal.
"""

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


class OutcomeRequired(ValueError):
    """Resolved means the request carries an Outcome (GLOSSARY); there is none (AC9.2)."""

    def __init__(self) -> None:
        super().__init__("An Outcome is required to resolve a request")


class ExplanationRequired(ValueError):
    """Resolved means the request carries an explanation (GLOSSARY); there is none (AC9.2)."""

    def __init__(self) -> None:
        super().__init__("An explanation is required to resolve a request")


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
