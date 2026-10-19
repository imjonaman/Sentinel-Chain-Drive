"""Unit tests for policy models, status transitions, and schema validations."""

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from sentinel_chain_drive.db.models.policy import Policy
from sentinel_chain_drive.db.models.policy_evaluation import (
    HoldStatus,
    PolicyOutcome,
    SpendingReservation,
    SpendingReservationStatus,
    StepUpChallenge,
    StepUpStatus,
    TransactionHold,
)
from sentinel_chain_drive.schemas.policy import (
    HoldResolutionRequest,
    PolicyCreate,
    PolicyRuleConfig,
    StepUpCompletionRequest,
)


def test_policy_model_instantiation() -> None:
    """Verify Policy SQLAlchemy model defaults and field assignment."""
    policy = Policy(
        policy_code="BANK_DEFAULT",
        version=1,
        name="Bank Default Policy",
        priority=50,
        rules={"max_transaction_amount": "10000.0000"},
    )
    assert policy.policy_code == "BANK_DEFAULT"
    assert policy.version == 1
    assert policy.priority == 50
    assert policy.is_active is True
    assert policy.activated_by == "system"


def test_spending_reservation_model() -> None:
    """Verify SpendingReservation defaults."""
    res = SpendingReservation(
        agent_id=uuid.uuid4(),
        institution_id=uuid.uuid4(),
        amount=Decimal("1500.0000"),
        currency="USD",
    )
    assert res.amount == Decimal("1500.0000")
    assert res.status == SpendingReservationStatus.ACTIVE


def test_step_up_challenge_model() -> None:
    """Verify StepUpChallenge model initialization."""
    challenge = StepUpChallenge(
        policy_evaluation_id=uuid.uuid4(),
        transaction_intent_hash="0123456789abcdef" * 4,
        policy_id=uuid.uuid4(),
        policy_version=1,
        initiating_agent_id=uuid.uuid4(),
        institution_id=uuid.uuid4(),
        verification_type="SUPERVISOR_APPROVAL",
        required_role="SUPERVISOR",
    )
    assert challenge.status == StepUpStatus.PENDING
    assert challenge.required_role == "SUPERVISOR"
    assert challenge.approver_id is None


def test_transaction_hold_model() -> None:
    """Verify TransactionHold model initialization."""
    hold = TransactionHold(
        policy_evaluation_id=uuid.uuid4(),
        transaction_intent_hash="0123456789abcdef" * 4,
        institution_id=uuid.uuid4(),
        hold_reason="Velocity anomaly",
    )
    assert hold.status == HoldStatus.ACTIVE
    assert hold.review_workflow == "FRAUD_INVESTIGATION"


def test_policy_schema_validation_success() -> None:
    """Verify PolicyCreate schema with valid configuration."""
    rules = PolicyRuleConfig(
        max_transaction_amount=Decimal("25000.0000"),
        step_up_threshold_amount=Decimal("10000.0000"),
        step_up_risk_threshold=0.6,
        hold_risk_threshold=0.9,
        allowed_currencies=["USD"],
    )
    payload = PolicyCreate(
        policy_code="TIER1_POLICY",
        name="Tier 1 Institutional Policy",
        priority=10,
        rules=rules,
    )
    assert payload.policy_code == "TIER1_POLICY"
    assert payload.rules.max_transaction_amount == Decimal("25000.0000")


def test_policy_schema_invalid_risk_threshold() -> None:
    """Risk thresholds outside [0.0, 1.0] must be rejected."""
    with pytest.raises(ValidationError):
        PolicyRuleConfig(step_up_risk_threshold=1.5)

    with pytest.raises(ValidationError):
        PolicyRuleConfig(hold_risk_threshold=-0.1)


def test_step_up_completion_schema() -> None:
    """Verify StepUpCompletionRequest schema validation."""
    valid_req = StepUpCompletionRequest(
        approver_id="supervisor_alice",
        decision="APPROVED",
        reason="Verified via telephone confirmation.",
    )
    assert valid_req.decision == "APPROVED"

    with pytest.raises(ValidationError):
        StepUpCompletionRequest(
            approver_id="supervisor_alice",
            decision="INVALID_DECISION",
            reason="Some reason",
        )


def test_hold_resolution_schema() -> None:
    """Verify HoldResolutionRequest schema validation."""
    valid_req = HoldResolutionRequest(
        resolution="RELEASE",
        resolved_by="analyst_bob",
        notes="Legitimate batch payroll transaction verified.",
    )
    assert valid_req.resolution == "RELEASE"

    with pytest.raises(ValidationError):
        HoldResolutionRequest(
            resolution="INVALID_RESOLUTION",
            resolved_by="analyst_bob",
            notes="Case notes",
        )


def test_policy_outcomes_enumeration() -> None:
    """Verify exact policy outcomes set."""
    outcomes = {o.value for o in PolicyOutcome}
    assert outcomes == {"ALLOW", "STEP_UP", "HOLD", "DECLINE"}
