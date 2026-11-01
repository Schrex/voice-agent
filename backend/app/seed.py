"""Seed command: `uv run python -m app.seed [roster.json]` (defaults to seed/sample_roster.json).

Loads foremen, their phones, jobs, job aliases and staff into DATABASE_URL. Safe to re-run.
"""

import sys
from pathlib import Path

from app.db.session import new_session
from app.services.roster import load_roster_file, seed_roster

DEFAULT_FILE = Path(__file__).resolve().parents[1] / "seed" / "sample_roster.json"


def main(argv: list[str]) -> None:
    path = Path(argv[0]) if argv else DEFAULT_FILE
    roster = load_roster_file(path)
    with new_session() as session:
        seed_roster(session, roster)
    print(
        f"Seeded {len(roster.foremen)} foremen, {len(roster.jobs)} jobs"
        f" and {len(roster.staff)} staff from {path}"
    )


if __name__ == "__main__":
    main(sys.argv[1:])
