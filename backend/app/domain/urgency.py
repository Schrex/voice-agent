"""Urgency (GLOSSARY "Urgency"). Pure: no I/O.

Members are declared most urgent first; the queue sorts by this order (spec J9).
Spec §5: "AI infers from needed-by and keywords": the needed-by gives Today or Planned
(`timeparse.urgency_for`); work-stopped keywords make it Today when no needed-by does.
"""

import re
from enum import StrEnum


class Urgency(StrEnum):
    EMERGENCY = "Emergency"
    TODAY = "Today"
    PLANNED = "Planned"


# Spec §5 Today = "needed today or work stopped".
WORK_STOPPED = re.compile(r"\b(stopped|shut down|waiting on it)\b", re.IGNORECASE)


def rank(urgency: Urgency) -> int:
    """0 for the most urgent; the queue shows lower ranks first."""
    return list(Urgency).index(urgency)


def infer_urgency(from_needed_by: Urgency | None, said: str) -> Urgency | None:
    """The needed-by's Urgency when it gave one; else Today when the Foreman's words say work
    is stopped ("stopped", "shut down", "waiting on it"); else unknown (None)."""
    if from_needed_by is not None:
        return from_needed_by
    return Urgency.TODAY if WORK_STOPPED.search(said) else None
