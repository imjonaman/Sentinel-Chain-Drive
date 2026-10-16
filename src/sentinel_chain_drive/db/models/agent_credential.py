"""Agent credential entity for cryptographic verification and revocation."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sentinel_chain_drive.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AgentCredential(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Cryptographic authorization credential issued to an AI agent."""

    __tablename__ = "agent_credentials"

    credential_id: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
        comment="Deterministic credential identifier, e.g. cred_<uuid>",
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    institution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("institutions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    issuer_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="Trust anchor or authority that issued this credential",
    )
    audience: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="Intended consuming service or scope, e.g. sentinel.authorization",
    )
    key_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    algorithm: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="Ed25519",
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    is_revoked: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revocation_reason: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
    )
    claims: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Signed payload claims binding agent, scope, and capabilities",
    )
    signature: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Hex or Base64-encoded Ed25519 signature across canonical claims",
    )

    # Relationships
    agent = relationship("Agent", back_populates="credentials")
    institution = relationship("Institution", lazy="selectin")
