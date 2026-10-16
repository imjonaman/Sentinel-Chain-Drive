"""Agent entity model and lifecycle state machine for AgentID."""

import enum
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sentinel_chain_drive.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AgentStatus(enum.StrEnum):
    """Lifecycle states for registered AI agents."""

    PENDING_APPROVAL = "PENDING_APPROVAL"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


# Legally permitted state transitions. REVOKED is terminal.
VALID_AGENT_TRANSITIONS: dict[AgentStatus, set[AgentStatus]] = {
    AgentStatus.PENDING_APPROVAL: {AgentStatus.ACTIVE, AgentStatus.REVOKED},
    AgentStatus.ACTIVE: {AgentStatus.SUSPENDED, AgentStatus.REVOKED, AgentStatus.EXPIRED},
    AgentStatus.SUSPENDED: {AgentStatus.ACTIVE, AgentStatus.REVOKED, AgentStatus.EXPIRED},
    AgentStatus.EXPIRED: {AgentStatus.REVOKED},
    AgentStatus.REVOKED: set(),  # Terminal state
}


class Agent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """AI Agent registered to initiate financial actions under an institution's authority."""

    __tablename__ = "agents"

    institution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("institutions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(256), nullable=True)
    owner_contact: Mapped[str] = mapped_column(String(128), nullable=False)
    agent_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="AUTONOMOUS_PAYMENT_AGENT",
    )
    public_key: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="PEM-encoded Ed25519 public verification key",
    )
    key_algorithm: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="Ed25519",
    )
    key_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    status: Mapped[AgentStatus] = mapped_column(
        sa.Enum(
            AgentStatus,
            native_enum=False,
            length=24,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=AgentStatus.PENDING_APPROVAL,
        index=True,
    )
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Optional expiration timestamp for periodic recertification",
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    institution = relationship("Institution", lazy="selectin")
    capabilities = relationship(
        "Capability",
        back_populates="agent",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    credentials = relationship(
        "AgentCredential",
        back_populates="agent",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def is_active(self) -> bool:
        """Confirm agent is currently in an active, non-expired, non-revoked state."""
        return self.status == AgentStatus.ACTIVE
