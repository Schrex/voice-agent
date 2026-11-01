"""drafts: requests.recorded_at nullable

A Draft (ticket #28) has not been Recorded yet; `recorded_at` is set when it is promoted.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-01 18:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "requests", "recorded_at", existing_type=sa.DateTime(timezone=True), nullable=True
    )


def downgrade() -> None:
    # Fails (NOT NULL violation) while any Draft exists: it has no time it was Recorded.
    op.alter_column(
        "requests", "recorded_at", existing_type=sa.DateTime(timezone=True), nullable=False
    )
