"""Account request and response schemas."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, field_validator

from sentinel_chain_drive.db.models.account import AccountStatus, AccountType


class AccountCreate(BaseModel):
    """Schema for creating a synthetic bank account."""

    institution_id: uuid.UUID = Field(
        description="Owning institution identifier",
    )
    account_number: str = Field(
        min_length=4,
        max_length=64,
        pattern=r"^[A-Z0-9_-]+$",
        description="Synthetic unique account number (e.g., ACCT-100234)",
    )
    account_type: AccountType = Field(
        default=AccountType.CHECKING,
        description="Account type classification",
    )
    currency: str = Field(
        default="USD",
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
        description="ISO 4217 three-letter currency code",
    )
    initial_balance: Decimal = Field(
        default=Decimal("0.0000"),
        ge=Decimal("0.0000"),
        decimal_places=4,
        description="Initial balance in exact decimal precision",
    )
    risk_flags: list[str] = Field(
        default_factory=list,
        description="Initial risk tags (e.g. ['NEW_ACCOUNT'])",
    )

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip().upper()
        return v


class AccountStatusUpdate(BaseModel):
    """Schema for changing account lifecycle status."""

    status: AccountStatus = Field(
        description="New account status (ACTIVE, FROZEN, CLOSED)",
    )
    reason: str | None = Field(
        default=None,
        max_length=256,
        description="Operational rationale for status change",
    )


class AccountResponse(BaseModel):
    """Response model representing a synthetic bank account."""

    id: uuid.UUID
    institution_id: uuid.UUID
    account_number: str
    account_type: AccountType
    currency: str
    balance: Decimal
    status: AccountStatus
    risk_flags: list[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AccountListResponse(BaseModel):
    """Paginated list response for accounts."""

    items: list[AccountResponse]
    total: int
    limit: int
    offset: int
