"""Unit test suite for Phase 7 DRUNIX Outbox, Worker, Circuit Breaker, and Adapter Simulator."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.db.models.drunix_outbox import (
    DrunixEventType,
    DrunixOutboxEvent,
    DrunixOutboxStatus,
)
from sentinel_chain_drive.db.models.institution import Institution
from sentinel_chain_drive.db.models.policy import Policy
from sentinel_chain_drive.db.models.policy_evaluation import PolicyOutcome
from sentinel_chain_drive.integrations.drunix import (
    CircuitBreaker,
    CircuitBreakerState,
    DRUNIXMalformedResponseError,
    DRUNIXTerminalError,
    DRUNIXTimeoutError,
    DRUNIXTransientError,
    DRUNIXUncertainOutcomeError,
    MockDRUNIXAdapter,
    MockSimulationMode,
)
from sentinel_chain_drive.repositories.drunix_outbox_repository import DrunixOutboxRepository
from sentinel_chain_drive.schemas.credential import TransactionIntent
from sentinel_chain_drive.schemas.policy import (
    HoldResolutionRequest,
    PolicyEvaluationRequest,
    StepUpCompletionRequest,
)
from sentinel_chain_drive.services.drunix_worker import DrunixWorkerService
from sentinel_chain_drive.services.policy_service import PolicyService


@pytest.fixture
async def institution_id(db_session: AsyncSession) -> uuid.UUID:
    """Fixture providing an active institution."""
    inst = Institution(
        id=uuid.uuid4(),
        institution_code=f"DRUNIX_{uuid.uuid4().hex[:6].upper()}",
        name="DRUNIX Test Bank",
        routing_identifier=f"ROUT_{uuid.uuid4().hex[:8]}",
        status="ACTIVE",
    )
    db_session.add(inst)
    await db_session.flush()
    return inst.id


@pytest.fixture
def mock_adapter() -> MockDRUNIXAdapter:
    """Fixture providing a clean MockDRUNIXAdapter."""
    adapter = MockDRUNIXAdapter()
    adapter.clear()
    return adapter


@pytest.mark.asyncio
async def test_circuit_breaker_lifecycle() -> None:
    """Verify Circuit Breaker transitions: CLOSED -> OPEN -> HALF_OPEN -> CLOSED."""
    cb = CircuitBreaker(
        failure_threshold=3,
        recovery_timeout_seconds=0.1,
        half_open_success_threshold=2,
    )

    def current_state(c: CircuitBreaker) -> CircuitBreakerState:
        return c.state

    assert current_state(cb) == CircuitBreakerState.CLOSED
    assert cb.can_execute() is True

    # 1. Record 2 failures: still CLOSED
    cb.record_failure(is_transient=True)
    cb.record_failure(is_transient=True)
    assert current_state(cb) == CircuitBreakerState.CLOSED
    assert cb.can_execute() is True

    # 2. Record 3rd failure: trips to OPEN
    cb.record_failure(is_transient=True)
    assert current_state(cb) == CircuitBreakerState.OPEN
    assert cb.can_execute() is False

    # 3. Wait for recovery timeout to elapse: transitions to HALF_OPEN
    import asyncio

    await asyncio.sleep(0.15)
    assert current_state(cb) == CircuitBreakerState.HALF_OPEN
    assert cb.can_execute() is True

    # 4. Probe failure in HALF_OPEN: immediately trips back to OPEN
    cb.record_failure(is_transient=True)
    assert current_state(cb) == CircuitBreakerState.OPEN

    # 5. Wait for recovery again
    await asyncio.sleep(0.15)
    assert current_state(cb) == CircuitBreakerState.HALF_OPEN

    # 6. Two consecutive successes in HALF_OPEN: returns to CLOSED
    cb.record_success()
    assert current_state(cb) == CircuitBreakerState.HALF_OPEN
    cb.record_success()
    assert current_state(cb) == CircuitBreakerState.CLOSED
    assert cb.can_execute() is True


@pytest.mark.asyncio
async def test_mock_adapter_simulation_modes(mock_adapter: MockDRUNIXAdapter) -> None:
    """Verify all 10 simulation modes of MockDRUNIXAdapter."""
    rec_id = "test_rec_001"
    commit_hash = "a" * 64

    # 1. Normal acknowledgement
    mock_adapter.set_simulation_mode(MockSimulationMode.NORMAL)
    receipt = await mock_adapter.record_authorization_attestation(rec_id, commit_hash)
    assert receipt.tx_hash.startswith("0x")
    assert receipt.status == "ACKNOWLEDGED"

    # 2. Duplicate submission returns existing receipt
    dup_receipt = await mock_adapter.record_authorization_attestation(rec_id, commit_hash)
    assert dup_receipt.tx_hash == receipt.tx_hash

    # 3. Timeout error
    mock_adapter.set_simulation_mode(MockSimulationMode.TIMEOUT)
    with pytest.raises(DRUNIXTimeoutError):
        await mock_adapter.record_authorization_attestation("other_rec", commit_hash)

    # 4. Transient error
    mock_adapter.set_simulation_mode(MockSimulationMode.TRANSIENT_ERROR)
    with pytest.raises(DRUNIXTransientError):
        await mock_adapter.record_authorization_attestation("other_rec", commit_hash)

    # 5. Terminal error
    mock_adapter.set_simulation_mode(MockSimulationMode.TERMINAL_ERROR)
    with pytest.raises(DRUNIXTerminalError):
        await mock_adapter.record_authorization_attestation("other_rec", commit_hash)

    # 6. Malformed response error
    mock_adapter.set_simulation_mode(MockSimulationMode.MALFORMED_RESPONSE)
    with pytest.raises(DRUNIXMalformedResponseError):
        await mock_adapter.record_authorization_attestation("other_rec", commit_hash)

    # 7. Uncertain timeout: written to node, but exception raised
    mock_adapter.set_simulation_mode(MockSimulationMode.UNCERTAIN_TIMEOUT)
    uncertain_id = "rec_uncertain_999"
    with pytest.raises(DRUNIXUncertainOutcomeError):
        await mock_adapter.record_authorization_attestation(uncertain_id, commit_hash)

    # 8. Reconciliation verification: record exists externally!
    retrieved = await mock_adapter.retrieve_record(uncertain_id)
    assert retrieved is not None
    assert retrieved["commitment_hash"] == commit_hash

    # 9. Verification matches
    is_valid = await mock_adapter.verify_attestation(retrieved["tx_hash"], commit_hash)
    assert is_valid is True

    # 10. Verification detects mismatched commitment
    is_valid_wrong = await mock_adapter.verify_attestation(retrieved["tx_hash"], "b" * 64)
    assert is_valid_wrong is False


@pytest.mark.asyncio
async def test_outbox_repository_crud_and_metrics(
    db_session: AsyncSession, institution_id: uuid.UUID
) -> None:
    """Test outbox creation, claiming, delivery recording, and metrics."""
    repo = DrunixOutboxRepository(db_session)
    event_id = uuid.uuid4()

    event = await repo.create_event(
        institution_id=institution_id,
        event_type=DrunixEventType.AUTH_ATTESTATION,
        aggregate_type="POLICY_EVALUATION",
        aggregate_id=event_id,
        idempotency_key=f"idemp_{event_id}",
        commitment_hash="c" * 64,
        payload={"decision": "ALLOW", "amount": "100.00"},
    )
    assert event.status == DrunixOutboxStatus.PENDING

    # Claim pending events
    claimed = await repo.claim_pending_events(worker_id="worker_test_1", batch_size=5)
    assert len(claimed) == 1
    assert claimed[0].id == event.id
    assert claimed[0].status == DrunixOutboxStatus.PROCESSING
    assert claimed[0].locked_by == "worker_test_1"

    # Record delivery
    await repo.record_delivery(
        event_id=event.id,
        receipt_reference="0x123456",
        receipt_data={"block": 100},
    )

    updated = await repo.get_by_id(event.id)
    assert updated is not None
    assert updated.status == DrunixOutboxStatus.DELIVERED
    assert updated.receipt_reference == "0x123456"
    assert updated.locked_by is None

    # Check metrics
    metrics = await repo.get_metrics(institution_id=institution_id)
    assert metrics["total_delivered"] == 1
    assert metrics["total_pending"] == 0


@pytest.mark.asyncio
async def test_worker_retry_scheduling_and_max_attempts(
    db_session: AsyncSession, institution_id: uuid.UUID
) -> None:
    """Test worker retry scheduling and transition to TERMINAL_FAILURE after max attempts."""
    repo = DrunixOutboxRepository(db_session)
    mock_adapter = MockDRUNIXAdapter()
    mock_adapter.set_simulation_mode(MockSimulationMode.TRANSIENT_ERROR)

    worker = DrunixWorkerService(
        session=db_session,
        adapter=mock_adapter,
        base_backoff_seconds=0.01,
        max_backoff_seconds=0.05,
    )

    event_id = uuid.uuid4()
    event = await repo.create_event(
        institution_id=institution_id,
        event_type=DrunixEventType.AUTH_ATTESTATION,
        aggregate_type="POLICY_EVALUATION",
        aggregate_id=event_id,
        idempotency_key=f"retry_test_{event_id}",
        commitment_hash="d" * 64,
        payload={"decision": "ALLOW"},
        max_attempts=3,
    )

    # Attempt 1: Fails transiently -> RETRYABLE_FAILURE
    delivered = await worker.process_batch(batch_size=10)
    assert delivered == 0
    e1 = await repo.get_by_id(event.id)
    assert e1 is not None
    assert e1.status == DrunixOutboxStatus.RETRYABLE_FAILURE
    assert e1.attempt_count == 1

    # Simulate time advancing to next_attempt_at
    e1.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.flush()

    # Attempt 2: Fails transiently -> RETRYABLE_FAILURE
    await worker.process_batch(batch_size=10)
    e2 = await repo.get_by_id(event.id)
    assert e2 is not None
    assert e2.status == DrunixOutboxStatus.RETRYABLE_FAILURE
    assert e2.attempt_count == 2

    # Advance time again
    e2.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.flush()

    # Attempt 3: Max attempts reached -> TERMINAL_FAILURE
    await worker.process_batch(batch_size=10)
    e3 = await repo.get_by_id(event.id)
    assert e3 is not None
    assert e3.status == DrunixOutboxStatus.TERMINAL_FAILURE
    assert e3.attempt_count == 3


@pytest.mark.asyncio
async def test_worker_reconciliation_workflow(
    db_session: AsyncSession, institution_id: uuid.UUID
) -> None:
    """Test handling of uncertain timeouts and subsequent successful reconciliation."""
    repo = DrunixOutboxRepository(db_session)
    mock_adapter = MockDRUNIXAdapter()
    mock_adapter.set_simulation_mode(MockSimulationMode.UNCERTAIN_TIMEOUT)

    worker = DrunixWorkerService(
        session=db_session,
        adapter=mock_adapter,
        base_backoff_seconds=0.01,
    )

    event_id = uuid.uuid4()
    event = await repo.create_event(
        institution_id=institution_id,
        event_type=DrunixEventType.AUTH_ATTESTATION,
        aggregate_type="POLICY_EVALUATION",
        aggregate_id=event_id,
        idempotency_key=f"unrec_{event_id}",
        commitment_hash="e" * 64,
        payload={"decision": "ALLOW"},
    )

    # Process batch with uncertain outcome
    delivered = await worker.process_batch(batch_size=10)
    assert delivered == 0

    e = await repo.get_by_id(event.id)
    assert e is not None
    assert e.status == DrunixOutboxStatus.RECONCILIATION_REQUIRED

    # Now run reconciliation: should discover external record on the adapter
    reconciled = await worker.reconcile_event(event.id)
    assert reconciled is True

    e_reconciled = await repo.get_by_id(event.id)
    assert e_reconciled is not None
    assert e_reconciled.status == DrunixOutboxStatus.DELIVERED
    assert e_reconciled.receipt_reference is not None


@pytest.mark.asyncio
async def test_stale_lock_recovery(db_session: AsyncSession, institution_id: uuid.UUID) -> None:
    """Test that event left in PROCESSING by crashed worker is recovered after stale timeout."""
    repo = DrunixOutboxRepository(db_session)

    event = await repo.create_event(
        institution_id=institution_id,
        event_type=DrunixEventType.AUTH_ATTESTATION,
        aggregate_type="POLICY_EVALUATION",
        aggregate_id=uuid.uuid4(),
        idempotency_key=f"crash_test_{uuid.uuid4()}",
        commitment_hash="f" * 64,
        payload={"decision": "ALLOW"},
    )

    # Simulate worker crash: event is PROCESSING and locked_at is 10 minutes in the past
    event.status = DrunixOutboxStatus.PROCESSING
    event.locked_by = "crashed_worker_99"
    event.locked_at = datetime.now(UTC) - timedelta(minutes=10)
    await db_session.flush()

    # New worker claims with stale_lock_seconds=300 (5 minutes)
    claimed = await repo.claim_pending_events(
        worker_id="new_worker_1", batch_size=5, stale_lock_seconds=300
    )
    # The crashed event must be recovered!
    claimed_ids = [c.id for c in claimed]
    assert event.id in claimed_ids
    recovered_event = next(c for c in claimed if c.id == event.id)
    assert recovered_event.locked_by == "new_worker_1"


@pytest.mark.asyncio
async def test_declined_and_held_operations_never_create_outbox_events(
    db_session: AsyncSession, institution_id: uuid.UUID
) -> None:
    """Verify security invariant: DECLINE and HOLD operations must NEVER create outbox events."""
    policy_service = PolicyService(db_session)

    # Ensure no outbox events exist initially for this institution
    stmt = select(DrunixOutboxEvent).where(DrunixOutboxEvent.institution_id == institution_id)
    initial_events = (await db_session.execute(stmt)).scalars().all()
    assert len(initial_events) == 0

    # Submit an invalid request that declines (e.g. amount <= 0 or invalid credentials)
    # To test without mock credentials, test the fail-closed decline path
    req = PolicyEvaluationRequest(
        institution_id=institution_id,
        agent_id=uuid.uuid4(),
        credential_id="non_existent_cred",
        idempotency_key=f"decline_test_{uuid.uuid4()}",
        nonce=f"nonce_{uuid.uuid4().hex}",
        request_timestamp=datetime.now(UTC),
        signature="invalid_sig",
        transaction=TransactionIntent(
            transaction_type="TRANSFER",
            origin_institution_code="BANK_A",
            origin_account_number="ACCT_001",
            destination_institution_code="BANK_B",
            destination_account_number="ACCT_002",
            amount=Decimal("50.00"),
            currency="USD",
            purpose_code="PAYMENT",
        ),
    )

    resp = await policy_service.evaluate_transaction_policy(req)
    assert resp.decision == PolicyOutcome.DECLINE

    # Confirm that NO outbox events were created!
    after_events = (await db_session.execute(stmt)).scalars().all()
    assert len(after_events) == 0


@pytest.mark.asyncio
async def test_step_up_approval_creates_outbox_event(
    db_session: AsyncSession, institution_id: uuid.UUID
) -> None:
    """Verify that approving a step-up challenge atomically enqueues an outbox event."""
    from sentinel_chain_drive.db.models.policy_evaluation import StepUpChallenge, StepUpStatus

    policy = Policy(
        id=uuid.uuid4(),
        institution_id=institution_id,
        policy_code="STEPUP_TEST_POL",
        name="StepUp Test Policy",
        version=1,
        priority=100,
        rules={},
        is_active=True,
    )
    db_session.add(policy)
    await db_session.flush()

    challenge_id = uuid.uuid4()
    eval_id = uuid.uuid4()
    agent_id = uuid.uuid4()

    from sentinel_chain_drive.db.models.policy_evaluation import PolicyEvaluationRecord

    eval_rec = PolicyEvaluationRecord(
        id=eval_id,
        idempotency_key=f"idemp_{eval_id}",
        institution_id=institution_id,
        agent_id=agent_id,
        policy_id=policy.id,
        policy_version=1,
        decision=PolicyOutcome.STEP_UP,
        transaction_intent_hash="hash_intent_123",
        reason_codes=["STEP_UP_AMOUNT_THRESHOLD_REACHED"],
        amount=Decimal("15000.00"),
        currency="USD",
    )
    db_session.add(eval_rec)

    challenge = StepUpChallenge(
        id=challenge_id,
        policy_evaluation_id=eval_id,
        transaction_intent_hash="hash_intent_123",
        policy_id=policy.id,
        policy_version=1,
        initiating_agent_id=agent_id,
        institution_id=institution_id,
        verification_type="SUPERVISOR_APPROVAL",
        required_role="SUPERVISOR",
        status=StepUpStatus.PENDING,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(challenge)
    await db_session.flush()

    policy_service = PolicyService(db_session)
    comp_req = StepUpCompletionRequest(
        approver_id="supervisor_alice",
        decision="APPROVED",
        reason="Verified transaction intent with authorized manager.",
    )
    res = await policy_service.complete_step_up(challenge_id, comp_req)
    assert res.status == StepUpStatus.COMPLETED

    # Verify that an outbox event was atomically enqueued for this approval!
    outbox_repo = DrunixOutboxRepository(db_session)
    ev = await outbox_repo.get_by_idempotency_key(
        institution_id=institution_id, idempotency_key=f"drunix:auth:{eval_id}"
    )
    assert ev is not None
    assert ev.event_type == DrunixEventType.AUTH_ATTESTATION
    assert ev.status == DrunixOutboxStatus.PENDING
    assert ev.payload["approver_id"] == "supervisor_alice"
    assert ev.payload["decision"] == "ALLOW"


@pytest.mark.asyncio
async def test_hold_release_creates_outbox_event(
    db_session: AsyncSession, institution_id: uuid.UUID
) -> None:
    """Verify that releasing a fraud review hold atomically enqueues an outbox event."""
    from sentinel_chain_drive.db.models.policy_evaluation import (
        HoldStatus,
        PolicyEvaluationRecord,
        TransactionHold,
    )

    policy = Policy(
        id=uuid.uuid4(),
        institution_id=institution_id,
        policy_code="HOLD_TEST_POL",
        name="Hold Test Policy",
        version=1,
        priority=100,
        rules={},
        is_active=True,
    )
    db_session.add(policy)
    await db_session.flush()

    hold_id = uuid.uuid4()
    eval_id = uuid.uuid4()
    agent_id = uuid.uuid4()

    eval_rec = PolicyEvaluationRecord(
        id=eval_id,
        idempotency_key=f"idemp_{eval_id}",
        institution_id=institution_id,
        agent_id=agent_id,
        policy_id=policy.id,
        policy_version=1,
        decision=PolicyOutcome.HOLD,
        transaction_intent_hash="hold_hash_456",
        reason_codes=["HOLD_VELOCITY_ANOMALY"],
        amount=Decimal("5000.00"),
        currency="USD",
    )
    db_session.add(eval_rec)

    hold = TransactionHold(
        id=hold_id,
        policy_evaluation_id=eval_id,
        transaction_intent_hash="hold_hash_456",
        institution_id=institution_id,
        hold_reason="Suspicious rapid transfer pattern",
        review_workflow="FRAUD_DESK",
        status=HoldStatus.ACTIVE,
    )
    db_session.add(hold)
    await db_session.flush()

    policy_service = PolicyService(db_session)
    resolution_req = HoldResolutionRequest(
        resolution="RELEASE",
        resolved_by="analyst_bob",
        notes="Legitimate vendor payment confirmed via out-of-band contact.",
    )
    res = await policy_service.resolve_transaction_hold(
        hold_id=hold_id, data=resolution_req, institution_id=institution_id
    )
    assert res.status == HoldStatus.RELEASED

    # Verify outbox event enqueued
    outbox_repo = DrunixOutboxRepository(db_session)
    ev = await outbox_repo.get_by_idempotency_key(
        institution_id=institution_id, idempotency_key=f"drunix:auth:{eval_id}"
    )
    assert ev is not None
    assert ev.event_type == DrunixEventType.AUTH_ATTESTATION
    assert ev.payload["resolved_by"] == "analyst_bob"
    assert ev.payload["decision"] == "ALLOW"


@pytest.mark.asyncio
async def test_institution_isolation_in_outbox_metrics(
    db_session: AsyncSession, institution_id: uuid.UUID
) -> None:
    """Verify that outbox metrics strictly respect institution tenant scoping."""
    repo = DrunixOutboxRepository(db_session)

    other_inst_id = uuid.uuid4()
    other_inst = Institution(
        id=other_inst_id,
        institution_code=f"OTHER_{uuid.uuid4().hex[:6].upper()}",
        name="Other Bank",
        routing_identifier=f"ROUT_{uuid.uuid4().hex[:8]}",
        status="ACTIVE",
    )
    db_session.add(other_inst)
    await db_session.flush()

    # Create 2 events for institution_id
    await repo.create_event(
        institution_id=institution_id,
        event_type=DrunixEventType.AUTH_ATTESTATION,
        aggregate_type="POLICY_EVALUATION",
        aggregate_id=uuid.uuid4(),
        idempotency_key=f"inst_a_1_{uuid.uuid4()}",
        commitment_hash="1" * 64,
        payload={"data": 1},
    )
    await repo.create_event(
        institution_id=institution_id,
        event_type=DrunixEventType.AUTH_ATTESTATION,
        aggregate_type="POLICY_EVALUATION",
        aggregate_id=uuid.uuid4(),
        idempotency_key=f"inst_a_2_{uuid.uuid4()}",
        commitment_hash="2" * 64,
        payload={"data": 2},
    )

    # Create 1 event for other_inst_id
    await repo.create_event(
        institution_id=other_inst_id,
        event_type=DrunixEventType.AUTH_ATTESTATION,
        aggregate_type="POLICY_EVALUATION",
        aggregate_id=uuid.uuid4(),
        idempotency_key=f"inst_b_1_{uuid.uuid4()}",
        commitment_hash="3" * 64,
        payload={"data": 3},
    )

    metrics_a = await repo.get_metrics(institution_id=institution_id)
    assert metrics_a["total_pending"] == 2

    metrics_b = await repo.get_metrics(institution_id=other_inst_id)
    assert metrics_b["total_pending"] == 1

    # Global metrics without institution scoping
    metrics_global = await repo.get_metrics(institution_id=None)
    assert metrics_global["total_pending"] >= 3


@pytest.mark.asyncio
async def test_drunix_status_api_endpoint(client_with_db: Any, institution_id: uuid.UUID) -> None:
    """Verify that GET /api/v1/drunix/status returns sanitized operational telemetry."""
    response = await client_with_db.get(
        "/api/v1/drunix/status",
        headers={"X-Institution-ID": str(institution_id)},
    )
    assert response.status_code == 200
    data = response.json()

    assert "worker_id" in data
    assert "circuit_breaker" in data
    assert data["circuit_breaker"]["state"] in ["CLOSED", "OPEN", "HALF_OPEN"]
    assert "outbox" in data
    assert "total_pending" in data["outbox"]
    assert "node_available" in data
    # Ensure no credentials or raw secrets are present
    raw_str = str(data)
    assert "password" not in raw_str.lower()
    assert "secret" not in raw_str.lower()
    assert "private_key" not in raw_str.lower()
