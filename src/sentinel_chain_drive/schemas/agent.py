"""Agent request and response validation schemas."""

import uuid
from datetime import datetime
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from pydantic import BaseModel, Field, field_validator, model_validator

from sentinel_chain_drive.core.crypto import load_ed25519_public_key
from sentinel_chain_drive.db.models.agent import AgentStatus


def _normalize_public_key(val: str) -> str:
    """Normalize public key: converts 64-hex string to PEM, or preserves valid PEM."""
    cleaned = val.strip()
    if len(cleaned) == 64 and all(c in "0123456789abcdefABCDEF" for c in cleaned):
        try:
            pub = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(cleaned))
            return pub.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            ).decode("utf-8")
        except Exception as err:
            raise ValueError(f"Invalid 64-hex Ed25519 public key: {err}") from err
    return cleaned


class AgentCreate(BaseModel):
    """Schema for registering a new AI agent."""

    institution_id: uuid.UUID | None = Field(
        default=None,
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
        default="security-admin@bank.internal",
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
        default="",
        description="PEM-encoded Ed25519 public verification key or 64-hex string",
    )
    ed25519_public_key: str | None = Field(
        default=None,
        description="Alias for public_key",
    )
    valid_until: datetime | None = Field(
        default=None,
        description="Optional recertification expiry timestamp",
    )

    @model_validator(mode="before")
    @classmethod
    def preprocess_agent_create(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if not data.get("public_key") and data.get("ed25519_public_key"):
                data["public_key"] = data["ed25519_public_key"]
            if data.get("public_key"):
                data["public_key"] = _normalize_public_key(str(data["public_key"]))
            if not data.get("owner_contact"):
                data["owner_contact"] = "security-admin@bank.internal"
            if not data.get("agent_type"):
                data["agent_type"] = "AUTONOMOUS_PAYMENT_AGENT"
        return data

    @field_validator("public_key")
    @classmethod
    def validate_public_key_pem(cls, value: str) -> str:
        """Enforce that the provided public key is valid Ed25519 PEM."""
        if not value:
            raise ValueError("Public key must be provided as 64-hex string or PEM.")
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
        default="",
        description="New PEM-encoded Ed25519 public verification key or 64-hex string",
    )
    new_ed25519_public_key: str | None = Field(
        default=None,
        description="Alias for new_public_key",
    )
    reason: str | None = Field(
        default=None,
        max_length=256,
        description="Reason for key rotation",
    )

    @model_validator(mode="before")
    @classmethod
    def preprocess_key_rotation(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if not data.get("new_public_key") and data.get("new_ed25519_public_key"):
                data["new_public_key"] = data["new_ed25519_public_key"]
            if data.get("new_public_key"):
                data["new_public_key"] = _normalize_public_key(str(data["new_public_key"]))
        return data

    @field_validator("new_public_key")
    @classmethod
    def validate_new_public_key_pem(cls, value: str) -> str:
        if not value:
            raise ValueError("New public key must be provided as 64-hex string or PEM.")
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
