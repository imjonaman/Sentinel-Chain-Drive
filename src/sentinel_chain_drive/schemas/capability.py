"""Capability request and response schemas."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, model_validator


class CapabilityCreate(BaseModel):
    """Schema for assigning authorization capabilities to an agent."""

    agent_id: uuid.UUID = Field(description="Target agent ID")
    name: str = Field(
        default="Default Capability Envelope",
        min_length=2,
        max_length=64,
        description="Capability identifier/profile name",
    )
    description: str | None = Field(default=None, max_length=256)
    permitted_transaction_types: list[str] = Field(
        default_factory=lambda: ["DOMESTIC_TRANSFER", "INTERBANK_PAYMENT"],
        min_length=1,
        description="Allowed transaction types (e.g. ['DOMESTIC_TRANSFER'])",
    )
    permitted_currencies: list[str] = Field(
        default_factory=lambda: ["USD"],
        min_length=1,
        description="Allowed 3-letter currency codes (e.g. ['USD'])",
    )
    max_amount_per_transaction: Decimal = Field(
        gt=Decimal("0.00"),
        description="Maximum single transaction amount",
    )
    max_daily_cumulative_amount: Decimal = Field(
        gt=Decimal("0.00"),
        description="Maximum 24-hour aggregate transaction spend",
    )
    allowed_origin_accounts: list[str] | None = Field(
        default=None,
        description="Optional whitelist of source account numbers",
    )
    allowed_destination_accounts: list[str] | None = Field(
        default=None,
        description="Optional whitelist of destination account numbers",
    )
    purpose_codes: list[str] | None = Field(
        default=None,
        description="Optional allowed purpose codes (e.g. ['PAYROLL'])",
    )
    operating_start_hour_utc: int | None = Field(
        default=None,
        ge=0,
        le=23,
        description="Start operating hour UTC (0-23)",
    )
    operating_end_hour_utc: int | None = Field(
        default=None,
        ge=0,
        le=23,
        description="End operating hour UTC (0-23)",
    )
    valid_from: datetime | None = Field(default=None)
    valid_until: datetime = Field(
        default_factory=lambda: datetime.now(UTC) + timedelta(days=365),
        description="Expiry date and time for capability",
    )
    created_by: str = Field(
        default="Security Administrator",
        min_length=2,
        max_length=128,
        description="Operator identity",
    )

    @model_validator(mode="before")
    @classmethod
    def preprocess_capability_create(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if not data.get("name"):
                data["name"] = f"Capability Profile for {str(data.get('agent_id', 'agent'))[:8]}"
            if not data.get("permitted_transaction_types"):
                data["permitted_transaction_types"] = ["DOMESTIC_TRANSFER", "INTERBANK_PAYMENT"]
            if not data.get("permitted_currencies"):
                data["permitted_currencies"] = ["USD"]
            if not data.get("created_by"):
                data["created_by"] = "Security Administrator"
            if not data.get("valid_until"):
                data["valid_until"] = datetime.now(UTC) + timedelta(days=365)
            # Map destination_account_whitelist to allowed_destination_accounts
            whitelist = data.get("destination_account_whitelist")
            if not data.get("allowed_destination_accounts") and whitelist:
                data["allowed_destination_accounts"] = whitelist
        return data

    @model_validator(mode="after")
    def validate_amounts_and_windows(self) -> "CapabilityCreate":
        if self.max_daily_cumulative_amount < self.max_amount_per_transaction:
            raise ValueError(
                "max_daily_cumulative_amount must be greater than or equal to "
                "max_amount_per_transaction"
            )
        if (self.operating_start_hour_utc is not None and self.operating_end_hour_utc is None) or (
            self.operating_start_hour_utc is None and self.operating_end_hour_utc is not None
        ):
            raise ValueError(
                "Both operating_start_hour_utc and operating_end_hour_utc must be provided "
                "together, or neither"
            )
        return self


class CapabilityUpdate(BaseModel):
    """Schema for updating capability limits or status."""

    max_amount_per_transaction: Decimal | None = Field(default=None, gt=Decimal("0.00"))
    max_daily_cumulative_amount: Decimal | None = Field(default=None, gt=Decimal("0.00"))
    allowed_origin_accounts: list[str] | None = None
    allowed_destination_accounts: list[str] | None = None
    purpose_codes: list[str] | None = None
    operating_start_hour_utc: int | None = Field(default=None, ge=0, le=23)
    operating_end_hour_utc: int | None = Field(default=None, ge=0, le=23)
    valid_until: datetime | None = None
    is_active: bool | None = None
    approved_by: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_update_amounts_and_windows(self) -> "CapabilityUpdate":
        if (
            self.max_daily_cumulative_amount is not None
            and self.max_amount_per_transaction is not None
            and self.max_daily_cumulative_amount < self.max_amount_per_transaction
        ):
            raise ValueError(
                "max_daily_cumulative_amount must be greater than or equal to "
                "max_amount_per_transaction"
            )
        if (self.operating_start_hour_utc is not None and self.operating_end_hour_utc is None) or (
            self.operating_start_hour_utc is None and self.operating_end_hour_utc is not None
        ):
            raise ValueError(
                "Both operating_start_hour_utc and operating_end_hour_utc must be provided "
                "together, or neither"
            )
        return self


class CapabilityResponse(BaseModel):
    """Response model for agent capabilities."""

    id: uuid.UUID
    agent_id: uuid.UUID
    institution_id: uuid.UUID
    name: str
    description: str | None
    permitted_transaction_types: list[str]
    permitted_currencies: list[str]
    max_amount_per_transaction: Decimal
    max_daily_cumulative_amount: Decimal
    allowed_origin_accounts: list[str] | None
    allowed_destination_accounts: list[str] | None
    purpose_codes: list[str] | None
    operating_start_hour_utc: int | None
    operating_end_hour_utc: int | None
    valid_from: datetime
    valid_until: datetime
    is_active: bool
    created_by: str
    approved_by: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CapabilityListResponse(BaseModel):
    """Paginated capability response."""

    items: list[CapabilityResponse]
    total: int
    limit: int
    offset: int
