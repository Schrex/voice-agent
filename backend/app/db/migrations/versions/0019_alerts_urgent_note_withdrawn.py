"""alerts: `urgent_note` and `withdrawn` kinds (review fix S1; #21 "urgent notes (17) and
withdrawals (20) text too"), one `withdrawn` alert per Request.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-02 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = "'today_new', 'callback', 'emergency', 'overdue', 'transfer', 'eod_summary'"
NEW_KINDS = f"{OLD_KINDS}, 'urgent_note', 'withdrawn'"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_alerts_kind_values"), "alerts", type_="check")
    op.create_check_constraint(op.f("ck_alerts_kind_values"), "alerts", f"kind IN ({NEW_KINDS})")
    op.create_index(
        "uq_alerts_withdrawn",
        "alerts",
        ["request_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'withdrawn'"),
    )


def downgrade() -> None:
    op.drop_index("uq_alerts_withdrawn", table_name="alerts")
    op.execute("DELETE FROM alerts WHERE kind IN ('urgent_note', 'withdrawn')")
    op.drop_constraint(op.f("ck_alerts_kind_values"), "alerts", type_="check")
    op.create_check_constraint(op.f("ck_alerts_kind_values"), "alerts", f"kind IN ({OLD_KINDS})")
