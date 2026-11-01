"""requests: outcome, explanation, resolved_at (ticket #12)

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-01 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("requests", sa.Column("outcome", sa.String(length=32), nullable=True))
    op.add_column("requests", sa.Column("explanation", sa.Text(), nullable=True))
    op.add_column("requests", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        op.f("ck_requests_outcome_values"),
        "requests",
        "outcome IN ('Fulfilled', 'Partially Fulfilled', 'Denied', 'Withdrawn')",
    )
    op.create_check_constraint(
        op.f("ck_requests_resolved_has_outcome"),
        "requests",
        "status <> 'Resolved' OR (outcome IS NOT NULL AND explanation IS NOT NULL"
        " AND resolved_at IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_requests_resolved_has_outcome"), "requests", type_="check")
    op.drop_constraint(op.f("ck_requests_outcome_values"), "requests", type_="check")
    op.drop_column("requests", "resolved_at")
    op.drop_column("requests", "explanation")
    op.drop_column("requests", "outcome")
