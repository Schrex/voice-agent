"""Request refs as rendered ("R-1042") back to their number. Pure."""

import pytest

from app.domain.ref import parse_ref


@pytest.mark.parametrize(
    ("ref", "number"),
    [
        ("R-1042", 1042),
        ("R-1000", 1000),
        ("R-", None),
        ("r-1042", None),
        ("1042", None),
        ("R-10x", None),
        ("R-1042 ", None),
        ("R-" + "9" * 19, None),
    ],
)
def test_parse_ref(ref: str, number: int | None) -> None:
    assert parse_ref(ref) == number
