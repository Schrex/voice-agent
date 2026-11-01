"""Wording of the incoming-transfer SMS and pop-up (ticket #25; spec J5 step 2, verbatim):
"Incoming transfer: <foreman>, <job>, about: <need or 'not stated'>"."""

from app.domain.sms_text import transfer_text


def test_names_the_foreman_the_job_and_the_need() -> None:
    assert (
        transfer_text(
            foreman="Dale Kramer",
            job="Route 104 Widening",
            job_spoken="the 104 job",
            about="tri-axle dump trucks",
        )
        == "Incoming transfer: Dale Kramer, Route 104 Widening, about: tri-axle dump trucks"
    )


def test_no_need_said_is_not_stated() -> None:
    assert (
        transfer_text(
            foreman="Dale Kramer", job="Route 104 Widening", job_spoken="the 104 job", about=None
        )
        == "Incoming transfer: Dale Kramer, Route 104 Widening, about: not stated"
    )


def test_a_blank_need_is_not_stated() -> None:
    assert transfer_text(foreman="Dale Kramer", job=None, job_spoken=None, about="  ").endswith(
        "about: not stated"
    )


def test_an_unmatched_job_is_quoted_as_said() -> None:
    assert (
        transfer_text(foreman="Dale Kramer", job=None, job_spoken="the quarry", about="a loader")
        == "Incoming transfer: Dale Kramer, “the quarry” (Unmatched), about: a loader"
    )


def test_no_job_said_is_not_stated() -> None:
    assert (
        transfer_text(foreman="Dale Kramer", job=None, job_spoken=None, about=None)
        == "Incoming transfer: Dale Kramer, not stated, about: not stated"
    )
