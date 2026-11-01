"""alerts.summary_date: one end-of-day summary per Coordinator per day (ticket #23)

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-01 20:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("alerts", sa.Column("summary_date", sa.Date(), nullable=True))
    op.create_check_constraint(
        op.f("ck_alerts_summary_date_only_for_eod_summary"),
        "alerts",
        "(kind = 'eod_summary') = (summary_date IS NOT NULL AND to_staff_id IS NOT NULL)",
    )
    op.create_index(
        "uq_alerts_eod_summary",
        "alerts",
        ["to_staff_id", "summary_date"],
        unique=True,
        postgresql_where=sa.text("kind = 'eod_summary'"),
    )


def downgrade() -> None:
    op.drop_index("uq_alerts_eod_summary", table_name="alerts")
    op.drop_constraint(op.f("ck_alerts_summary_date_only_for_eod_summary"), "alerts", type_="check")
    op.drop_column("alerts", "summary_date")
