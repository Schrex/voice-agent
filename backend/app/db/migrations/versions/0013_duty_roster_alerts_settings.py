"""staff.phone_e164, duty_roster, alerts, settings (ticket #21)

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-01 19:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

E164 = r"~ '^\+[1-9][0-9]{1,14}$'"
ALERT_KINDS = "'today_new', 'callback', 'emergency', 'overdue', 'transfer', 'eod_summary'"


def upgrade() -> None:
    op.add_column("staff", sa.Column("phone_e164", sa.String(length=16), nullable=True))
    op.create_check_constraint(op.f("ck_staff_phone_e164_format"), "staff", f"phone_e164 {E164}")
    op.create_table(
        "duty_roster",
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("on_duty_staff_id", sa.Uuid(), nullable=False),
        sa.Column("backup_staff_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["on_duty_staff_id"],
            ["staff.id"],
            name=op.f("fk_duty_roster_on_duty_staff_id_staff"),
        ),
        sa.ForeignKeyConstraint(
            ["backup_staff_id"],
            ["staff.id"],
            name=op.f("fk_duty_roster_backup_staff_id_staff"),
        ),
        sa.PrimaryKeyConstraint("date", name=op.f("pk_duty_roster")),
    )
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=True),
        sa.Column("call_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("channel", sa.String(length=10), nullable=False),
        sa.Column("to_staff_id", sa.Uuid(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"kind IN ({ALERT_KINDS})", name=op.f("ck_alerts_kind_values")),
        sa.CheckConstraint(
            "channel IN ('sms', 'email', 'popup')", name=op.f("ck_alerts_channel_values")
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed')", name=op.f("ck_alerts_status_values")
        ),
        sa.ForeignKeyConstraint(
            ["request_id"], ["requests.id"], name=op.f("fk_alerts_request_id_requests")
        ),
        sa.ForeignKeyConstraint(["call_id"], ["calls.id"], name=op.f("fk_alerts_call_id_calls")),
        sa.ForeignKeyConstraint(
            ["to_staff_id"], ["staff.id"], name=op.f("fk_alerts_to_staff_id_staff")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alerts")),
    )
    op.create_index(op.f("ix_alerts_request_id"), "alerts", ["request_id"])
    op.create_index(
        "uq_alerts_today_new",
        "alerts",
        ["request_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'today_new'"),
    )
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), server_default="1", nullable=False),
        sa.Column("office_line_e164", sa.String(length=16), nullable=True),
        sa.Column("ack_window_today_min", sa.Integer(), server_default="15", nullable=False),
        sa.Column("ack_window_planned_min", sa.Integer(), server_default="120", nullable=False),
        sa.Column("uninformed_after_min", sa.Integer(), server_default="120", nullable=False),
        sa.Column(
            "timezone", sa.String(length=64), server_default="America/New_York", nullable=False
        ),
        sa.CheckConstraint("id = 1", name=op.f("ck_settings_singleton")),
        sa.CheckConstraint(
            f"office_line_e164 {E164}", name=op.f("ck_settings_office_line_e164_format")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_settings")),
    )
    op.execute("INSERT INTO settings (id) VALUES (1)")


def downgrade() -> None:
    op.drop_table("settings")
    op.drop_index("uq_alerts_today_new", table_name="alerts")
    op.drop_index(op.f("ix_alerts_request_id"), table_name="alerts")
    op.drop_table("alerts")
    op.drop_table("duty_roster")
    op.drop_constraint(op.f("ck_staff_phone_e164_format"), "staff", type_="check")
    op.drop_column("staff", "phone_e164")
