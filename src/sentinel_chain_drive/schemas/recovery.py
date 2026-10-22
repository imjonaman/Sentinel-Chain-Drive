"""Pydantic schemas and contracts for Phase 9 Recovery Request Orchestration."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from sentinel_chain_drive.db.models.recovery import (
    RecoveryActionType,
    RecoveryStatus,
)


class RecoveryRequestCreate(BaseModel):
    """Payload to draft or initiate a recovery request for a case."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: uuid.UUID = Field(
        ...,
        description="Transaction for which recovery or recall is sought",
    )
    target_institution_id: uuid.UUID = Field(
        ...,
        description="Target destination institution owning receiving account",
    )
    amount: Decimal = Field(
        ...,
        gt=Decimal("0.0000"),
        decimal_places=4,
        description="Amount to recall or recover",
    )
    currency: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="ISO 4217 currency code",
    )
    action_type: RecoveryActionType = Field(
        default=RecoveryActionType.FUNDS_RECALL,
        description=(
            "Recovery action: FUNDS_RECALL, PAYMENT_REVERSAL, ACCOUNT_FREEZE_REQUEST, "
            "TRANSACTION_HOLD_REQUEST"
        ),
    )

    rationale: str = Field(
        ...,
        min_length=5,
        max_length=2000,
        description="Detailed justification and evidentiary rationale for request",
    )
    idempotency_key: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Client-generated unique idempotency token for request submission",
    )
    metadata_json: dict[str, Any] = Field(
        default_factory=dict,
        description="Non-sensitive structured routing or reference attributes",
    )


class RecoveryApprovalRequest(BaseModel):
    """Payload to approve a recovery request (dual-control enforcement)."""

    model_config = ConfigDict(extra="forbid")

    approval_notes: str | None = Field(
        default=None,
        max_length=1000,
        description="Supervisor approval notes",
    )


class RecoveryRejectionRequest(BaseModel):
    """Payload to reject a recovery request."""

    model_config = ConfigDict(extra="forbid")

    rejection_reason: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="Mandatory justification for rejecting recovery request",
    )


class RecoverySubmissionRequest(BaseModel):
    """Payload to submit an approved recovery request to simulated rails."""

    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Submission attempt idempotency token",
    )
    target_rail: str = Field(
        default="SYNTHETIC_INTERBANK_SETTLEMENT",
        description="Simulated settlement or message rail descriptor",
    )
    simulated_outcome: str = Field(
        default="ACKNOWLEDGE",
        description="Simulated mock response: ACKNOWLEDGE, REJECT, TIMEOUT (OUTCOME_UNKNOWN)",
    )


class RecoveryAcknowledgeRequest(BaseModel):
    """Payload representing simulated counterparty bank acknowledgement."""

    model_config = ConfigDict(extra="forbid")

    external_reference: str = Field(
        ...,
        min_length=3,
        max_length=128,
        description="External tracking reference returned by target institution",
    )
    notes: str | None = Field(
        default=None,
        max_length=500,
        description="Optional counterparty acknowledgement notes",
    )


class RecoveryReconcileRequest(BaseModel):
    """Payload to reconcile an uncertain or pending recovery outcome."""

    model_config = ConfigDict(extra="forbid")

    reconciliation_status: str = Field(
        ...,
        description="Final reconciliation status: SETTLED, REJECTED",
    )
    reconciliation_notes: str = Field(
        ...,
        min_length=5,
        max_length=2000,
        description="Mandatory investigation and reconciliation explanation",
    )


class RecoveryStatusHistoryResponse(BaseModel):
    """Lifecycle transition history entry for a recovery request."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    recovery_request_id: uuid.UUID
    actor: str
    action: str
    from_status: str
    to_status: str
    reason: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class RecoveryResponse(BaseModel):
    """Recovery request representation with simulated safeguards."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    request_number: str
    case_id: uuid.UUID
    transaction_id: uuid.UUID
    requesting_institution_id: uuid.UUID
    target_institution_id: uuid.UUID
    amount: Decimal
    currency: str
    action_type: RecoveryActionType
    status: RecoveryStatus
    rationale: str
    requester_id: str
    requester_role: str
    approver_id: str | None = None
    approver_role: str | None = None
    approval_notes: str | None = None
    approved_at: datetime | None = None
    rejected_by: str | None = None
    rejection_reason: str | None = None
    rejected_at: datetime | None = None
    idempotency_key: str
    submission_attempt_count: int
    submitted_at: datetime | None = None
    acknowledged_at: datetime | None = None
    external_reference: str | None = None
    reconciliation_status: str | None = None
    reconciliation_notes: str | None = None
    reconciled_at: datetime | None = None
    reconciled_by: str | None = None
    is_simulated: bool = True
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class RecoveryListResponse(BaseModel):
    """Paginated list of recovery requests."""

    model_config = ConfigDict(from_attributes=True)

    items: list[RecoveryResponse]
    total: int
    page: int
    page_size: int
