"""Agent request and response validation schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from sentinel_chain_drive.core.crypto import load_ed25519_public_key
from sentinel_chain_drive.db.models.agent import AgentStatus


class AgentCreate(BaseModel):
    """Schema for registering a new AI agent."""

    institution_id: uuid.UUID = Field(
        description="ID of the sponsoring financial institution",
    )
    name: str = Field(
        min_length=2,
        max_length=64,
        description="Human-readable identifier for the agent",
    )
    description: str | None = Field(
        default=None,
        max_length=256,
        description="Optional description of agent function and authority",
    )
    owner_contact: str = Field(
        min_length=3,
        max_length=128,
        description="Responsible human or department email/contact",
    )
    agent_type: str = Field(
        default="AUTONOMOUS_PAYMENT_AGENT",
        max_length=32,
        description="Functional classification of the agent",
    )
    public_key: str = Field(
        description="PEM-encoded Ed25519 public verification key",
    )
    valid_until: datetime | None = Field(
        default=None,
        description="Optional recertification expiry timestamp",
    )

    @field_validator("public_key")
    @classmethod
    def validate_public_key_pem(cls, value: str) -> str:
        """Enforce that the provided public key is valid Ed25519 PEM."""
        try:
            load_ed25519_public_key(value)
        except Exception as err:
            raise ValueError(f"Invalid Ed25519 public verification key: {err}") from err
        return value.strip()


class AgentUpdate(BaseModel):
    """Schema for updating agent metadata."""

    name: str | None = Field(
        default=None,
        min_length=2,
        max_length=64,
    )
    description: str | None = Field(
        default=None,
        max_length=256,
    )
    owner_contact: str | None = Field(
        default=None,
        min_length=3,
        max_length=128,
    )


class AgentStatusUpdate(BaseModel):
    """Schema for requesting a lifecycle transition."""

    status: AgentStatus = Field(
        description="Target lifecycle state (ACTIVE, SUSPENDED, REVOKED, EXPIRED)",
    )
    reason: str | None = Field(
        default=None,
        max_length=256,
        description="Administrative rationale for status transition",
    )


class AgentKeyRotation(BaseModel):
    """Schema for rotating an agent's cryptographic verification key."""

    new_public_key: str = Field(
        description="New PEM-encoded Ed25519 public verification key",
    )
    reason: str | None = Field(
        default=None,
        max_length=256,
        description="Reason for key rotation",
    )

    @field_validator("new_public_key")
    @classmethod
    def validate_new_public_key_pem(cls, value: str) -> str:
        try:
            load_ed25519_public_key(value)
        except Exception as err:
            raise ValueError(f"Invalid Ed25519 public verification key: {err}") from err
        return value.strip()


class AgentResponse(BaseModel):
    """Response model representing a registered AI agent."""

    id: uuid.UUID
    institution_id: uuid.UUID
    name: str
    description: str | None
    owner_contact: str
    agent_type: str
    public_key: str
    key_algorithm: str
    key_version: int
    status: AgentStatus
    valid_until: datetime | None
    activated_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AgentListResponse(BaseModel):
    """Paginated list of agents."""

    items: list[AgentResponse]
    total: int
    limit: int
    offset: int
