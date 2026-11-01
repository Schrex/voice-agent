"""requests: merged_into_id (ticket #33)

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-01 19:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("requests", sa.Column("merged_into_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_requests_merged_into_id_requests"),
        "requests",
        "requests",
        ["merged_into_id"],
        ["id"],
    )
    op.create_index(op.f("ix_requests_merged_into_id"), "requests", ["merged_into_id"])
    op.create_check_constraint(
        op.f("ck_requests_merged_is_resolved"),
        "requests",
        "merged_into_id IS NULL OR (status = 'Resolved' AND merged_into_id <> id)",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_requests_merged_is_resolved"), "requests", type_="check")
    op.drop_index(op.f("ix_requests_merged_into_id"), table_name="requests")
    op.drop_constraint(op.f("fk_requests_merged_into_id_requests"), "requests", type_="foreignkey")
    op.drop_column("requests", "merged_into_id")
