"""AuditLog model for traceable, tamper-evident recording of system and security events."""

from typing import Any

from sqlalchemy import JSON, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from sentinel_chain_drive.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AuditLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Immutable record of system, authorization, and administrative events."""

    __tablename__ = "audit_logs"

    event_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="Categorical classification of the audit event",
    )
    severity: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="INFO",
        index=True,
        comment="Log severity: INFO, WARNING, ERROR, CRITICAL",
    )
    actor: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="system",
        comment="Entity or identifier responsible for initiating the event",
    )
    correlation_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="Associated HTTP request correlation ID",
    )
    description: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="Human-readable event summary",
    )
    details: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        comment="Structured diagnostic context",
    )

    __table_args__ = (Index("ix_audit_logs_created_at_desc", "created_at"),)
