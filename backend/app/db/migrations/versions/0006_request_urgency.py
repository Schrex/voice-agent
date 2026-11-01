"""request urgency

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-01 16:28:44.189300
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("requests", sa.Column("urgency", sa.String(length=16), nullable=True))
    # Autogenerate does not emit CHECK constraints; the name follows the model's convention.
    op.create_check_constraint(
        op.f("ck_requests_urgency_values"),
        "requests",
        "urgency IN ('Emergency', 'Today', 'Planned')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_requests_urgency_values"), "requests", type_="check")
    op.drop_column("requests", "urgency")
