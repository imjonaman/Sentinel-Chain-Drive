"""Unit tests for the DeterministicPolicyEngine and rule precedence hierarchy."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sentinel_chain_drive.db.models.account import Account, AccountStatus, AccountType
from sentinel_chain_drive.db.models.agent import Agent, AgentStatus
from sentinel_chain_drive.db.models.capability import Capability
from sentinel_chain_drive.db.models.institution import Institution, InstitutionStatus
from sentinel_chain_drive.db.models.policy import Policy
from sentinel_chain_drive.db.models.policy_evaluation import PolicyOutcome
from sentinel_chain_drive.schemas.credential import TransactionIntent
from sentinel_chain_drive.schemas.policy import RiskSignals
from sentinel_chain_drive.services.policy_engine import DeterministicPolicyEngine


def create_test_fixtures(
    agent_status: AgentStatus = AgentStatus.ACTIVE,
    institution_status: InstitutionStatus = InstitutionStatus.ACTIVE,
    origin_account_status: AccountStatus = AccountStatus.ACTIVE,
    destination_account_status: AccountStatus = AccountStatus.ACTIVE,
    currency: str = "USD",
    single_limit: Decimal = Decimal("10000.0000"),
    daily_limit: Decimal = Decimal("50000.0000"),
    policy_max_cap: Decimal | None = None,
    step_up_threshold: Decimal = Decimal("5000.0000"),
) -> tuple[Policy, Agent, list[Capability], Institution, Account, Account]:
    """Helper creating initialized test entities."""
    inst_id = uuid.uuid4()
    agent_id = uuid.uuid4()

    policy = Policy(
        id=uuid.uuid4(),
        institution_id=inst_id,
        policy_code="UNIT_TEST_POLICY",
        version=1,
        name="Unit Test Policy",
        priority=100,
        rules={
            "max_transaction_amount": str(policy_max_cap) if policy_max_cap else None,
            "step_up_threshold_amount": str(step_up_threshold),
            "step_up_risk_threshold": 0.50,
            "hold_risk_threshold": 0.85,
            "allowed_currencies": ["USD", "EUR"],
            "allowed_purpose_codes": ["TRANSFER", "PAYMENT"],
            "dual_control_roles": ["SUPERVISOR"],
        },
        is_active=True,
    )

    agent = Agent(
        id=agent_id,
        institution_id=inst_id,
        name="Test Autonomous Agent",
        owner_contact="agent-admin@bank.example.com",
        public_key="dummy_pem",
        key_algorithm="Ed25519",
        key_version=1,
        status=agent_status,
    )

    cap = Capability(
        id=uuid.uuid4(),
        agent_id=agent_id,
        name="Standard Transfer Capability",
        max_amount_per_transaction=single_limit,
        max_daily_cumulative_amount=daily_limit,
        permitted_currencies=["USD", "EUR"],
        permitted_transaction_types=["TRANSFER", "PAYMENT"],
        allowed_origin_accounts=None,
        allowed_destination_accounts=None,
        purpose_codes=["TRANSFER", "PAYMENT"],
        is_active=True,
    )

    inst = Institution(
        id=inst_id,
        institution_code="TESTBANK",
        name="Test Bank Corp",
        routing_identifier="123456789",
        status=institution_status,
    )

    origin_acct = Account(
        id=uuid.uuid4(),
        institution_id=inst_id,
        account_number="ACC-ORIGIN-001",
        account_type=AccountType.CHECKING,
        currency=currency,
        status=origin_account_status,
    )

    dest_acct = Account(
        id=uuid.uuid4(),
        institution_id=inst_id,
        account_number="ACC-DEST-002",
        account_type=AccountType.CHECKING,
        currency=currency,
        status=destination_account_status,
    )

    return policy, agent, [cap], inst, origin_acct, dest_acct


def test_deterministic_allow_outcome() -> None:
    """Verify that a compliant request produces ALLOW deterministically."""
    policy, agent, caps, inst, orig_acct, dest_acct = create_test_fixtures()
    engine = DeterministicPolicyEngine()

    intent = TransactionIntent(
        amount=Decimal("1500.0000"),
        currency="USD",
        origin_institution_code="TESTBANK",
        origin_account_number="ACC-ORIGIN-001",
        destination_institution_code="TESTBANK",
        destination_account_number="ACC-DEST-002",
        transaction_type="TRANSFER",
        purpose_code="TRANSFER",
    )

    now = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)
    result = engine.evaluate(
        policy=policy,
        agent=agent,
        capabilities=caps,
        transaction=intent,
        origin_institution=inst,
        origin_account=orig_acct,
        destination_account=dest_acct,
        spend_24h=Decimal("0.0000"),
        active_reservations_amount=Decimal("0.0000"),
        risk_signals=RiskSignals(risk_score=0.10),
        evaluation_time=now,
        credential_check_passed=True,
        credential_reasons=[],
    )

    assert result.outcome == PolicyOutcome.ALLOW
    assert "POLICY_EVALUATION_PASSED" in result.reason_codes
    assert result.applicable_rule_ids == ["RULE_DEFAULT_ALLOW"]
    assert not result.step_up_required
    assert not result.hold_required


def test_priority1_security_failure_overrides_all() -> None:
    """Security failures (e.g. signature error) must immediately DECLINE even with benign inputs."""
    policy, agent, caps, inst, orig_acct, dest_acct = create_test_fixtures()
    engine = DeterministicPolicyEngine()

    intent = TransactionIntent(
        amount=Decimal("100.0000"),
        currency="USD",
        origin_institution_code="TESTBANK",
        origin_account_number="ACC-ORIGIN-001",
        destination_institution_code="TESTBANK",
        destination_account_number="ACC-DEST-002",
        transaction_type="TRANSFER",
    )

    now = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)
    result = engine.evaluate(
        policy=policy,
        agent=agent,
        capabilities=caps,
        transaction=intent,
        origin_institution=inst,
        origin_account=orig_acct,
        destination_account=dest_acct,
        spend_24h=Decimal("0.0000"),
        active_reservations_amount=Decimal("0.0000"),
        risk_signals=RiskSignals(risk_score=0.0),
        evaluation_time=now,
        credential_check_passed=False,
        credential_reasons=["INVALID_SIGNATURE"],
    )

    assert result.outcome == PolicyOutcome.DECLINE
    assert "INVALID_SIGNATURE" in result.reason_codes
    assert "RULE_SEC_001_CREDENTIAL_VERIFICATION" in result.applicable_rule_ids


def test_priority1_inactive_agent_declines() -> None:
    """Suspended or revoked agents must produce immediate DECLINE."""
    policy, agent, caps, inst, orig_acct, dest_acct = create_test_fixtures(
        agent_status=AgentStatus.SUSPENDED
    )
    engine = DeterministicPolicyEngine()

    intent = TransactionIntent(
        amount=Decimal("100.0000"),
        currency="USD",
        origin_institution_code="TESTBANK",
        origin_account_number="ACC-ORIGIN-001",
        destination_institution_code="TESTBANK",
        destination_account_number="ACC-DEST-002",
        transaction_type="TRANSFER",
    )

    result = engine.evaluate(
        policy=policy,
        agent=agent,
        capabilities=caps,
        transaction=intent,
        origin_institution=inst,
        origin_account=orig_acct,
        destination_account=dest_acct,
        spend_24h=Decimal("0.0000"),
        active_reservations_amount=Decimal("0.0000"),
        risk_signals=RiskSignals(),
        evaluation_time=datetime.now(UTC),
        credential_check_passed=True,
        credential_reasons=[],
    )

    assert result.outcome == PolicyOutcome.DECLINE
    assert "AGENT_NOT_ACTIVE_SUSPENDED" in result.reason_codes


def test_priority2_frozen_account_declines() -> None:
    """Frozen origin account must produce immediate DECLINE."""
    policy, agent, caps, inst, orig_acct, dest_acct = create_test_fixtures(
        origin_account_status=AccountStatus.FROZEN
    )
    engine = DeterministicPolicyEngine()

    intent = TransactionIntent(
        amount=Decimal("100.0000"),
        currency="USD",
        origin_institution_code="TESTBANK",
        origin_account_number="ACC-ORIGIN-001",
        destination_institution_code="TESTBANK",
        destination_account_number="ACC-DEST-002",
        transaction_type="TRANSFER",
    )

    result = engine.evaluate(
        policy=policy,
        agent=agent,
        capabilities=caps,
        transaction=intent,
        origin_institution=inst,
        origin_account=orig_acct,
        destination_account=dest_acct,
        spend_24h=Decimal("0.0000"),
        active_reservations_amount=Decimal("0.0000"),
        risk_signals=RiskSignals(),
        evaluation_time=datetime.now(UTC),
        credential_check_passed=True,
        credential_reasons=[],
    )

    assert result.outcome == PolicyOutcome.DECLINE
    assert "ORIGIN_ACCOUNT_FROZEN" in result.reason_codes


def test_priority3_cumulative_velocity_limit_exceeded() -> None:
    """Request where spend + active reservations + amount > daily limit must DECLINE."""
    policy, agent, caps, inst, orig_acct, dest_acct = create_test_fixtures(
        daily_limit=Decimal("10000.0000")
    )
    engine = DeterministicPolicyEngine()

    intent = TransactionIntent(
        amount=Decimal("3000.0000"),
        currency="USD",
        origin_institution_code="TESTBANK",
        origin_account_number="ACC-ORIGIN-001",
        destination_institution_code="TESTBANK",
        destination_account_number="ACC-DEST-002",
        transaction_type="TRANSFER",
    )

    # 24h spend = 6000, active reservations = 2000 -> total velocity with new tx = 11000 > 10000
    result = engine.evaluate(
        policy=policy,
        agent=agent,
        capabilities=caps,
        transaction=intent,
        origin_institution=inst,
        origin_account=orig_acct,
        destination_account=dest_acct,
        spend_24h=Decimal("6000.0000"),
        active_reservations_amount=Decimal("2000.0000"),
        risk_signals=RiskSignals(),
        evaluation_time=datetime.now(UTC),
        credential_check_passed=True,
        credential_reasons=[],
    )

    assert result.outcome == PolicyOutcome.DECLINE
    assert any("CAPABILITY_DAILY_LIMIT_EXCEEDED" in r for r in result.reason_codes)


def test_priority4_policy_max_cap_declines() -> None:
    """Transaction exceeding institutional policy cap produces DECLINE."""
    policy, agent, caps, inst, orig_acct, dest_acct = create_test_fixtures(
        single_limit=Decimal("50000.0000"),
        policy_max_cap=Decimal("20000.0000"),
    )
    engine = DeterministicPolicyEngine()

    intent = TransactionIntent(
        amount=Decimal("25000.0000"),
        currency="USD",
        origin_institution_code="TESTBANK",
        origin_account_number="ACC-ORIGIN-001",
        destination_institution_code="TESTBANK",
        destination_account_number="ACC-DEST-002",
        transaction_type="TRANSFER",
    )

    result = engine.evaluate(
        policy=policy,
        agent=agent,
        capabilities=caps,
        transaction=intent,
        origin_institution=inst,
        origin_account=orig_acct,
        destination_account=dest_acct,
        spend_24h=Decimal("0.0000"),
        active_reservations_amount=Decimal("0.0000"),
        risk_signals=RiskSignals(),
        evaluation_time=datetime.now(UTC),
        credential_check_passed=True,
        credential_reasons=[],
    )

    assert result.outcome == PolicyOutcome.DECLINE
    assert "POLICY_MAX_TRANSACTION_AMOUNT_EXCEEDED" in result.reason_codes


def test_priority5_high_risk_score_produces_hold() -> None:
    """Risk score >= 0.85 produces HOLD."""
    policy, agent, caps, inst, orig_acct, dest_acct = create_test_fixtures()
    engine = DeterministicPolicyEngine()

    intent = TransactionIntent(
        amount=Decimal("1000.0000"),
        currency="USD",
        origin_institution_code="TESTBANK",
        origin_account_number="ACC-ORIGIN-001",
        destination_institution_code="TESTBANK",
        destination_account_number="ACC-DEST-002",
        transaction_type="TRANSFER",
    )

    result = engine.evaluate(
        policy=policy,
        agent=agent,
        capabilities=caps,
        transaction=intent,
        origin_institution=inst,
        origin_account=orig_acct,
        destination_account=dest_acct,
        spend_24h=Decimal("0.0000"),
        active_reservations_amount=Decimal("0.0000"),
        risk_signals=RiskSignals(risk_score=0.92),
        evaluation_time=datetime.now(UTC),
        credential_check_passed=True,
        credential_reasons=[],
    )

    assert result.outcome == PolicyOutcome.HOLD
    assert result.hold_required
    assert "HOLD_HIGH_RISK_SCORE" in result.reason_codes
    assert result.hold_workflow == "FRAUD_INVESTIGATION"


def test_priority5_velocity_warning_produces_hold() -> None:
    """Velocity anomaly risk signal produces HOLD."""
    policy, agent, caps, inst, orig_acct, dest_acct = create_test_fixtures()
    engine = DeterministicPolicyEngine()

    intent = TransactionIntent(
        amount=Decimal("1000.0000"),
        currency="USD",
        origin_institution_code="TESTBANK",
        origin_account_number="ACC-ORIGIN-001",
        destination_institution_code="TESTBANK",
        destination_account_number="ACC-DEST-002",
        transaction_type="TRANSFER",
    )

    result = engine.evaluate(
        policy=policy,
        agent=agent,
        capabilities=caps,
        transaction=intent,
        origin_institution=inst,
        origin_account=orig_acct,
        destination_account=dest_acct,
        spend_24h=Decimal("0.0000"),
        active_reservations_amount=Decimal("0.0000"),
        risk_signals=RiskSignals(velocity_warning=True),
        evaluation_time=datetime.now(UTC),
        credential_check_passed=True,
        credential_reasons=[],
    )

    assert result.outcome == PolicyOutcome.HOLD
    assert result.hold_required
    assert "HOLD_VELOCITY_ANOMALY" in result.reason_codes


def test_priority6_amount_threshold_produces_step_up() -> None:
    """Transaction amount exceeding step-up threshold produces STEP_UP dual control."""
    policy, agent, caps, inst, orig_acct, dest_acct = create_test_fixtures(
        single_limit=Decimal("20000.0000"),
        step_up_threshold=Decimal("5000.0000"),
    )
    engine = DeterministicPolicyEngine()

    intent = TransactionIntent(
        amount=Decimal("7500.0000"),  # > 5000 step up threshold
        currency="USD",
        origin_institution_code="TESTBANK",
        origin_account_number="ACC-ORIGIN-001",
        destination_institution_code="TESTBANK",
        destination_account_number="ACC-DEST-002",
        transaction_type="TRANSFER",
    )

    result = engine.evaluate(
        policy=policy,
        agent=agent,
        capabilities=caps,
        transaction=intent,
        origin_institution=inst,
        origin_account=orig_acct,
        destination_account=dest_acct,
        spend_24h=Decimal("0.0000"),
        active_reservations_amount=Decimal("0.0000"),
        risk_signals=RiskSignals(risk_score=0.20),
        evaluation_time=datetime.now(UTC),
        credential_check_passed=True,
        credential_reasons=[],
    )

    assert result.outcome == PolicyOutcome.STEP_UP
    assert result.step_up_required
    assert "STEP_UP_AMOUNT_THRESHOLD_REACHED" in result.reason_codes
    assert result.step_up_role == "SUPERVISOR"
    assert result.verification_type == "SUPERVISOR_APPROVAL"


def test_priority6_medium_risk_score_produces_step_up() -> None:
    """Medium risk score (e.g. 0.65) produces STEP_UP."""
    policy, agent, caps, inst, orig_acct, dest_acct = create_test_fixtures()
    engine = DeterministicPolicyEngine()

    intent = TransactionIntent(
        amount=Decimal("1000.0000"),
        currency="USD",
        origin_institution_code="TESTBANK",
        origin_account_number="ACC-ORIGIN-001",
        destination_institution_code="TESTBANK",
        destination_account_number="ACC-DEST-002",
        transaction_type="TRANSFER",
    )

    result = engine.evaluate(
        policy=policy,
        agent=agent,
        capabilities=caps,
        transaction=intent,
        origin_institution=inst,
        origin_account=orig_acct,
        destination_account=dest_acct,
        spend_24h=Decimal("0.0000"),
        active_reservations_amount=Decimal("0.0000"),
        risk_signals=RiskSignals(risk_score=0.65),
        evaluation_time=datetime.now(UTC),
        credential_check_passed=True,
        credential_reasons=[],
    )

    assert result.outcome == PolicyOutcome.STEP_UP
    assert result.step_up_required
    assert "STEP_UP_MEDIUM_RISK_SCORE" in result.reason_codes


def test_deterministic_reproducibility() -> None:
    """Identical evaluation parameters must produce exactly identical outcomes."""
    policy, agent, caps, inst, orig_acct, dest_acct = create_test_fixtures()
    engine = DeterministicPolicyEngine()

    intent = TransactionIntent(
        amount=Decimal("2500.0000"),
        currency="USD",
        origin_institution_code="TESTBANK",
        origin_account_number="ACC-ORIGIN-001",
        destination_institution_code="TESTBANK",
        destination_account_number="ACC-DEST-002",
        transaction_type="TRANSFER",
    )

    now = datetime(2026, 10, 19, 14, 30, 0, tzinfo=UTC)

    eval1 = engine.evaluate(
        policy=policy,
        agent=agent,
        capabilities=caps,
        transaction=intent,
        origin_institution=inst,
        origin_account=orig_acct,
        destination_account=dest_acct,
        spend_24h=Decimal("1000.0000"),
        active_reservations_amount=Decimal("500.0000"),
        risk_signals=RiskSignals(risk_score=0.25),
        evaluation_time=now,
        credential_check_passed=True,
        credential_reasons=[],
    )

    eval2 = engine.evaluate(
        policy=policy,
        agent=agent,
        capabilities=caps,
        transaction=intent,
        origin_institution=inst,
        origin_account=orig_acct,
        destination_account=dest_acct,
        spend_24h=Decimal("1000.0000"),
        active_reservations_amount=Decimal("500.0000"),
        risk_signals=RiskSignals(risk_score=0.25),
        evaluation_time=now,
        credential_check_passed=True,
        credential_reasons=[],
    )

    assert eval1.outcome == eval2.outcome == PolicyOutcome.ALLOW
    assert eval1.reason_codes == eval2.reason_codes
    assert eval1.applicable_rule_ids == eval2.applicable_rule_ids
    assert eval1.evidence["projected_total_velocity"] == eval2.evidence["projected_total_velocity"]
