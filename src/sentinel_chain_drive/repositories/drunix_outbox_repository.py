import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.db.models.drunix_outbox import (
    DrunixEventType,
    DrunixOutboxEvent,
    DrunixOutboxStatus,
)
from sentinel_chain_drive.db.models.ledger_submission import (
    DrunixLedgerSubmission,
    DrunixSubmissionStatus,
)

logger = logging.getLogger(__name__)


class OutboxLockManager:
    """Manages in-process claim lock safely across pytest event loops and tasks."""

    _lock: asyncio.Lock | None = None
    _loop: asyncio.AbstractEventLoop | None = None

    @classmethod
    def get_claim_lock(cls) -> asyncio.Lock:
        current_loop = asyncio.get_running_loop()
        if cls._lock is None or cls._loop is not current_loop:
            cls._lock = asyncio.Lock()
            cls._loop = current_loop
        return cls._lock


class DrunixOutboxRepository:
    """Repository handling ACID persistence and PostgreSQL row-locking for outbox events."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_event(
        self,
        institution_id: uuid.UUID,
        event_type: DrunixEventType,
        aggregate_type: str,
        aggregate_id: uuid.UUID,
        idempotency_key: str,
        commitment_hash: str,
        payload: dict[str, Any],
        correlation_id: str | None = None,
        max_attempts: int = 5,
        schema_version: str = "v1.0",
    ) -> DrunixOutboxEvent:
        """Create a new outbox event within the current session transaction."""
        now = datetime.now(UTC)
        event = DrunixOutboxEvent(
            id=uuid.uuid4(),
            institution_id=institution_id,
            event_type=event_type,
            schema_version=schema_version,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            idempotency_key=idempotency_key,
            commitment_hash=commitment_hash,
            payload=payload,
            status=DrunixOutboxStatus.PENDING,
            attempt_count=0,
            max_attempts=max_attempts,
            next_attempt_at=now,
            correlation_id=correlation_id,
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def get_by_id(self, event_id: uuid.UUID) -> DrunixOutboxEvent | None:
        """Fetch outbox event by primary key."""
        stmt = select(DrunixOutboxEvent).where(DrunixOutboxEvent.id == event_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_idempotency_key(
        self,
        institution_id: uuid.UUID,
        idempotency_key: str,
    ) -> DrunixOutboxEvent | None:
        """Fetch outbox event by institution and idempotency key."""
        stmt = select(DrunixOutboxEvent).where(
            DrunixOutboxEvent.institution_id == institution_id,
            DrunixOutboxEvent.idempotency_key == idempotency_key,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def claim_pending_events(
        self,
        worker_id: str,
        batch_size: int = 10,
        stale_lock_seconds: int = 300,
    ) -> list[DrunixOutboxEvent]:
        """Claim a batch of eligible events using PostgreSQL FOR UPDATE SKIP LOCKED.

        Prevents duplicate concurrent worker processing and reclaims expired locks.
        """
        async with OutboxLockManager.get_claim_lock():
            now = datetime.now(UTC)
            stale_threshold = now - timedelta(seconds=stale_lock_seconds)

            stmt = (
                select(DrunixOutboxEvent)
                .where(
                    (
                        DrunixOutboxEvent.status.in_(
                            [
                                DrunixOutboxStatus.PENDING,
                                DrunixOutboxStatus.RETRYABLE_FAILURE,
                            ]
                        )
                        & (DrunixOutboxEvent.next_attempt_at <= now)
                        & (
                            DrunixOutboxEvent.locked_by.is_(None)
                            | (DrunixOutboxEvent.locked_at < stale_threshold)
                        )
                    )
                    | (
                        (DrunixOutboxEvent.status == DrunixOutboxStatus.PROCESSING)
                        & (DrunixOutboxEvent.locked_at < stale_threshold)
                    )
                )
                .order_by(DrunixOutboxEvent.next_attempt_at.asc())
                .limit(batch_size)
            )

            # Apply PostgreSQL FOR UPDATE SKIP LOCKED if supported by dialect
            bind = self.session.bind
            dialect_name = bind.dialect.name if bind is not None else ""
            if dialect_name == "postgresql":
                stmt = stmt.with_for_update(skip_locked=True)

            result = await self.session.execute(stmt)
            events = list(result.scalars().all())

            for ev in events:
                ev.locked_by = worker_id
                ev.locked_at = now
                ev.status = DrunixOutboxStatus.PROCESSING

            if events:
                await self.session.commit()

            return events

    async def record_delivery(
        self,
        event_id: uuid.UUID,
        receipt_reference: str,
        receipt_data: dict[str, Any] | None = None,
    ) -> None:
        """Mark an outbox event as successfully delivered and record receipt evidence."""
        event = await self.get_by_id(event_id)
        if event is None:
            return

        now = datetime.now(UTC)
        event.status = DrunixOutboxStatus.DELIVERED
        event.delivered_at = now
        event.receipt_reference = receipt_reference
        event.locked_by = None
        event.locked_at = None
        event.error_category = None
        event.last_error = None
        event.attempt_count += 1

        submission = DrunixLedgerSubmission(
            id=uuid.uuid4(),
            outbox_event_id=event.id,
            institution_id=event.institution_id,
            submission_type=event.event_type.value,
            commitment_hash=event.commitment_hash,
            status=DrunixSubmissionStatus.ACKNOWLEDGED,
            tx_hash=receipt_reference,
            attempt_number=event.attempt_count,
            receipt_data=receipt_data,
        )
        self.session.add(submission)
        await self.session.commit()

    async def record_retryable_failure(
        self,
        event_id: uuid.UUID,
        error_category: str,
        error_message: str,
        next_attempt_at: datetime,
    ) -> None:
        """Record transient failure and schedule next bounded retry attempt."""
        event = await self.get_by_id(event_id)
        if event is None:
            return

        event.attempt_count += 1
        event.error_category = error_category
        event.last_error = error_message[:1000]
        event.locked_by = None
        event.locked_at = None

        if event.attempt_count >= event.max_attempts:
            event.status = DrunixOutboxStatus.TERMINAL_FAILURE
            submission_status = DrunixSubmissionStatus.FAILED
        else:
            event.status = DrunixOutboxStatus.RETRYABLE_FAILURE
            event.next_attempt_at = next_attempt_at
            submission_status = DrunixSubmissionStatus.FAILED

        submission = DrunixLedgerSubmission(
            id=uuid.uuid4(),
            outbox_event_id=event.id,
            institution_id=event.institution_id,
            submission_type=event.event_type.value,
            commitment_hash=event.commitment_hash,
            status=submission_status,
            attempt_number=event.attempt_count,
            error_category=error_category,
            error_message=error_message[:1000],
        )
        self.session.add(submission)
        await self.session.commit()

    async def record_terminal_failure(
        self,
        event_id: uuid.UUID,
        error_category: str,
        error_message: str,
    ) -> None:
        """Permanently mark event as terminal failure without scheduling retries."""
        event = await self.get_by_id(event_id)
        if event is None:
            return

        event.attempt_count += 1
        event.status = DrunixOutboxStatus.TERMINAL_FAILURE
        event.error_category = error_category
        event.last_error = error_message[:1000]
        event.locked_by = None
        event.locked_at = None

        submission = DrunixLedgerSubmission(
            id=uuid.uuid4(),
            outbox_event_id=event.id,
            institution_id=event.institution_id,
            submission_type=event.event_type.value,
            commitment_hash=event.commitment_hash,
            status=DrunixSubmissionStatus.FAILED,
            attempt_number=event.attempt_count,
            error_category=error_category,
            error_message=error_message[:1000],
        )
        self.session.add(submission)
        await self.session.commit()

    async def record_reconciliation_required(
        self,
        event_id: uuid.UUID,
        error_category: str,
        error_message: str,
    ) -> None:
        """Mark event as uncertain, requiring external ledger reconciliation."""
        event = await self.get_by_id(event_id)
        if event is None:
            return

        event.attempt_count += 1
        event.status = DrunixOutboxStatus.RECONCILIATION_REQUIRED
        event.error_category = error_category
        event.last_error = error_message[:1000]
        event.locked_by = None
        event.locked_at = None

        submission = DrunixLedgerSubmission(
            id=uuid.uuid4(),
            outbox_event_id=event.id,
            institution_id=event.institution_id,
            submission_type=event.event_type.value,
            commitment_hash=event.commitment_hash,
            status=DrunixSubmissionStatus.UNCERTAIN,
            attempt_number=event.attempt_count,
            error_category=error_category,
            error_message=error_message[:1000],
        )
        self.session.add(submission)
        await self.session.commit()

    async def get_metrics(
        self,
        institution_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Aggregate outbox metrics for operational observability."""
        now = datetime.now(UTC)
        base_stmt = select(
            DrunixOutboxEvent.status,
            func.count(DrunixOutboxEvent.id).label("count"),
        ).group_by(DrunixOutboxEvent.status)

        if institution_id is not None:
            base_stmt = base_stmt.where(DrunixOutboxEvent.institution_id == institution_id)

        rows = await self.session.execute(base_stmt)
        counts: dict[str, int] = {s.value: 0 for s in DrunixOutboxStatus}
        for status_val, count in rows.all():
            counts[status_val] = count

        # Oldest pending event age in seconds
        oldest_stmt = select(func.min(DrunixOutboxEvent.created_at)).where(
            DrunixOutboxEvent.status.in_(
                [DrunixOutboxStatus.PENDING, DrunixOutboxStatus.RETRYABLE_FAILURE]
            )
        )
        if institution_id is not None:
            oldest_stmt = oldest_stmt.where(DrunixOutboxEvent.institution_id == institution_id)

        oldest_dt = (await self.session.execute(oldest_stmt)).scalar()
        oldest_age_seconds: float = 0.0
        if oldest_dt is not None:
            if oldest_dt.tzinfo is None:
                oldest_dt = oldest_dt.replace(tzinfo=UTC)
            oldest_age_seconds = max(0.0, (now - oldest_dt).total_seconds())

        return {
            "counts_by_status": counts,
            "total_pending": counts[DrunixOutboxStatus.PENDING.value]
            + counts[DrunixOutboxStatus.RETRYABLE_FAILURE.value],
            "total_processing": counts[DrunixOutboxStatus.PROCESSING.value],
            "total_delivered": counts[DrunixOutboxStatus.DELIVERED.value],
            "total_terminal_failure": counts[DrunixOutboxStatus.TERMINAL_FAILURE.value],
            "total_reconciliation_required": counts[
                DrunixOutboxStatus.RECONCILIATION_REQUIRED.value
            ],
            "oldest_pending_age_seconds": round(oldest_age_seconds, 2),
        }
