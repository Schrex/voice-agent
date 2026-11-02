"""staff: `removed_at`. An admin removes a person from the staff list (they lose dashboard access
at once); the row stays, so the audit history keeps their name. Adding them again clears it.

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-02 19:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("staff", sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("staff", "removed_at")
