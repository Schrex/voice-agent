"""Draft from an unfinished call (spec §5 "Draft", AC1.8, AC5.2; architecture §3.4 step 4).

Pure: no I/O. Turns the post-call analysis (ElevenLabs data collection) into the fields of a
Draft. The spoken Job is matched later, by the same matcher as `find_jobs`.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

# The data-collection field ids configured in backend/agent/agent.json
# (`platform_settings.data_collection`). Keep the two in step.
DATA_COLLECTION_FIELDS = (
    "need",
    "job_spoken",
    "category",
    "quantity",
    "unit",
    "needed_by_spoken",
)
FALLBACK_CATEGORY = "Other"


@dataclass(frozen=True)
class DraftItem:
    """One need the call analysis found, as the Foreman said it."""

    need: str
    category: str
    job_spoken: str | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    needed_by_spoken: str | None = None


def _value(results: Mapping[str, Any], field: str) -> Any:
    result = results.get(field)
    return result.get("value") if isinstance(result, Mapping) else None


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _quantity(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        quantity = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    return quantity if quantity.is_finite() else None


def draft_from_data_collection(
    results: Mapping[str, Any], *, categories: Collection[str]
) -> DraftItem | None:
    """The Draft the analysis describes, or None when it found no need.

    `results` is `analysis.data_collection_results` (`{field_id: {value, ...}}`). A category
    outside `categories` (or missing) becomes "Other"; any other missing field stays unknown.
    """
    need = _text(_value(results, "need"))
    if need is None:
        return None
    category = _text(_value(results, "category"))
    if category is None or category not in categories:
        category = FALLBACK_CATEGORY
    return DraftItem(
        need=need,
        category=category,
        job_spoken=_text(_value(results, "job_spoken")),
        quantity=_quantity(_value(results, "quantity")),
        unit=_text(_value(results, "unit")),
        needed_by_spoken=_text(_value(results, "needed_by_spoken")),
    )
