"""Credential and cryptographic authorization request/response schemas."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class TransactionIntent(BaseModel):
    """Transaction payload to be verified against agent capabilities and signature binding."""

    amount: Decimal = Field(gt=Decimal("0.00"), description="Transaction amount")
    currency: str = Field(min_length=3, max_length=3, description="3-letter ISO currency code")
    origin_institution_code: str = Field(min_length=2, max_length=16)
    origin_account_number: str = Field(min_length=4, max_length=34)
    destination_institution_code: str = Field(min_length=2, max_length=16)
    destination_account_number: str = Field(min_length=4, max_length=34)
    transaction_type: str = Field(min_length=2, max_length=32)
    purpose_code: str | None = Field(default=None, max_length=32)


class CredentialIssueRequest(BaseModel):
    """Schema for registering or issuing a cryptographic agent credential."""

    agent_id: uuid.UUID
    institution_id: uuid.UUID
    issuer_id: str = Field(
        default="sentinel.trust-authority",
        max_length=128,
        description="Identifier of the credential issuing authority",
    )
    audience: str = Field(
        default="sentinel.authorization",
        max_length=128,
        description="Target audience or service domain",
    )
    valid_hours: int = Field(default=24, ge=1, le=8760, description="Validity window in hours")
    claims: dict[str, Any] = Field(default_factory=dict, description="Custom credential claims")
    signature: str = Field(
        description="Hex-encoded signature over canonical claims",
    )


class CredentialRevocationRequest(BaseModel):
    """Schema for revoking a credential."""

    reason: str = Field(min_length=3, max_length=256, description="Revocation rationale")


class AuthorizationVerificationRequest(BaseModel):
    """Cryptographic authorization request submitted with each transaction intent."""

    credential_id: str = Field(description="Unique credential ID")
    agent_id: uuid.UUID = Field(description="Agent identity")
    institution_id: uuid.UUID = Field(description="Owning institution ID")
    nonce: str = Field(
        min_length=16,
        max_length=64,
        description="Single-use high-entropy nonce for replay protection",
    )
    request_timestamp: datetime = Field(
        description="UTC timestamp of the authorization request (|now - ts| <= 300s)",
    )
    transaction: TransactionIntent
    signature: str = Field(
        description="Hex-encoded Ed25519 signature by agent key over canonical request payload",
    )
    expected_audience: str | None = Field(
        default="sentinel.authorization",
        max_length=128,
        description="Target audience or service domain to match against credential",
    )
    expected_issuer: str | None = Field(
        default=None,
        max_length=128,
        description="Optional expected credential issuing authority ID",
    )


class AuthorizationVerificationResponse(BaseModel):
    """Verification outcome returned to the gateway or caller."""

    authorized: bool
    decision: str = Field(description="AUTHORIZED or REJECTED")
    reasons: list[str] = Field(default_factory=list, description="Audit reason codes")
    agent_id: uuid.UUID
    institution_id: uuid.UUID
    credential_id: str
    nonce: str
    evaluated_at: datetime


class CredentialResponse(BaseModel):
    """Response model for an issued agent credential."""

    id: uuid.UUID
    credential_id: str
    agent_id: uuid.UUID
    institution_id: uuid.UUID
    issuer_id: str
    audience: str
    key_version: int
    algorithm: str
    issued_at: datetime
    expires_at: datetime
    is_revoked: bool
    revoked_at: datetime | None
    revocation_reason: str | None
    claims: dict[str, Any]
    signature: str
    created_at: datetime

    model_config = {"from_attributes": True}


class CredentialListResponse(BaseModel):
    """Paginated list of credentials."""

    items: list[CredentialResponse]
    total: int
    limit: int
    offset: int
