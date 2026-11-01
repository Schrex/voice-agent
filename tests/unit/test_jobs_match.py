"""Spoken Job matching (ticket #13, spec J1 step 3, AC1.3/AC1.4).

A spoken Job is matched against active Job names and aliases. No confident match means no
Job: the Request is recorded as Unmatched and nothing is guessed.
"""

import pytest

from app.domain.jobs_match import JobCandidate, match_jobs

JOBS = [
    JobCandidate(job_id=12, name="Penfield Sewer Replacement", aliases=("Penfield sewer",)),
    JobCandidate(job_id=14, name="Route 104 Widening", aliases=("Route 104", "104 job")),
    JobCandidate(job_id=21, name="Route 140 Culvert", aliases=()),
    JobCandidate(job_id=30, name="Webster Park Drainage", aliases=("the park job",)),
]


def matched_names(query: str) -> list[str]:
    return [m.name for m in match_jobs(query, JOBS)]


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        # The canonical name, however it is cased or punctuated.
        ("Route 104 Widening", "Route 104 Widening"),
        ("ROUTE 104 WIDENING.", "Route 104 Widening"),
        # Aliases read back as the canonical name (AC1.3).
        ("Route 104", "Route 104 Widening"),
        ("the 104 job", "Route 104 Widening"),
        ("104", "Route 104 Widening"),
        ("Penfield sewer", "Penfield Sewer Replacement"),
        ("the park job", "Webster Park Drainage"),
        # Part of a name, with filler words around it.
        ("the Penfield job", "Penfield Sewer Replacement"),
        ("over at Penfield", "Penfield Sewer Replacement"),
        ("Webster Park", "Webster Park Drainage"),
        # Small transcription slips in a word.
        ("the Penfeld job", "Penfield Sewer Replacement"),
        ("Webstr Park", "Webster Park Drainage"),
        # A near miss is a different word, not a slip: no guess.
        ("the Penfold job", None),
        ("Webber Park", None),
        # Numbers must match exactly: 104 is not 140, and 105 is no Job.
        ("Route 140", "Route 140 Culvert"),
        ("Route 105", None),
        ("105", None),
        # A Request reference is not a Job ("R-104" vs "Route 104").
        ("R-104", None),
        ("r104", None),
        ("R 104", None),
        ("reference R-104", None),
        # Nothing like any Job (AC1.4).
        ("the Smith pit", None),
        ("Fairport", None),
        ("", None),
        ("the job", None),
    ],
)
def test_spoken_job_matches_one_job_or_none(spoken: str, expected: str | None) -> None:
    assert matched_names(spoken) == ([] if expected is None else [expected])


def test_words_shared_by_several_jobs_return_each_so_the_agent_asks_which() -> None:
    assert sorted(matched_names("the Route job")) == ["Route 104 Widening", "Route 140 Culvert"]


def test_a_match_carries_the_job_id_and_a_score() -> None:
    [match] = match_jobs("Route 104", JOBS)
    assert match.job_id == 14
    assert match.name == "Route 104 Widening"
    assert 0 < match.score <= 100


def test_the_exact_name_ranks_above_a_partial_match() -> None:
    jobs = [
        JobCandidate(job_id=1, name="Penfield Sewer Replacement", aliases=()),
        JobCandidate(job_id=2, name="Penfield", aliases=()),
    ]
    assert [m.job_id for m in match_jobs("Penfield", jobs)] == [2, 1]


def test_at_most_three_matches() -> None:
    jobs = [JobCandidate(job_id=i, name=f"Main Street Phase {i}", aliases=()) for i in range(1, 6)]
    assert len(match_jobs("Main Street", jobs)) == 3


def test_a_job_appears_once_even_when_name_and_alias_both_match() -> None:
    assert matched_names("Route 104 Widening") == ["Route 104 Widening"]
