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


@pytest.mark.parametrize(
    ("rejected", "submitted", "drafted", "tools_called", "expected"),
    [
        pytest.param(False, False, False, ["end_call"], "status_only", id="only a lookup"),
        pytest.param(False, True, False, [], "submitted", id="submitted outranks a lookup"),
        pytest.param(False, False, True, [], "draft", id="Draft outranks a lookup"),
        pytest.param(
            False, False, False, ["transfer_to_number"], "transferred", id="transfer outranks"
        ),
        pytest.param(True, False, False, [], "rejected", id="rejected outranks a lookup"),
    ],
)
def test_call_with_a_status_lookup(
    rejected: bool, submitted: bool, drafted: bool, tools_called: list[str], expected: str
) -> None:
    outcome = call_outcome(
        rejected=rejected,
        submitted=submitted,
        tools_called=tools_called,
        drafted=drafted,
        looked_up=True,
    )

    assert outcome == expected
