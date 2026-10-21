"""Unit test suite for Phase 8 Event Replay, Tenant Isolation, and Replay Audit Logging."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.core.errors import AppException
from sentinel_chain_drive.db.models.audit_log import AuditLog
from sentinel_chain_drive.db.models.drunix_outbox import (
    DrunixEventType,
    DrunixOutboxStatus,
)
from sentinel_chain_drive.db.models.institution import Institution
from sentinel_chain_drive.repositories.drunix_outbox_repository import DrunixOutboxRepository


@pytest.fixture
async def inst_a(db_session: AsyncSession) -> Institution:
    """Fixture providing Bank A."""
    inst = Institution(
        id=uuid.uuid4(),
        institution_code="BANK_A",
        name="Institution Alpha",
        routing_identifier=f"ROUT_{uuid.uuid4().hex[:8]}",
        status="ACTIVE",
    )
    db_session.add(inst)
    await db_session.flush()
    return inst


@pytest.fixture
async def inst_b(db_session: AsyncSession) -> Institution:
    """Fixture providing Bank B."""
    inst = Institution(
        id=uuid.uuid4(),
        institution_code="BANK_B",
        name="Institution Beta",
        routing_identifier=f"ROUT_{uuid.uuid4().hex[:8]}",
        status="ACTIVE",
    )
    db_session.add(inst)
    await db_session.flush()
    return inst


@pytest.mark.asyncio
async def test_replay_eligible_terminal_failure_event(
    db_session: AsyncSession,
    inst_a: Institution,
) -> None:
    """Verify that a TERMINAL_FAILURE event can be replayed by its owning institution."""
    repo = DrunixOutboxRepository(db_session)
    event = await repo.create_event(
        institution_id=inst_a.id,
        event_type=DrunixEventType.AUTH_ATTESTATION,
        aggregate_type="POLICY",
        aggregate_id=uuid.uuid4(),
        idempotency_key=f"idemp_replay_{uuid.uuid4().hex}",
        payload={"result": "FAILED"},
        commitment_hash="hash" + uuid.uuid4().hex[:12],
    )
    # Transition to TERMINAL_FAILURE
    event.status = DrunixOutboxStatus.TERMINAL_FAILURE
    event.attempt_count = 5
    await db_session.flush()

    # Replay event
    replayed = await repo.replay_event(
        event_id=event.id,
        requesting_institution_id=inst_a.id,
        actor="test-operator@banka.com",
    )
    assert replayed.status == DrunixOutboxStatus.PENDING
    assert replayed.attempt_count == 0
    assert replayed.replay_count == 1
    assert replayed.replayed_by == "test-operator@banka.com"
    assert replayed.last_replayed_at is not None

    # Check audit log record was created
    audit_stmt = select(AuditLog).where(
        AuditLog.event_type == "OUTBOX_EVENT_REPLAYED",
        AuditLog.actor == "test-operator@banka.com",
    )
    audit_res = await db_session.execute(audit_stmt)
    audit_entry = audit_res.scalar_one_or_none()
    assert audit_entry is not None
    assert audit_entry.actor == "test-operator@banka.com"
    assert audit_entry.details is not None
    assert audit_entry.details["event_id"] == str(event.id)
    assert audit_entry.details["institution_id"] == str(inst_a.id)


@pytest.mark.asyncio
async def test_replay_ineligible_pending_event_rejected(
    db_session: AsyncSession,
    inst_a: Institution,
) -> None:
    """Verify that a PENDING event cannot be replayed (only failed events are eligible)."""
    repo = DrunixOutboxRepository(db_session)
    event = await repo.create_event(
        institution_id=inst_a.id,
        event_type=DrunixEventType.AUTH_ATTESTATION,
        aggregate_type="POLICY",
        aggregate_id=uuid.uuid4(),
        idempotency_key=f"idemp_replay_{uuid.uuid4().hex}",
        payload={"result": "PENDING"},
        commitment_hash="hash" + uuid.uuid4().hex[:12],
    )
    assert event.status == DrunixOutboxStatus.PENDING

    with pytest.raises(AppException) as exc_info:
        await repo.replay_event(
            event_id=event.id,
            requesting_institution_id=inst_a.id,
        )
    assert exc_info.value.status_code == 400
    assert "not eligible for replay" in str(exc_info.value)


@pytest.mark.asyncio
async def test_replay_ineligible_delivered_event_rejected(
    db_session: AsyncSession,
    inst_a: Institution,
) -> None:
    """Verify that a DELIVERED event cannot be replayed."""
    repo = DrunixOutboxRepository(db_session)
    event = await repo.create_event(
        institution_id=inst_a.id,
        event_type=DrunixEventType.AUTH_ATTESTATION,
        aggregate_type="POLICY",
        aggregate_id=uuid.uuid4(),
        idempotency_key=f"idemp_replay_{uuid.uuid4().hex}",
        payload={"result": "DELIVERED"},
        commitment_hash="hash" + uuid.uuid4().hex[:12],
    )
    event.status = DrunixOutboxStatus.DELIVERED
    await db_session.flush()

    with pytest.raises(AppException) as exc_info:
        await repo.replay_event(
            event_id=event.id,
            requesting_institution_id=inst_a.id,
        )
    assert exc_info.value.status_code == 400
    assert "not eligible for replay" in str(exc_info.value)


@pytest.mark.asyncio
async def test_replay_cross_institution_unauthorized(
    db_session: AsyncSession,
    inst_a: Institution,
    inst_b: Institution,
) -> None:
    """Verify that Institution B cannot replay an event owned by Institution A."""
    repo = DrunixOutboxRepository(db_session)
    event = await repo.create_event(
        institution_id=inst_a.id,
        event_type=DrunixEventType.AUTH_ATTESTATION,
        aggregate_type="POLICY",
        aggregate_id=uuid.uuid4(),
        idempotency_key=f"idemp_cross_{uuid.uuid4().hex}",
        payload={"result": "FAILED"},
        commitment_hash="hash" + uuid.uuid4().hex[:12],
    )
    event.status = DrunixOutboxStatus.TERMINAL_FAILURE
    await db_session.flush()

    # Attempt replay as Institution B
    with pytest.raises(AppException) as exc_info:
        await repo.replay_event(
            event_id=event.id,
            requesting_institution_id=inst_b.id,
            actor="attacker@bankb.com",
        )
    assert exc_info.value.status_code == 403
    assert "belonging to another institution" in str(exc_info.value)


@pytest.mark.asyncio
async def test_replay_batch_filtered_by_institution(
    db_session: AsyncSession,
    inst_a: Institution,
    inst_b: Institution,
) -> None:
    """Verify that batch replay only reconfigures events belonging to the requesting institution."""
    repo = DrunixOutboxRepository(db_session)

    # Create 2 failed events for Inst A
    event_a1 = await repo.create_event(
        institution_id=inst_a.id,
        event_type=DrunixEventType.AUTH_ATTESTATION,
        aggregate_type="POLICY",
        aggregate_id=uuid.uuid4(),
        idempotency_key=f"idemp_batch_a1_{uuid.uuid4().hex}",
        payload={"result": "FAILED"},
        commitment_hash="hash" + uuid.uuid4().hex[:12],
    )
    event_a1.status = DrunixOutboxStatus.TERMINAL_FAILURE
    event_a2 = await repo.create_event(
        institution_id=inst_a.id,
        event_type=DrunixEventType.AUTH_ATTESTATION,
        aggregate_type="POLICY",
        aggregate_id=uuid.uuid4(),
        idempotency_key=f"idemp_batch_a2_{uuid.uuid4().hex}",
        payload={"result": "FAILED"},
        commitment_hash="hash" + uuid.uuid4().hex[:12],
    )
    event_a2.status = DrunixOutboxStatus.RETRYABLE_FAILURE

    # Create 1 failed event for Inst B
    event_b = await repo.create_event(
        institution_id=inst_b.id,
        event_type=DrunixEventType.AUTH_ATTESTATION,
        aggregate_type="POLICY",
        aggregate_id=uuid.uuid4(),
        idempotency_key=f"idemp_batch_b_{uuid.uuid4().hex}",
        payload={"result": "FAILED"},
        commitment_hash="hash" + uuid.uuid4().hex[:12],
    )
    event_b.status = DrunixOutboxStatus.TERMINAL_FAILURE
    await db_session.flush()

    # Inst A triggers batch replay
    replayed_count = await repo.replay_batch(
        requesting_institution_id=inst_a.id,
        limit=10,
        actor="batch-operator@banka.com",
    )
    assert replayed_count == 2

    # Verify Inst A's events are now PENDING
    a1_refreshed = await repo.get_by_id(event_a1.id)
    assert a1_refreshed is not None
    assert a1_refreshed.status == DrunixOutboxStatus.PENDING

    a2_refreshed = await repo.get_by_id(event_a2.id)
    assert a2_refreshed is not None
    assert a2_refreshed.status == DrunixOutboxStatus.PENDING

    # Verify Inst B's event is still TERMINAL_FAILURE
    b_refreshed = await repo.get_by_id(event_b.id)
    assert b_refreshed is not None
    assert b_refreshed.status == DrunixOutboxStatus.TERMINAL_FAILURE
