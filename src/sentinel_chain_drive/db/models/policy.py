"""Deterministic policy model for transaction authorization governance."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sentinel_chain_drive.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Policy(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Versioned institutional or global transaction authorization policy."""

    __tablename__ = "policies"

    institution_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="Owning institution (null denotes system-wide default baseline)",
    )
    policy_code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="Unique policy family identifier e.g. DEFAULT_BANKING_POLICY",
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="Monotonically increasing policy version number",
    )
    name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="Human-readable policy title",
    )
    description: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
        comment="Detailed policy scope or regulatory intent description",
    )
    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=100,
        comment="Evaluation precedence: lower integer indicates higher priority",
    )
    rules: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Structured predicate definitions, thresholds, and condition parameters",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        comment="Whether this policy version is active for evaluation",
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=lambda: datetime.now(UTC),
        comment="Timestamp when policy version was made active",
    )
    activated_by: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="system",
        comment="Authenticated identity or actor who activated this version",
    )

    # Relationships
    institution = relationship("Institution", lazy="selectin")

    __table_args__ = (
        UniqueConstraint(
            "institution_id",
            "policy_code",
            "version",
            name="uq_policies_institution_code_version",
        ),
    )

    def __init__(
        self,
        *,
        policy_code: str,
        name: str,
        version: int = 1,
        priority: int = 100,
        rules: dict[str, Any] | None = None,
        is_active: bool = True,
        institution_id: uuid.UUID | None = None,
        description: str | None = None,
        activated_at: datetime | None = None,
        activated_by: str = "system",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.policy_code = policy_code
        self.name = name
        self.version = version
        self.priority = priority
        self.rules = rules or {}
        self.is_active = is_active
        self.institution_id = institution_id
        self.description = description
        self.activated_at = activated_at or datetime.now(UTC)
        self.activated_by = activated_by
