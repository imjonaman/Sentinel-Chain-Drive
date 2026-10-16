"""SQLAlchemy declarative base and common model mixins."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, MetaData, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Standard naming conventions for constraints to ensure deterministic migration generation
POSTGRES_NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""

    metadata = MetaData(naming_convention=POSTGRES_NAMING_CONVENTION)


class TimestampMixin:
    """Provides standard UTC timestamp audit fields."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class UUIDPrimaryKeyMixin:
    """Provides a primary key UUID field compatible across PostgreSQL and SQLite (in tests)."""

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
