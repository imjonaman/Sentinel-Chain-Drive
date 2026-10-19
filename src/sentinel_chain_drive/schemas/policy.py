"""Pydantic schemas for Policy configuration, evaluation, step-up challenges, and holds."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from sentinel_chain_drive.db.models.policy_evaluation import (
    HoldStatus,
    PolicyOutcome,
    StepUpStatus,
)
from sentinel_chain_drive.schemas.credential import TransactionIntent


class PolicyRuleConfig(BaseModel):
    """Configurable predicates and parameters for a policy version."""

    max_transaction_amount: Decimal | None = Field(
        default=None,
        gt=Decimal("0.0000"),
        description="Absolute ceiling amount permitted per transaction under this policy",
    )
    step_up_threshold_amount: Decimal | None = Field(
        default=Decimal("10000.0000"),
        gt=Decimal("0.0000"),
        description="Transaction amount exceeding this threshold triggers STEP_UP dual control",
    )
    step_up_risk_threshold: float = Field(
        default=0.50,
        ge=0.0,
        le=1.0,
        description="Risk score threshold (inclusive) triggering STEP_UP outcome",
    )
    hold_risk_threshold: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Risk score threshold (inclusive) triggering HOLD outcome",
    )
    require_whitelisted_beneficiary: bool = Field(
        default=False,
        description="Require destination account to be pre-approved in agent capability envelope",
    )
    allowed_currencies: list[str] | None = Field(
        default=None,
        description="Optional policy-level allowed currency whitelist",
    )
    allowed_purpose_codes: list[str] | None = Field(
        default=None,
        description="Optional policy-level allowed purpose code whitelist",
    )
    dual_control_roles: list[str] = Field(
        default_factory=lambda: ["SUPERVISOR"],
        description="Roles authorized to complete step-up verification challenges",
    )
    manual_review_roles: list[str] = Field(
        default_factory=lambda: ["FRAUD_ANALYST", "COMPLIANCE_OFFICER"],
        description="Roles authorized to resolve transaction holds",
    )


class PolicyCreate(BaseModel):
    """Schema for creating a new versioned policy."""

    institution_id: uuid.UUID | None = Field(
        default=None,
        description="Owning institution ID (null creates a system-wide default baseline policy)",
    )
    policy_code: str = Field(
        min_length=3,
        max_length=64,
        description="Policy family code e.g. DEFAULT_BANKING_POLICY",
    )
    name: str = Field(
        min_length=3,
        max_length=128,
        description="Human-readable policy title",
    )
    description: str | None = Field(
        default=None,
        max_length=256,
        description="Scope or regulatory purpose description",
    )
    priority: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Lower integer indicates higher precedence during evaluation",
    )
    rules: PolicyRuleConfig = Field(
        default_factory=PolicyRuleConfig,
        description="Configurable rule predicates and thresholds",
    )


class PolicyUpdate(BaseModel):
    """Schema for updating draft policy metadata (active policies create new versions)."""

    name: str | None = Field(default=None, min_length=3, max_length=128)
    description: str | None = Field(default=None, max_length=256)
    priority: int | None = Field(default=None, ge=1, le=1000)
    rules: PolicyRuleConfig | None = None


class PolicyResponse(BaseModel):
    """Public representation of a versioned policy."""

    id: uuid.UUID
    institution_id: uuid.UUID | None
    policy_code: str
    version: int
    name: str
    description: str | None
    priority: int
    rules: dict[str, Any]
    is_active: bool
    activated_at: datetime | None
    activated_by: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PolicyListResponse(BaseModel):
    """Paginated list of policies."""

    items: list[PolicyResponse]
    total: int
    limit: int
    offset: int


class RiskSignals(BaseModel):
    """Client- or sensor-provided risk telemetry evaluated deterministically."""

    risk_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Normalized risk score from 0.0 (benign) to 1.0 (high risk)",
    )
    velocity_warning: bool = Field(
        default=False,
        description="True if rapid transaction frequency anomaly detected",
    )
    manual_review_flag: bool = Field(
        default=False,
        description="Explicit flag requesting manual institutional review",
    )
    custom_signals: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional deterministic risk parameters",
    )


class PolicyEvaluationRequest(BaseModel):
    """Request payload to evaluate a transaction authorization through the policy engine."""

    idempotency_key: str = Field(
        min_length=16,
        max_length=128,
        description="Client-generated unique idempotency key",
    )
    credential_id: str = Field(
        description="AgentID credential identifier",
    )
    agent_id: uuid.UUID = Field(
        description="AI Agent UUID",
    )
    institution_id: uuid.UUID = Field(
        description="Origin institution UUID",
    )
    nonce: str = Field(
        min_length=16,
        max_length=64,
        description="Single-use high-entropy replay prevention nonce",
    )
    request_timestamp: datetime = Field(
        description="UTC request timestamp within allowed clock skew window",
    )
    transaction: TransactionIntent = Field(
        description="Canonical transaction intent fields",
    )
    signature: str = Field(
        description="Hex-encoded Ed25519 signature over canonical authorization payload",
    )
    transaction_id: uuid.UUID | None = Field(
        default=None,
        description="Optional existing transaction identifier to bind and update status",
    )
    risk_signals: RiskSignals = Field(
        default_factory=RiskSignals,
        description="Deterministic risk indicators",
    )
    expected_audience: str | None = Field(
        default="sentinel.authorization",
        max_length=128,
    )
    expected_issuer: str | None = Field(
        default=None,
        max_length=128,
    )


class StepUpChallengeInfo(BaseModel):
    """Summary of step-up verification required for a STEP_UP decision."""

    challenge_id: uuid.UUID
    verification_type: str
    required_role: str
    status: StepUpStatus
    expires_at: datetime


class HoldInfo(BaseModel):
    """Summary of institutional review hold for a HOLD decision."""

    hold_id: uuid.UUID
    hold_reason: str
    review_workflow: str
    status: HoldStatus


class PolicyDecisionResponse(BaseModel):
    """Shielded public policy evaluation decision model."""

    decision: PolicyOutcome
    reason_codes: list[str] = Field(
        description="Stable machine-readable public reason codes",
    )
    policy_id: uuid.UUID
    policy_version: int
    agent_id: uuid.UUID
    institution_id: uuid.UUID
    transaction_id: uuid.UUID | None
    transaction_intent_hash: str
    evaluated_at: datetime
    correlation_id: str | None
    idempotency_key: str
    step_up_challenge: StepUpChallengeInfo | None = None
    hold: HoldInfo | None = None
    audit_record_id: uuid.UUID | None = None

    model_config = ConfigDict(from_attributes=True)


class PolicyEvaluationDetailResponse(PolicyDecisionResponse):
    """Detailed evaluation record available to authorized investigators and compliance auditors."""

    applicable_rule_ids: list[str] = Field(
        description="Internal identifiers of policy rules that triggered during evaluation",
    )
    evaluation_evidence: dict[str, Any] = Field(
        description="Internal decision evidence, raw inputs, and thresholds",
    )
    spending_reservation_id: uuid.UUID | None = None


class PolicyEvaluationListResponse(BaseModel):
    """Paginated list of policy evaluations."""

    items: list[PolicyDecisionResponse]
    total: int
    limit: int
    offset: int


class StepUpCompletionRequest(BaseModel):
    """Request schema for supervisor or dual-control step-up resolution."""

    approver_id: str = Field(
        min_length=3,
        max_length=128,
        description="Identity of the supervisor or approver (must not match initiating agent)",
    )
    decision: str = Field(
        pattern="^(APPROVED|REJECTED)$",
        description="Approval decision: APPROVED or REJECTED",
    )
    reason: str = Field(
        min_length=3,
        max_length=500,
        description="Operational rationale for supervisor signoff or rejection",
    )


class StepUpChallengeResponse(BaseModel):
    """Full detail of a step-up challenge."""

    id: uuid.UUID
    policy_evaluation_id: uuid.UUID
    transaction_id: uuid.UUID | None
    transaction_intent_hash: str
    policy_id: uuid.UUID
    policy_version: int
    initiating_agent_id: uuid.UUID
    institution_id: uuid.UUID
    verification_type: str
    required_role: str
    status: StepUpStatus
    expires_at: datetime
    approver_id: str | None
    decision_reason: str | None
    completed_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HoldResolutionRequest(BaseModel):
    """Request schema for resolving an institutional review hold."""

    resolution: str = Field(
        pattern="^(RELEASE|CONFIRM_DECLINE)$",
        description="Resolution action: RELEASE or CONFIRM_DECLINE",
    )
    resolved_by: str = Field(
        min_length=3,
        max_length=128,
        description="Identity of the fraud investigator or compliance officer",
    )
    notes: str = Field(
        min_length=3,
        max_length=500,
        description="Resolution explanation or case notes",
    )


class TransactionHoldResponse(BaseModel):
    """Full detail of a transaction hold."""

    id: uuid.UUID
    policy_evaluation_id: uuid.UUID
    transaction_id: uuid.UUID | None
    transaction_intent_hash: str
    institution_id: uuid.UUID
    hold_reason: str
    review_workflow: str
    status: HoldStatus
    resolved_by: str | None
    resolution_notes: str | None
    resolved_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
