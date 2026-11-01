"""Call outcome from what happened on the call (architecture §3.4, §5 `calls.outcome`)."""

import pytest

from app.domain.call_outcome import call_outcome


@pytest.mark.parametrize(
    ("rejected", "submitted", "tools_called", "expected"),
    [
        pytest.param(True, False, ["end_call"], "rejected", id="unrostered caller"),
        pytest.param(False, True, ["submit_requests", "end_call"], "submitted", id="submitted"),
        pytest.param(False, False, ["transfer_to_number"], "transferred", id="transferred"),
        pytest.param(False, True, ["transfer_to_number"], "transferred", id="submit then transfer"),
        pytest.param(False, False, ["end_call"], "none", id="nothing happened"),
        pytest.param(False, False, ["submit_requests"], "none", id="submit failed"),
        pytest.param(False, False, [], "none", id="no tool calls"),
    ],
)
def test_call_outcome(
    rejected: bool, submitted: bool, tools_called: list[str], expected: str
) -> None:
    assert call_outcome(rejected=rejected, submitted=submitted, tools_called=tools_called) == (
        expected
    )


@pytest.mark.parametrize(
    ("rejected", "tools_called", "expected"),
    [
        pytest.param(False, ["end_call"], "draft", id="hang-up with a Draft"),
        pytest.param(False, [], "draft", id="dropped call with a Draft"),
        pytest.param(False, ["transfer_to_number"], "transferred", id="transfer outranks Draft"),
        pytest.param(True, [], "rejected", id="rejected outranks Draft"),
    ],
)
def test_call_with_a_draft(rejected: bool, tools_called: list[str], expected: str) -> None:
    outcome = call_outcome(
        rejected=rejected, submitted=False, tools_called=tools_called, drafted=True
    )

    assert outcome == expected
