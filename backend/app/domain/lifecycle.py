"""Request lifecycle guards (architecture §5, GLOSSARY "Lifecycle"). Pure: no I/O.

Statuses are the glossary words, stored verbatim. `transition` allows only the guard-free moves
listed in `_ALLOWED`; a move that needs more than a status has its own function
(`acknowledge`: Recorded → Acknowledged, Owner required). Later tickets add Acknowledged →
In Progress and → Resolved.
"""

from enum import StrEnum


class Status(StrEnum):
    DRAFT = "Draft"
    RECORDED = "Recorded"
    ACKNOWLEDGED = "Acknowledged"
    IN_PROGRESS = "In Progress"
    RESOLVED = "Resolved"


class TransitionNotAllowed(ValueError):
    def __init__(self, current: Status, target: Status) -> None:
        super().__init__(f"{current.value} → {target.value} is not allowed")
        self.current = current
        self.target = target


class OwnerRequired(ValueError):
    """Acknowledged means a coordinator set an Owner (GLOSSARY); there is none (AC9.1)."""

    def __init__(self) -> None:
        super().__init__("An Owner is required to acknowledge a request")


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
