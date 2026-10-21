"""Integration test suite for Phase 8 Event Ordering, Concurrency, and Consumer Idempotency."""

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from sentinel_chain_drive.db.base import Base
from sentinel_chain_drive.db.models.drunix_outbox import (
    DrunixEventType,
    DrunixOutboxStatus,
)
from sentinel_chain_drive.db.models.institution import Institution
from sentinel_chain_drive.repositories.drunix_outbox_repository import DrunixOutboxRepository
from sentinel_chain_drive.repositories.processed_event_repository import ProcessedEventRepository
from sentinel_chain_drive.services.drunix_worker import DrunixWorkerService


@pytest.fixture
async def event_ordering_engine() -> AsyncGenerator[AsyncEngine]:
    """Engine for outbox ordering and concurrency testing."""
    postgres_url = os.environ.get("TEST_POSTGRES_URL")
    if postgres_url:
        engine = create_async_engine(postgres_url, pool_size=10, max_overflow=5)
    else:
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def session_factory(
    event_ordering_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Provides independent async sessions for multi-worker concurrent operations."""
    return async_sessionmaker(
        bind=event_ordering_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


@pytest.fixture
async def shared_institution_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> uuid.UUID:
    """Creates a shared active institution for ordering tests."""
    async with session_factory() as session:
        inst = Institution(
            id=uuid.uuid4(),
            institution_code=f"ORDER_{uuid.uuid4().hex[:6].upper()}",
            name="Ordering Test Bank",
            routing_identifier=f"ROUT_{uuid.uuid4().hex[:8]}",
            status="ACTIVE",
        )
        session.add(inst)
        await session.commit()
        return inst.id


@pytest.mark.asyncio
async def test_stream_ordering_predecessor_blocks_successor(
    session_factory: async_sessionmaker[AsyncSession],
    shared_institution_id: uuid.UUID,
) -> None:
    """Verify that a later event in a stream (seq 2) cannot be claimed while seq 1 is pending."""
    ordering_key = f"tx:stream_{uuid.uuid4().hex[:8]}"

    async with session_factory() as session:
        repo = DrunixOutboxRepository(session)
        # Sequence 1: Transaction Submitted
        ev1 = await repo.create_event(
            institution_id=shared_institution_id,
            event_type=DrunixEventType.TRANSACTION_SUBMITTED,
            aggregate_type="TRANSACTION",
            aggregate_id=uuid.uuid4(),
            idempotency_key=f"idemp_seq1_{uuid.uuid4().hex}",
            payload={"step": 1},
            commitment_hash="hash_seq1",
            ordering_key=ordering_key,
            sequence_number=1,
        )
        # Sequence 2: Policy Authorized (depends on sequence 1)
        ev2 = await repo.create_event(
            institution_id=shared_institution_id,
            event_type=DrunixEventType.AUTH_ATTESTATION,
            aggregate_type="TRANSACTION",
            aggregate_id=uuid.uuid4(),
            idempotency_key=f"idemp_seq2_{uuid.uuid4().hex}",
            payload={"step": 2},
            commitment_hash="hash_seq2",
            ordering_key=ordering_key,
            sequence_number=2,
        )
        await session.commit()
        ev1_id = ev1.id
        ev2_id = ev2.id

    # Worker 1 claims pending events
    async with session_factory() as session:
        repo = DrunixOutboxRepository(session)
        claimed = await repo.claim_pending_events(
            worker_id="worker-1",
            batch_size=10,
            stale_lock_seconds=30,
        )
        claimed_ids = [e.id for e in claimed]

        # Sequence 1 must be claimed; Sequence 2 MUST NOT be claimed because seq 1 is not DELIVERED
        assert ev1_id in claimed_ids
        assert ev2_id not in claimed_ids

        # Mark Sequence 1 as DELIVERED
        await repo.record_delivery(
            event_id=ev1_id,
            receipt_reference="REC-DELIV-001",
        )

    # Worker 2 now claims pending events; Sequence 2 is now unblocked
    async with session_factory() as session:
        repo = DrunixOutboxRepository(session)
        claimed_round_2 = await repo.claim_pending_events(
            worker_id="worker-2",
            batch_size=10,
            stale_lock_seconds=30,
        )
        claimed_round_2_ids = [e.id for e in claimed_round_2]

        assert ev2_id in claimed_round_2_ids


@pytest.mark.asyncio
async def test_consumer_idempotency_tracking(
    session_factory: async_sessionmaker[AsyncSession],
    shared_institution_id: uuid.UUID,
) -> None:
    """Verify that ProcessedEventRepository prevents duplicate processing by consumers."""
    event_id = uuid.uuid4()
    consumer = "DRUNIX_LEDGER_ADAPTER"

    async with session_factory() as session:
        proc_repo = ProcessedEventRepository(session)

        # 1. First check: not processed
        assert await proc_repo.is_processed(consumer, event_id) is False

        # 2. Record processing
        recorded = await proc_repo.record_processed(
            consumer_name=consumer,
            event_id=event_id,
            institution_id=shared_institution_id,
            correlation_id="corr_test_001",
        )
        await session.commit()
        assert recorded is True

    # 3. Second session check: now marked as processed
    async with session_factory() as session:
        proc_repo = ProcessedEventRepository(session)
        assert await proc_repo.is_processed(consumer, event_id) is True

        # Attempt duplicate insert should return False (idempotent duplicate prevented)
        duplicate_recorded = await proc_repo.record_processed(
            consumer_name=consumer,
            event_id=event_id,
            institution_id=shared_institution_id,
        )
        assert duplicate_recorded is False


@pytest.mark.asyncio
async def test_concurrent_workers_respect_stream_ordering(
    session_factory: async_sessionmaker[AsyncSession],
    shared_institution_id: uuid.UUID,
) -> None:
    """Verify concurrent workers never process dependent events out of order."""
    ordering_key = f"tx:concurrent_{uuid.uuid4().hex[:8]}"

    # Create 3-step stream: 1 -> 2 -> 3
    async with session_factory() as session:
        repo = DrunixOutboxRepository(session)
        for seq in range(1, 4):
            await repo.create_event(
                institution_id=shared_institution_id,
                event_type=DrunixEventType.AUTH_ATTESTATION,
                aggregate_type="TRANSACTION",
                aggregate_id=uuid.uuid4(),
                idempotency_key=f"idemp_chain_{seq}_{uuid.uuid4().hex}",
                payload={"step": seq},
                commitment_hash=f"hash_chain_{seq}",
                ordering_key=ordering_key,
                sequence_number=seq,
            )
        await session.commit()

    # Simulate 3 concurrent workers attempting to claim
    async def worker_claim(worker_id: str) -> list[int]:
        async with session_factory() as session:
            repo = DrunixOutboxRepository(session)
            events = await repo.claim_pending_events(
                worker_id=worker_id,
                batch_size=5,
                stale_lock_seconds=30,
            )
            seqs = [
                e.sequence_number
                for e in events
                if e.ordering_key == ordering_key and e.sequence_number is not None
            ]
            await session.commit()
            return seqs

    results = await asyncio.gather(
        worker_claim("worker-a"),
        worker_claim("worker-b"),
        worker_claim("worker-c"),
    )

    all_claimed_seqs = [s for sub in results for s in sub]
    # Only sequence 1 should have been claimed in this initial round!
    assert all_claimed_seqs == [1]


@pytest.mark.asyncio
async def test_poison_message_transitions_to_terminal_failure(
    session_factory: async_sessionmaker[AsyncSession],
    shared_institution_id: uuid.UUID,
) -> None:
    """Verify that an unprocessable event exceeding max attempts transitions to TERMINAL_FAILURE."""
    async with session_factory() as session:
        repo = DrunixOutboxRepository(session)
        event = await repo.create_event(
            institution_id=shared_institution_id,
            event_type=DrunixEventType.AUTH_ATTESTATION,
            aggregate_type="POLICY",
            aggregate_id=uuid.uuid4(),
            idempotency_key=f"idemp_poison_{uuid.uuid4().hex}",
            payload={"corrupt": "data"},
            commitment_hash="hash_poison",
            max_attempts=3,
        )
        await session.commit()
        event_id = event.id

    # Simulate 3 failed attempts
    for attempt in range(1, 4):
        async with session_factory() as session:
            repo = DrunixOutboxRepository(session)
            claimed = await repo.claim_pending_events(
                worker_id=f"worker-attempt-{attempt}",
                batch_size=1,
            )
            assert len(claimed) == 1
            ev = claimed[0]
            assert ev.id == event_id

            if attempt == 3:
                await repo.record_terminal_failure(
                    event_id=ev.id,
                    error_category="DRUNIX_TERMINAL_ERROR",
                    error_message="Simulation rejected corrupt payload",
                )
            else:
                await repo.record_retryable_failure(
                    event_id=ev.id,
                    error_category="DRUNIX_RETRYABLE_ERROR",
                    error_message="Transient simulation failure",
                    next_attempt_at=datetime.now(UTC),
                )

    # Verify event is now in TERMINAL_FAILURE
    async with session_factory() as session:
        repo = DrunixOutboxRepository(session)
        terminal_ev = await repo.get_by_id(event_id)
        assert terminal_ev is not None
        assert terminal_ev.status == DrunixOutboxStatus.TERMINAL_FAILURE
        assert terminal_ev.attempt_count == 3


@pytest.mark.asyncio
async def test_operational_visibility_metrics(
    session_factory: async_sessionmaker[AsyncSession],
    shared_institution_id: uuid.UUID,
) -> None:
    """Verify operational status overview includes all Phase 8 reliability metrics."""
    async with session_factory() as session:
        worker = DrunixWorkerService(session=session)
        overview = await worker.get_status_overview(institution_id=shared_institution_id)

        assert "outbox" in overview
        outbox_data = overview["outbox"]
        assert "total_pending" in outbox_data
        assert "total_processing" in outbox_data
        assert "total_retries" in outbox_data
        assert "replay_operations_total" in outbox_data
        assert "stale_claims_recovered_total" in outbox_data
        assert "average_processing_latency_ms" in overview
        assert "backpressure_active" in overview


@pytest.mark.asyncio
async def test_concurrent_duplicate_sequence_assignment_and_insertion(
    session_factory: async_sessionmaker[AsyncSession],
    shared_institution_id: uuid.UUID,
) -> None:
    """Verify that duplicate sequence numbers for the same ordering key are strictly rejected."""
    ordering_key = f"tx:duplicate_guard_{uuid.uuid4().hex[:8]}"

    # 1. Insert sequence 1 successfully
    async with session_factory() as session:
        repo = DrunixOutboxRepository(session)
        await repo.create_event(
            institution_id=shared_institution_id,
            event_type=DrunixEventType.TRANSACTION_SUBMITTED,
            aggregate_type="TRANSACTION",
            aggregate_id=uuid.uuid4(),
            idempotency_key=f"idemp_orig_{uuid.uuid4().hex}",
            payload={"step": 1},
            commitment_hash="hash_orig",
            ordering_key=ordering_key,
            sequence_number=1,
        )
        await session.commit()

    # 2. Attempt duplicate insertion of sequence 1 with different idempotency key
    async with session_factory() as session:
        repo = DrunixOutboxRepository(session)
        with pytest.raises(IntegrityError):
            await repo.create_event(
                institution_id=shared_institution_id,
                event_type=DrunixEventType.AUTH_ATTESTATION,
                aggregate_type="TRANSACTION",
                aggregate_id=uuid.uuid4(),
                idempotency_key=f"idemp_dup_{uuid.uuid4().hex}",
                payload={"step": "duplicate"},
                commitment_hash="hash_dup",
                ordering_key=ordering_key,
                sequence_number=1,
            )
            await session.commit()

    # 3. Verify nullable ordering_key and sequence_number can be inserted multiple times
    async with session_factory() as session:
        repo = DrunixOutboxRepository(session)
        for i in range(3):
            await repo.create_event(
                institution_id=shared_institution_id,
                event_type=DrunixEventType.FRAUD_ALERT_RAISED,
                aggregate_type="ALERT",
                aggregate_id=uuid.uuid4(),
                idempotency_key=f"idemp_null_{i}_{uuid.uuid4().hex}",
                payload={"null_seq": i},
                commitment_hash=f"hash_null_{i}",
                ordering_key=None,
                sequence_number=None,
            )
        await session.commit()


@pytest.mark.asyncio
async def test_independent_ordering_keys_process_in_parallel(
    session_factory: async_sessionmaker[AsyncSession],
    shared_institution_id: uuid.UUID,
) -> None:
    """Verify that independent ordering keys do not block each other."""
    key_a = f"tx:stream_a_{uuid.uuid4().hex[:8]}"
    key_b = f"tx:stream_b_{uuid.uuid4().hex[:8]}"

    async with session_factory() as session:
        repo = DrunixOutboxRepository(session)
        # Stream A: Seq 1 and 2
        a1 = await repo.create_event(
            institution_id=shared_institution_id,
            event_type=DrunixEventType.TRANSACTION_SUBMITTED,
            aggregate_type="TRANSACTION",
            aggregate_id=uuid.uuid4(),
            idempotency_key=f"idemp_a1_{uuid.uuid4().hex}",
            payload={"stream": "A", "seq": 1},
            commitment_hash="hash_a1",
            ordering_key=key_a,
            sequence_number=1,
        )
        await repo.create_event(
            institution_id=shared_institution_id,
            event_type=DrunixEventType.AUTH_ATTESTATION,
            aggregate_type="TRANSACTION",
            aggregate_id=uuid.uuid4(),
            idempotency_key=f"idemp_a2_{uuid.uuid4().hex}",
            payload={"stream": "A", "seq": 2},
            commitment_hash="hash_a2",
            ordering_key=key_a,
            sequence_number=2,
        )
        # Stream B: Seq 1 and 2
        b1 = await repo.create_event(
            institution_id=shared_institution_id,
            event_type=DrunixEventType.TRANSACTION_SUBMITTED,
            aggregate_type="TRANSACTION",
            aggregate_id=uuid.uuid4(),
            idempotency_key=f"idemp_b1_{uuid.uuid4().hex}",
            payload={"stream": "B", "seq": 1},
            commitment_hash="hash_b1",
            ordering_key=key_b,
            sequence_number=1,
        )
        b2 = await repo.create_event(
            institution_id=shared_institution_id,
            event_type=DrunixEventType.AUTH_ATTESTATION,
            aggregate_type="TRANSACTION",
            aggregate_id=uuid.uuid4(),
            idempotency_key=f"idemp_b2_{uuid.uuid4().hex}",
            payload={"stream": "B", "seq": 2},
            commitment_hash="hash_b2",
            ordering_key=key_b,
            sequence_number=2,
        )
        await session.commit()
        a1_id, b1_id, b2_id = a1.id, b1.id, b2.id

    # Simulate: Stream A seq 1 enters retryable failure (blocked temporarily)
    async with session_factory() as session:
        repo = DrunixOutboxRepository(session)
        await repo.record_retryable_failure(
            event_id=a1_id,
            error_category="SIMULATED_RETRYABLE",
            error_message="Stream A delayed",
            next_attempt_at=datetime.now(UTC),
        )

    # Stream B should be completely unblocked and proceed to claim both b1 and then b2
    async with session_factory() as session:
        repo = DrunixOutboxRepository(session)
        claimed = await repo.claim_pending_events(worker_id="worker-b", batch_size=10)
        claimed_ids = {e.id for e in claimed}
        assert b1_id in claimed_ids

        # Deliver b1
        await repo.record_delivery(event_id=b1_id, receipt_reference="REC-B1")

    # Now b2 can be claimed even while Stream A seq 1 is still failing
    async with session_factory() as session:
        repo = DrunixOutboxRepository(session)
        claimed_round_2 = await repo.claim_pending_events(worker_id="worker-b2", batch_size=10)
        claimed_round_2_ids = {e.id for e in claimed_round_2}
        assert b2_id in claimed_round_2_ids


@pytest.mark.asyncio
async def test_terminal_failure_blocks_stream_until_replayed_or_operator_resolution(
    session_factory: async_sessionmaker[AsyncSession],
    shared_institution_id: uuid.UUID,
) -> None:
    """Verify terminal failure blocks successors until explicit operator replay occurs."""
    ordering_key = f"tx:terminal_stream_{uuid.uuid4().hex[:8]}"

    async with session_factory() as session:
        repo = DrunixOutboxRepository(session)
        ev1 = await repo.create_event(
            institution_id=shared_institution_id,
            event_type=DrunixEventType.TRANSACTION_SUBMITTED,
            aggregate_type="TRANSACTION",
            aggregate_id=uuid.uuid4(),
            idempotency_key=f"idemp_term1_{uuid.uuid4().hex}",
            payload={"step": 1},
            commitment_hash="hash_term1",
            ordering_key=ordering_key,
            sequence_number=1,
        )
        ev2 = await repo.create_event(
            institution_id=shared_institution_id,
            event_type=DrunixEventType.AUTH_ATTESTATION,
            aggregate_type="TRANSACTION",
            aggregate_id=uuid.uuid4(),
            idempotency_key=f"idemp_term2_{uuid.uuid4().hex}",
            payload={"step": 2},
            commitment_hash="hash_term2",
            ordering_key=ordering_key,
            sequence_number=2,
        )
        await session.commit()
        ev1_id, ev2_id = ev1.id, ev2.id

    # 1. Claim ev1 and mark as TERMINAL_FAILURE
    async with session_factory() as session:
        repo = DrunixOutboxRepository(session)
        claimed = await repo.claim_pending_events(worker_id="worker-term", batch_size=1)
        assert len(claimed) == 1 and claimed[0].id == ev1_id
        await repo.record_terminal_failure(
            event_id=ev1_id,
            error_category="UNRECOVERABLE_REJECTION",
            error_message="Permanent payload rejection",
        )

    # 2. Worker tries to claim: ev2 MUST NOT be claimed because predecessor is in TERMINAL_FAILURE!
    async with session_factory() as session:
        repo = DrunixOutboxRepository(session)
        blocked_claim = await repo.claim_pending_events(
            worker_id="worker-term-blocked",
            batch_size=10,
        )
        blocked_ids = {e.id for e in blocked_claim}
        assert ev2_id not in blocked_ids

    # 3. Operator intervenes: reviews and triggers manual replay on ev1
    async with session_factory() as session:
        repo = DrunixOutboxRepository(session)
        replayed_ev1 = await repo.replay_event(
            event_id=ev1_id,
            requesting_institution_id=shared_institution_id,
            actor="compliance_officer_alice",
            reason="Payload corrected out-of-band by compliance team",
        )
        assert replayed_ev1.status == DrunixOutboxStatus.PENDING
        assert replayed_ev1.replayed_by == "compliance_officer_alice"
        assert replayed_ev1.replay_count == 1

    # 4. Worker now claims replayed ev1 and delivers it
    async with session_factory() as session:
        repo = DrunixOutboxRepository(session)
        claimed_replayed = await repo.claim_pending_events(
            worker_id="worker-term-retry",
            batch_size=10,
        )
        assert ev1_id in {e.id for e in claimed_replayed}
        await repo.record_delivery(event_id=ev1_id, receipt_reference="REC-REPLAYED-001")

    # 5. Now ev2 is finally unblocked and claimed
    async with session_factory() as session:
        repo = DrunixOutboxRepository(session)
        unblocked_claim = await repo.claim_pending_events(
            worker_id="worker-term-unblocked",
            batch_size=10,
        )
        assert ev2_id in {e.id for e in unblocked_claim}
