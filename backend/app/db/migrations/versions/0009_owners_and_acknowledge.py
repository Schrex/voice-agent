"""owners and acknowledge

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-01 16:48:28.480062
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "owners",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("phone_e164", sa.String(length=16), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_owners")),
        sa.UniqueConstraint("name", name=op.f("uq_owners_name")),
    )
    op.create_table(
        "category_owner_defaults",
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "category IN ('Trucking', 'Equipment', 'Equipment Repair', 'Material', 'Labor',"
            " 'Information', 'Callback', 'Other')",
            name=op.f("ck_category_owner_defaults_category_values"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["owners.id"], name=op.f("fk_category_owner_defaults_owner_id_owners")
        ),
        sa.PrimaryKeyConstraint("category", name=op.f("pk_category_owner_defaults")),
    )
    op.create_index(
        op.f("ix_category_owner_defaults_owner_id"),
        "category_owner_defaults",
        ["owner_id"],
        unique=False,
    )
    op.add_column("requests", sa.Column("owner_id", sa.Integer(), nullable=True))
    op.add_column(
        "requests", sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(op.f("ix_requests_owner_id"), "requests", ["owner_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_requests_owner_id_owners"), "requests", "owners", ["owner_id"], ["id"]
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_requests_owner_id_owners"), "requests", type_="foreignkey")
    op.drop_index(op.f("ix_requests_owner_id"), table_name="requests")
    op.drop_column("requests", "acknowledged_at")
    op.drop_column("requests", "owner_id")
    op.drop_index(op.f("ix_category_owner_defaults_owner_id"), table_name="category_owner_defaults")
    op.drop_table("category_owner_defaults")
    op.drop_table("owners")
