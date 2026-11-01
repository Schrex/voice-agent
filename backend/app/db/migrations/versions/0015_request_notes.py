"""request_notes (ticket #17)

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
    op.create_table(
        "request_notes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("author_type", sa.String(length=10), nullable=False),
        sa.Column("author_id", sa.String(length=64), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("urgent", sa.Boolean(), server_default="false", nullable=False),
        sa.CheckConstraint(
            "author_type IN ('agent', 'staff', 'system')",
            name=op.f("ck_request_notes_author_type_values"),
        ),
        sa.ForeignKeyConstraint(
            ["request_id"], ["requests.id"], name=op.f("fk_request_notes_request_id_requests")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_request_notes")),
    )
    op.create_index(op.f("ix_request_notes_request_id"), "request_notes", ["request_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_request_notes_request_id"), table_name="request_notes")
    op.drop_table("request_notes")
