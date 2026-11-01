"""Draft fields from the call analysis, and exact Job matching (ticket #28)."""

from decimal import Decimal
from typing import Any

import pytest

from app.domain.draft import DraftItem, draft_from_data_collection, exact_job_match

CATEGORIES = ("Trucking", "Equipment", "Other")


def _results(**values: Any) -> dict[str, Any]:
    return {k: {"data_collection_id": k, "value": v, "rationale": "r"} for k, v in values.items()}


def test_all_fields_found() -> None:
    results = _results(
        need=" tri-axle dump trucks ",
        job_spoken="Route 104",
        category="Trucking",
        quantity=2,
        unit="trucks",
        needed_by_spoken="tomorrow at 7 AM",
    )

    assert draft_from_data_collection(results, categories=CATEGORIES) == DraftItem(
        need="tri-axle dump trucks",
        category="Trucking",
        job_spoken="Route 104",
        quantity=Decimal(2),
        unit="trucks",
        needed_by_spoken="tomorrow at 7 AM",
    )


@pytest.mark.parametrize(
    "results",
    [
        pytest.param({}, id="nothing collected"),
        pytest.param(_results(need=None, category="Trucking"), id="need null"),
        pytest.param(_results(need="  ", category="Trucking"), id="need blank"),
        pytest.param(_results(need=3), id="need not text"),
        pytest.param({"need": "trucks"}, id="malformed result"),
    ],
)
def test_no_need_means_no_draft(results: dict[str, Any]) -> None:
    assert draft_from_data_collection(results, categories=CATEGORIES) is None


@pytest.mark.parametrize("category", [None, "", "Snacks", "trucking"])
def test_missing_or_unknown_category_is_other(category: Any) -> None:
    draft = draft_from_data_collection(
        _results(need="something", category=category), categories=CATEGORIES
    )

    assert draft is not None and draft.category == "Other"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (2, Decimal(2)),
        (2.5, Decimal("2.5")),
        ("3", Decimal(3)),
        (None, None),
        ("a couple", None),
        (True, None),
        ("NaN", None),
    ],
)
def test_quantity(value: Any, expected: Decimal | None) -> None:
    draft = draft_from_data_collection(
        _results(need="stone", quantity=value), categories=CATEGORIES
    )

    assert draft is not None and draft.quantity == expected


def test_missing_optional_fields_stay_unknown() -> None:
    draft = draft_from_data_collection(_results(need="stone", unit=""), categories=CATEGORIES)

    assert draft == DraftItem(need="stone", category="Other")


JOBS = [
    (14, ["Route 104 Widening", "Route 104", "104 job"]),
    (12, ["Penfield Sewer Replacement", "Penfield sewer"]),
    (20, ["North Yard"]),
    (21, ["North  yard annex", "north yard"]),
]


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        pytest.param("Route 104 Widening", 14, id="name"),
        pytest.param("route 104", 14, id="alias any case"),
        pytest.param("  Penfield   SEWER ", 12, id="spacing"),
        pytest.param("104", None, id="partial is no match"),
        pytest.param("the Penfield job", None, id="paraphrase is no match"),
        pytest.param("R-104", None, id="ref-like is no match"),
        pytest.param("north yard", None, id="ambiguous across Jobs"),
        pytest.param(None, None, id="not said"),
    ],
)
def test_exact_job_match(spoken: str | None, expected: int | None) -> None:
    assert exact_job_match(spoken, JOBS) == expected
