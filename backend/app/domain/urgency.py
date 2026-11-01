"""Urgency (GLOSSARY "Urgency"). Pure: no I/O.

Members are declared most urgent first; the queue sorts by this order (spec J9).
Inferring urgency from needed-by and keywords comes with ticket #14.
"""

from enum import StrEnum


class Urgency(StrEnum):
    EMERGENCY = "Emergency"
    TODAY = "Today"
    PLANNED = "Planned"


def rank(urgency: Urgency) -> int:
    """0 for the most urgent; the queue shows lower ranks first."""
    return list(Urgency).index(urgency)
