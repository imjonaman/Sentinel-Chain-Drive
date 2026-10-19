"""Privacy Gateway audit event log model."""

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from sentinel_chain_drive.db.base import Base, UUIDPrimaryKeyMixin


class PrivacyAction(enum.StrEnum):
    """Actions recorded in the privacy audit stream."""

    PUBLISH = "PUBLISH"
    QUERY = "QUERY"
    REJECT = "REJECT"
    REVOKE = "REVOKE"
    WITHDRAW = "WITHDRAW"


class PrivacyOutcome(enum.StrEnum):
    """Outcome status of an audited privacy action."""

    SUCCESS = "SUCCESS"
    DENIED = "DENIED"
    VALIDATION_FAILED = "VALIDATION_FAILED"


class PrivacyAuditLog(Base, UUIDPrimaryKeyMixin):
    """Immutable audit record tracking cross-institution intelligence sharing and queries."""

    __tablename__ = "privacy_audit_logs"

    institution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Institution associated with the privacy action",
    )
    actor: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="Authenticated caller, agent, or simulation actor",
    )
    action: Mapped[PrivacyAction] = mapped_column(
        Enum(PrivacyAction, name="privacy_action_enum", native_enum=False),
        nullable=False,
        index=True,
        comment="Type of privacy operation performed",
    )
    outcome: Mapped[PrivacyOutcome] = mapped_column(
        Enum(PrivacyOutcome, name="privacy_outcome_enum", native_enum=False),
        nullable=False,
        comment="Execution result status",
    )
    pseudonymous_mesh_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="Subject MeshID queried or published",
    )
    indicator_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("shared_indicators.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Target shared indicator identifier if applicable",
    )
    details: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Non-sensitive operational metadata (rule version, reason, query filters)",
    )
    correlation_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="Correlation ID for request tracing",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
        comment="UTC timestamp when the event was recorded",
    )
