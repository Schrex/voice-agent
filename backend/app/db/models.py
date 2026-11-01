"""SQLAlchemy models (architecture §5). Schema changes go through an Alembic migration."""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, MetaData, String, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Stable constraint names so migrations can reference them.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


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


STAFF_ROLES = ("coordinator", "admin")


class Staff(Base):
    """A dashboard user. `id` is the Supabase Auth user id (the access token's `sub`)."""

    __tablename__ = "staff"
    __table_args__ = (CheckConstraint("role IN ('coordinator', 'admin')", name="role"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(20))
