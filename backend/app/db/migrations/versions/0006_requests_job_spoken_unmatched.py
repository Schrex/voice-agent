"""requests: job_spoken; job_id nullable (Unmatched)

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-01 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("requests", sa.Column("job_spoken", sa.Text(), nullable=True))
    # Requests recorded before this revision always had a matched Job; keep its name as spoken.
    op.execute(
        "UPDATE requests SET job_spoken = jobs.name FROM jobs WHERE jobs.id = requests.job_id"
    )
    op.alter_column("requests", "job_spoken", nullable=False)
    op.alter_column("requests", "job_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    # Fails (NOT NULL violation) while any Unmatched Request exists: those have no Job to restore.
    op.alter_column("requests", "job_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("requests", "job_spoken")
