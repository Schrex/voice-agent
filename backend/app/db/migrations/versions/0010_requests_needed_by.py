"""requests: needed_by (the spoken needed-by resolved to a time)

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-01 19:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("requests", sa.Column("needed_by", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("requests", "needed_by")
