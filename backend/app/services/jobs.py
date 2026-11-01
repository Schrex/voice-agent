"""Job lookup for the agent's `find_jobs` tool (architecture §4.2). Read-only."""

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Job
from app.domain.jobs_match import JobCandidate, JobMatch, match_jobs


def find_jobs(session: Session, spoken: str) -> list[JobMatch]:
    """Up to three active Jobs matching what the Foreman said; empty means Unmatched."""
    jobs = session.scalars(select(Job).where(Job.active).options(selectinload(Job.aliases)))
    candidates = [
        JobCandidate(job_id=job.id, name=job.name, aliases=tuple(a.alias for a in job.aliases))
        for job in jobs
    ]
    return match_jobs(spoken, candidates)
