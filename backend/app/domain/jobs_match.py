"""Spoken Job matching (spec J1 step 3, AC1.3/AC1.4; architecture §4.2 `find_jobs`). Pure.

A spoken Job is compared with each Job's name and aliases. Every meaningful word the Foreman
said (filler such as "the" or "job" is dropped) must be found in the name or alias: numbers
exactly, other words allowing a small transcription slip. A Job is a match only if all of its
words pass; otherwise there is no match and the Request is recorded as Unmatched. Nothing is
guessed: a near miss is no match. So a Request reference said instead of a Job ("R-104")
matches no Job: its "r" is in no Job name, even though "104" is.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from rapidfuzz.distance import Indel

MAX_MATCHES = 3

WORD_THRESHOLD = 85
"""Minimum similarity (0-100) of each spoken word to a word of the Job name or alias.
Spec intent is "never guess"; tune only with the real Job list (ticket #13 open question)."""

FILLER_WORDS = frozenset(
    {"a", "an", "at", "by", "for", "in", "job", "jobs", "of", "on", "out", "over", "site", "the"}
)

_WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class JobCandidate:
    """An active Job with its aliases."""

    job_id: int
    name: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class JobMatch:
    job_id: int
    name: str
    score: int
    """0-100; higher is closer."""


def _words(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in FILLER_WORDS]


def _word_similarity(spoken: str, words: Sequence[str]) -> float:
    if spoken.isdigit():
        return 100.0 if spoken in words else 0.0
    return max(
        (Indel.normalized_similarity(spoken, w) * 100 for w in words if not w.isdigit()),
        default=0.0,
    )


def _score(spoken: Sequence[str], label: str) -> float:
    """0 unless every spoken word is found in `label`; then the mean word similarity, nudged
    up when the spoken words cover the whole label (an exact name beats a partial one)."""
    words = _words(label)
    similarities = [_word_similarity(w, words) for w in spoken]
    if not similarities or min(similarities) < WORD_THRESHOLD:
        return 0.0
    mean = sum(similarities) / len(similarities)
    coverage = len(set(spoken) & set(words)) / len(set(words))
    return 0.9 * mean + 0.1 * coverage * 100


def match_jobs(spoken: str, jobs: Iterable[JobCandidate]) -> list[JobMatch]:
    """Up to three Jobs that the spoken words name, closest first; empty means Unmatched."""
    words = _words(spoken)
    if not words:
        return []
    matches = []
    for job in jobs:
        best = max(_score(words, label) for label in (job.name, *job.aliases))
        if best > 0:
            matches.append(JobMatch(job_id=job.job_id, name=job.name, score=round(best)))
    matches.sort(key=lambda m: (-m.score, m.name))
    return matches[:MAX_MATCHES]
