"""Request lifecycle guards (architecture §5, GLOSSARY "Lifecycle"). Pure: no I/O.

Statuses are the glossary words, stored verbatim. Only the transitions listed in `_ALLOWED`
may happen; later tickets add Recorded → Acknowledged, Acknowledged → In Progress and
→ Resolved, each with its own guard.
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


_ALLOWED: frozenset[tuple[Status, Status]] = frozenset({(Status.DRAFT, Status.RECORDED)})


def transition(current: Status, target: Status) -> Status:
    """Return `target` if the request may move there from `current`; else raise."""
    if (current, target) not in _ALLOWED:
        raise TransitionNotAllowed(current, target)
    return target
