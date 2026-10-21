"""Repository handling persistence and lookup for consumer-side processed event idempotency."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.db.models.processed_event import ProcessedEvent


class ProcessedEventRepository:
    """Manages processed event idempotency records."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def is_processed(
        self,
        consumer_name: str,
        event_id: uuid.UUID,
    ) -> bool:
        """Check if an event was previously processed by a specific consumer."""
        stmt = select(ProcessedEvent.id).where(
            ProcessedEvent.consumer_name == consumer_name,
            ProcessedEvent.event_id == event_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar() is not None

    async def record_processed(
        self,
        consumer_name: str,
        event_id: uuid.UUID,
        institution_id: uuid.UUID,
        correlation_id: str | None = None,
    ) -> bool:
        """Record that an event has been processed by a consumer.

        Returns True if newly recorded, or False if already recorded (idempotent duplicate).
        """
        record = ProcessedEvent(
            id=uuid.uuid4(),
            event_id=event_id,
            consumer_name=consumer_name,
            institution_id=institution_id,
            processed_at=datetime.now(UTC),
            correlation_id=correlation_id,
        )
        self.session.add(record)
        try:
            await self.session.flush()
            return True
        except IntegrityError:
            # Duplicate (consumer_name, event_id) detected; roll back savepoint
            return False
