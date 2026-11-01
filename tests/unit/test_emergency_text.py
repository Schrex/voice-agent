"""Emergency SMS / pop-up wording (ticket #26; spec J6 step 3, verbatim template)."""

import pytest

from app.domain.sms_text import emergency_text


@pytest.mark.parametrize(
    ("job", "job_spoken", "summary", "expected"),
    [
        pytest.param(
            "Route 104 Widening",
            "the 104 job",
            "we hit a gas line",
            "EMERGENCY call from Dale Kramer, Route 104 Widening: we hit a gas line",
            id="matched Job by name",
        ),
        pytest.param(
            None,
            "the Fairport job",
            "trench collapse",
            "EMERGENCY call from Dale Kramer, “the Fairport job” (Unmatched): trench collapse",
            id="Unmatched Job quoted as said",
        ),
        pytest.param(
            None,
            None,
            "there's a gas leak",
            "EMERGENCY call from Dale Kramer, not stated: there's a gas leak",
            id="no Job said",
        ),
        pytest.param(
            None,
            "  ",
            "  fire in the shed ",
            "EMERGENCY call from Dale Kramer, not stated: fire in the shed",
            id="blank Job, summary trimmed",
        ),
    ],
)
def test_emergency_text_follows_the_spec_template(
    job: str | None, job_spoken: str | None, summary: str, expected: str
) -> None:
    assert (
        emergency_text(foreman="Dale Kramer", job=job, job_spoken=job_spoken, summary=summary)
        == expected
    )
