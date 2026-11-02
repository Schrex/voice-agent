"""SQLAlchemy models (architecture §5). Schema changes go through an Alembic migration."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    MetaData,
    Numeric,
    Sequence,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.domain.lifecycle import Outcome, Status
from app.domain.urgency import Urgency

# Stable constraint names so migrations can reference them.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


E164_MATCH = r"~ '^\+[1-9][0-9]{1,14}$'"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Foreman(Base):
    __tablename__ = "foremen"

    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(default=True, server_default="true")

    phones: Mapped[list["ForemanPhone"]] = relationship(back_populates="foreman")


class ForemanPhone(Base):
    """A rostered number. Unique across all foremen: one number identifies one Foreman."""

    __tablename__ = "foreman_phones"
    __table_args__ = (CheckConstraint(r"e164 ~ '^\+[1-9][0-9]{1,14}$'", name="e164_format"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    foreman_id: Mapped[int] = mapped_column(ForeignKey("foremen.id"), index=True)
    e164: Mapped[str] = mapped_column(String(16), unique=True)

    foreman: Mapped[Foreman] = relationship(back_populates="phones")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(default=True, server_default="true")

    aliases: Mapped[list["JobAlias"]] = relationship(back_populates="job")


class JobAlias(Base):
    __tablename__ = "job_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    alias: Mapped[str] = mapped_column(String(200))

    job: Mapped[Job] = relationship(back_populates="aliases")


CALL_OUTCOMES = (
    "submitted",
    "draft",
    "transferred",
    "emergency",
    "rejected",
    "status_only",
    "none",
)


class Call(Base):
    """One ElevenLabs conversation. Binds the conversation to the verified Foreman (ADR 0004).

    `foreman_id` is null for an unrostered caller (outcome `rejected`). `outcome` of a rostered
    call stays null until the post-call webhook sets it. The post-call columns (`ended_at`,
    `duration_s`, `termination_reason`, `transcript`, `summary`) are null until then;
    `ended_at` set means the post-call record has been stored.
    """

    __tablename__ = "calls"
    __table_args__ = (
        CheckConstraint(
            "outcome IN (" + ", ".join(f"'{o}'" for o in CALL_OUTCOMES) + ")",
            name="outcome_values",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(128), unique=True)
    call_sid: Mapped[str | None] = mapped_column(String(64), index=True)
    caller_e164: Mapped[str] = mapped_column(String(32))
    foreman_id: Mapped[int | None] = mapped_column(ForeignKey("foremen.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(String(20))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_s: Mapped[int | None]
    termination_reason: Mapped[str | None] = mapped_column(Text)
    # The ElevenLabs transcript turns as delivered (role, message, time_in_call_secs, tool calls).
    transcript: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    summary: Mapped[str | None] = mapped_column(Text)

    foreman: Mapped[Foreman | None] = relationship()


def _one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


# GLOSSARY "Category", verbatim.
CATEGORIES = (
    "Trucking",
    "Equipment",
    "Equipment Repair",
    "Material",
    "Labor",
    "Information",
    "Callback",
    "Other",
)
REQUEST_STATUSES = tuple(s.value for s in Status)


class Owner(Base):
    """The person or team responsible for fulfilling a Request (GLOSSARY "Owner")."""

    __tablename__ = "owners"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    phone_e164: Mapped[str | None] = mapped_column(String(16))
    email: Mapped[str | None] = mapped_column(String(320))


class CategoryOwnerDefault(Base):
    """The Owner a coordinator is offered first when acknowledging a Request of `category`."""

    __tablename__ = "category_owner_defaults"
    __table_args__ = (CheckConstraint(_one_of("category", CATEGORIES), name="category_values"),)

    category: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id"), index=True)


REQUEST_SOURCES = ("ai_call", "coordinator")
URGENCIES = tuple(u.value for u in Urgency)
OUTCOMES = tuple(o.value for o in Outcome)

# References start at 1000 and are rendered "R-1000" (architecture §5).
request_ref_seq = Sequence("request_ref_seq", start=1000, metadata=Base.metadata)


class Request(Base):
    """One actionable need from a Foreman, tied to one Job (or Unmatched). Never hard-deleted."""

    __tablename__ = "requests"
    __table_args__ = (
        CheckConstraint(_one_of("category", CATEGORIES), name="category_values"),
        CheckConstraint(_one_of("status", REQUEST_STATUSES), name="status_values"),
        CheckConstraint(_one_of("source", REQUEST_SOURCES), name="source_values"),
        CheckConstraint(_one_of("urgency", URGENCIES), name="urgency_values"),
        CheckConstraint(_one_of("outcome", OUTCOMES), name="outcome_values"),
        CheckConstraint(
            "status <> 'Resolved' OR (outcome IS NOT NULL AND explanation IS NOT NULL"
            " AND resolved_at IS NOT NULL)",
            name="resolved_has_outcome",
        ),
        CheckConstraint(
            "merged_into_id IS NULL OR (status = 'Resolved' AND merged_into_id <> id)",
            name="merged_is_resolved",
        ),
        CheckConstraint(
            "foreman_informed_at IS NULL OR status = 'Resolved'", name="informed_only_when_resolved"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[int] = mapped_column(
        request_ref_seq, server_default=request_ref_seq.next_value(), unique=True
    )
    foreman_id: Mapped[int] = mapped_column(ForeignKey("foremen.id"), index=True)
    # Null = Unmatched: no confident match for what the Foreman said (spec J1 step 3).
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), index=True)
    # The Job as the Foreman said it, kept whether or not it matched.
    job_spoken: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(32))
    need: Mapped[str] = mapped_column(Text)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric)
    unit: Mapped[str | None] = mapped_column(String(64))
    # Needed-by as the Foreman said it; null when they could not say (needed-by unknown).
    needed_by_spoken: Mapped[str | None] = mapped_column(Text)
    # `needed_by_spoken` resolved to a time (app.domain.timeparse); null when unknown, not
    # understood, or only a day was said.
    needed_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set from the resolved needed-by's day; null when needed-by is unknown or not understood.
    # The queue shows nulls last.
    urgency: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(20))
    # When the Request became Recorded; null while it is a Draft.
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set together when a coordinator acknowledges (ticket #11); null while Recorded.
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("owners.id"), index=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set together when a coordinator resolves (ticket #12); null until Resolved.
    outcome: Mapped[str | None] = mapped_column(String(32))
    explanation: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when a coordinator merges this duplicate into another Request (ticket #33); this one
    # is then Resolved and a status lookup of its ref reports the other one.
    merged_into_id: Mapped[int | None] = mapped_column(ForeignKey("requests.id"), index=True)
    # Set when a coordinator marks Foreman Informed (ticket #32); null = not marked. A Resolved
    # Request not marked within the threshold shows Uninformed (app.domain.sla; derived).
    foreman_informed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # When it must be Acknowledged by: Recorded time + the ack window of its Urgency (ticket
    # #22, app.domain.sla.ack_due_at); null while a Draft, and for Emergency or no Urgency.
    # Still Recorded after it = Overdue (derived).
    ack_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when the Foreman asks by phone to change a Request at or after In Progress (spec J4,
    # ticket #19): nothing was changed, a note says what was asked; the queue flags it.
    change_requested: Mapped[bool] = mapped_column(default=False, server_default="false")

    @property
    def ref_display(self) -> str:
        return f"R-{self.ref}"


ACTOR_TYPES = ("agent", "staff", "system")


class RequestEvent(Base):
    """Audit log row, written in the same transaction as every Request change.

    `before`/`after` hold only the changed fields; `before` is null when the Request is created.
    `actor_id` is null for the agent (the Foreman is on the Request) and for the system.
    """

    __tablename__ = "request_events"
    __table_args__ = (
        CheckConstraint(_one_of("actor_type", ACTOR_TYPES), name="actor_type_values"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor_type: Mapped[str] = mapped_column(String(10))
    actor_id: Mapped[str | None] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(40))
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class RequestNote(Base):
    """A note on a Request (ticket #17), optionally urgent; appended, never edited.

    `author_type` uses the audit actor types; `author_id` is null for the agent (the Foreman is
    on the Request) and the staff id for a coordinator. Adding one also writes a `note_added`
    event in the same transaction.
    """

    __tablename__ = "request_notes"
    __table_args__ = (
        CheckConstraint(_one_of("author_type", ACTOR_TYPES), name="author_type_values"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    author_type: Mapped[str] = mapped_column(String(10))
    author_id: Mapped[str | None] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text)
    urgent: Mapped[bool] = mapped_column(default=False, server_default="false")


CALL_REQUEST_RELATIONS = ("created", "looked_up", "amended")


class CallRequest(Base):
    """Links a Call to a Request it created, looked up or amended."""

    __tablename__ = "call_requests"
    __table_args__ = (
        CheckConstraint(_one_of("relation", CALL_REQUEST_RELATIONS), name="relation_values"),
    )

    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id"), primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id"), primary_key=True, index=True)
    relation: Mapped[str] = mapped_column(String(16), primary_key=True)


class Staff(Base):
    """A dashboard user. `id` is the Supabase Auth user id (the access token's `sub`)."""

    __tablename__ = "staff"
    __table_args__ = (
        CheckConstraint("role IN ('coordinator', 'admin')", name="role"),
        CheckConstraint(rf"phone_e164 {E164_MATCH}", name="phone_e164_format"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(20))
    # Where alert SMS reach them (ticket #21); null = no texts possible.
    phone_e164: Mapped[str | None] = mapped_column(String(16))


class DutyRoster(Base):
    """Who is the on-duty Coordinator (and backup) on a New York calendar date."""

    __tablename__ = "duty_roster"

    day: Mapped[date] = mapped_column("date", Date, primary_key=True)
    on_duty_staff_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("staff.id"))
    backup_staff_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff.id"))

    on_duty: Mapped[Staff] = relationship(foreign_keys=[on_duty_staff_id])
    backup: Mapped[Staff | None] = relationship(foreign_keys=[backup_staff_id])


ALERT_KINDS = (
    "today_new",
    "callback",
    "emergency",
    "overdue",
    "transfer",
    "eod_summary",
    "urgent_note",
    "withdrawn",
)
ALERT_CHANNELS = ("sms", "email", "popup")
ALERT_STATUSES = ("pending", "sent", "failed")


class Alert(Base):
    """One alert sent (or attempted) to staff; the record that makes sending idempotent.

    `status` pending (being sent), sent (provider accepted it; `provider_id` set) or failed
    (`detail` says why, e.g. nobody on duty). `sent_at` is when it was attempted.
    One `today_new` alert per Request at most (`uq_alerts_today_new`) and one `overdue` alert
    (`uq_alerts_overdue`, ticket #22) and one `withdrawn` alert (`uq_alerts_withdrawn`); one
    `urgent_note` alert per urgent phone note; one `eod_summary` per Coordinator per New York day
    (`summary_date`, `uq_alerts_eod_summary`, ticket #23).
    """

    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint(_one_of("kind", ALERT_KINDS), name="kind_values"),
        CheckConstraint(_one_of("channel", ALERT_CHANNELS), name="channel_values"),
        CheckConstraint(_one_of("status", ALERT_STATUSES), name="status_values"),
        Index(
            "uq_alerts_today_new",
            "request_id",
            unique=True,
            postgresql_where=text("kind = 'today_new'"),
        ),
        Index(
            "uq_alerts_overdue",
            "request_id",
            unique=True,
            postgresql_where=text("kind = 'overdue'"),
        ),
        Index(
            "uq_alerts_withdrawn",
            "request_id",
            unique=True,
            postgresql_where=text("kind = 'withdrawn'"),
        ),
        CheckConstraint(
            "(kind = 'eod_summary') = (summary_date IS NOT NULL AND to_staff_id IS NOT NULL)",
            name="summary_date_only_for_eod_summary",
        ),
        Index(
            "uq_alerts_eod_summary",
            "to_staff_id",
            "summary_date",
            unique=True,
            postgresql_where=text("kind = 'eod_summary'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int | None] = mapped_column(ForeignKey("requests.id"), index=True)
    call_id: Mapped[int | None] = mapped_column(ForeignKey("calls.id"))
    kind: Mapped[str] = mapped_column(String(20))
    channel: Mapped[str] = mapped_column(String(10))
    to_staff_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff.id"))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provider_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(10))
    detail: Mapped[str | None] = mapped_column(Text)
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The New York day an `eod_summary` alert summarizes; null for every other kind.
    summary_date: Mapped[date | None] = mapped_column(Date)


class Settings(Base):
    """Singleton (id = 1) of office-wide settings (architecture §5); defaults set by migration."""

    __tablename__ = "settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
        CheckConstraint(rf"office_line_e164 {E164_MATCH}", name="office_line_e164_format"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, server_default="1")
    office_line_e164: Mapped[str | None] = mapped_column(String(16))
    ack_window_today_min: Mapped[int] = mapped_column(server_default="15")
    ack_window_planned_min: Mapped[int] = mapped_column(server_default="120")
    uninformed_after_min: Mapped[int] = mapped_column(server_default="120")
    timezone: Mapped[str] = mapped_column(String(64), server_default="America/New_York")
