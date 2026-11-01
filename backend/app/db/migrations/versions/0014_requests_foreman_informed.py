"""requests: foreman_informed_at (ticket #32)

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-01 19:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "requests", sa.Column("foreman_informed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_requests_informed_only_when_resolved"),
        "requests",
        "foreman_informed_at IS NULL OR status = 'Resolved'",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_requests_informed_only_when_resolved"), "requests", type_="check")
    op.drop_column("requests", "foreman_informed_at")
