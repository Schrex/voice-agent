"""staff: drop `role`. The pilot has one Staff role (ADR 0006): everyone on the staff list can
do every Coordinator and Admin task.

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-02 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_staff_role"), "staff", type_="check")
    op.drop_column("staff", "role")


def downgrade() -> None:
    # Who was an Admin is not kept: every staff member comes back as a Coordinator.
    op.add_column(
        "staff",
        sa.Column("role", sa.String(length=20), nullable=False, server_default="coordinator"),
    )
    op.alter_column("staff", "role", server_default=None)
    op.create_check_constraint(op.f("ck_staff_role"), "staff", "role IN ('coordinator', 'admin')")
