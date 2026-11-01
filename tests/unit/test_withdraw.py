"""Withdrawing a Request by phone (ticket #20, spec J4, architecture §5): the agent may resolve a
Request as Withdrawn only before In Progress; from In Progress on it is a Change requested flag.
"""

import pytest

from app.domain.lifecycle import (
    WITHDRAWN_BY_FOREMAN,
    Outcome,
    Status,
    TransitionNotAllowed,
    may_withdraw,
    withdraw,
)


@pytest.mark.parametrize("status", [Status.RECORDED, Status.ACKNOWLEDGED])
def test_the_agent_may_withdraw_before_in_progress(status: Status) -> None:
    assert may_withdraw(status) is True
    assert withdraw(status) == (Status.RESOLVED, Outcome.WITHDRAWN, "Withdrawn by foreman")


@pytest.mark.parametrize("status", [Status.DRAFT, Status.IN_PROGRESS, Status.RESOLVED])
def test_the_agent_may_not_withdraw_in_any_other_status(status: Status) -> None:
    assert may_withdraw(status) is False
    with pytest.raises(TransitionNotAllowed):
        withdraw(status)


def test_the_explanation_is_the_tickets_wording() -> None:
    assert WITHDRAWN_BY_FOREMAN == "Withdrawn by foreman"
