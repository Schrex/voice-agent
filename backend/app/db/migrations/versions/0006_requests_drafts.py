"""drafts: requests.job_id and recorded_at nullable, requests.job_spoken

A Draft (ticket #28) may name a Job that matches no active Job (job kept as spoken) and has not
been Recorded yet. Ticket #13 needs the same `job_id`/`job_spoken` change for Unmatched Jobs, so
these statements are written to be safe if #13's migration has already made them.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-01 18:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE requests ALTER COLUMN job_id DROP NOT NULL")
    op.execute("ALTER TABLE requests ADD COLUMN IF NOT EXISTS job_spoken TEXT")
    op.execute("ALTER TABLE requests ALTER COLUMN recorded_at DROP NOT NULL")


def downgrade() -> None:
    # Fails while any Request has no Job or is still a Draft; resolve those first.
    op.execute("ALTER TABLE requests ALTER COLUMN recorded_at SET NOT NULL")
    op.execute("ALTER TABLE requests DROP COLUMN IF EXISTS job_spoken")
    op.execute("ALTER TABLE requests ALTER COLUMN job_id SET NOT NULL")
