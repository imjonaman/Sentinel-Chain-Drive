"""Transaction request and response schemas."""

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from sentinel_chain_drive.db.models.transaction import TransactionStatus, TransactionType


class SimulationAction(enum.StrEnum):
    """Permitted simulation-only lifecycle operations."""

    SIMULATE_AUTHORIZE = "SIMULATE_AUTHORIZE"
    SIMULATE_SETTLE = "SIMULATE_SETTLE"
    SIMULATE_HOLD = "SIMULATE_HOLD"
    SIMULATE_REJECT = "SIMULATE_REJECT"
    AUTHORIZE = "AUTHORIZE"
    SETTLE = "SETTLE"
    HOLD = "HOLD"
    REJECT = "REJECT"
    CANCEL = "CANCEL"


class TransactionSubmitRequest(BaseModel):
    """Schema for submitting a simulated payment transaction."""

    idempotency_key: str = Field(
        min_length=16,
        max_length=128,
        description="Client-generated unique key for request deduplication",
    )
    origin_institution_id: uuid.UUID = Field(
        description="Initiating institution identifier",
    )
    origin_account_id: uuid.UUID = Field(
        description="Debited origin account identifier",
    )
    destination_institution_id: uuid.UUID = Field(
        description="Receiving institution identifier",
    )
    destination_account_id: uuid.UUID = Field(
        description="Credited destination account identifier",
    )
    amount: Decimal = Field(
        gt=Decimal("0.0000"),
        le=Decimal("100000000.0000"),
        decimal_places=4,
        description="Transfer amount in exact decimal precision (> 0 and <= 100,000,000)",
    )
    currency: str = Field(
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
        description="ISO 4217 three-letter currency code (e.g. USD)",
    )
    transaction_type: TransactionType = Field(
        default=TransactionType.TRANSFER,
        description="Transaction type classification",
    )
    purpose_code: str = Field(
        default="TRANSFER",
        min_length=2,
        max_length=32,
        description="Standard payment purpose descriptor",
    )
    simulation_metadata: dict[str, Any] | None = Field(
        default=None,
        description="Optional simulation scenario tags or testing context",
    )


class TransactionSimulationActionRequest(BaseModel):
    """Schema for explicitly transitioning a simulated transaction state."""

    action: SimulationAction = Field(
        description="Simulation action to execute",
    )
    reason: str | None = Field(
        default=None,
        max_length=256,
        description="Operational rationale for simulation state change",
    )


class TransactionStatusHistoryResponse(BaseModel):
    """Response model for a recorded transaction status transition."""

    id: uuid.UUID
    transaction_id: uuid.UUID
    previous_status: str | None
    new_status: str
    reason: str | None
    actor: str
    correlation_id: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TransactionResponse(BaseModel):
    """Response model representing a financial transaction."""

    id: uuid.UUID
    idempotency_key: str
    origin_institution_id: uuid.UUID
    origin_account_id: uuid.UUID
    destination_institution_id: uuid.UUID
    destination_account_id: uuid.UUID
    amount: Decimal
    currency: str
    transaction_type: TransactionType
    status: TransactionStatus
    purpose_code: str
    agent_id: uuid.UUID | None
    rejection_reason: str | None
    correlation_id: str | None
    simulation_metadata: dict[str, Any] | None
    settled_at: datetime | None
    created_at: datetime
    updated_at: datetime
    status_history: list[TransactionStatusHistoryResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class TransactionListResponse(BaseModel):
    """Paginated list response for transactions."""

    items: list[TransactionResponse]
    total: int
    limit: int
    offset: int
