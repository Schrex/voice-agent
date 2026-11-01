"""requests.ack_due_at, one overdue alert per Request (ticket #22)

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-01 21:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("requests", sa.Column("ack_due_at", sa.DateTime(timezone=True), nullable=True))
    # Requests already Recorded get the window they would have had (settings, else §4 defaults).
    op.execute(
        """
        UPDATE requests SET ack_due_at = recorded_at + make_interval(mins => CASE urgency
            WHEN 'Today' THEN COALESCE((SELECT ack_window_today_min FROM settings), 15)
            ELSE COALESCE((SELECT ack_window_planned_min FROM settings), 120) END)
        WHERE recorded_at IS NOT NULL AND urgency IN ('Today', 'Planned')
        """
    )
    op.create_index(
        "uq_alerts_overdue",
        "alerts",
        ["request_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'overdue'"),
    )


def downgrade() -> None:
    op.drop_index("uq_alerts_overdue", table_name="alerts")
    op.drop_column("requests", "ack_due_at")
