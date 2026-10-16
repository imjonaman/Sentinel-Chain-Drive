"""Data-access repository for authorization records and replay protection."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.db.models.authorization_record import (
    AuthorizationRecord,
    ProcessedNonce,
)
from sentinel_chain_drive.repositories.base import BaseRepository


class AuthorizationRepository(BaseRepository[AuthorizationRecord]):
    """Encapsulates database operations for authorization audit and replay nonce tracking."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(AuthorizationRecord, session)

    async def is_nonce_processed(self, nonce: str) -> bool:
        """Check whether a nonce has already been consumed."""
        stmt = select(func.count()).select_from(ProcessedNonce).where(ProcessedNonce.nonce == nonce)
        result = await self.session.execute(stmt)
        count = result.scalar_one()
        return count > 0

    async def record_nonce(
        self,
        nonce: str,
        agent_id: uuid.UUID,
        request_timestamp: datetime,
        expires_at: datetime,
    ) -> ProcessedNonce:
        """Persist a single-use nonce to prevent replay attacks."""
        record = ProcessedNonce(
            nonce=nonce,
            agent_id=agent_id,
            request_timestamp=request_timestamp,
            expires_at=expires_at,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_24h_spend_sum(
        self,
        agent_id: uuid.UUID,
        since: datetime,
        currency: str | None = None,
    ) -> Decimal:
        """Calculate total authorized transaction volume within the window, scoped by currency."""
        stmt = select(func.coalesce(func.sum(AuthorizationRecord.amount), Decimal("0.00"))).where(
            AuthorizationRecord.agent_id == agent_id,
            AuthorizationRecord.decision == "AUTHORIZED",
            AuthorizationRecord.evaluated_at >= since,
        )
        if currency:
            stmt = stmt.where(AuthorizationRecord.currency == currency)
        result = await self.session.execute(stmt)
        spend = result.scalar_one()
        return Decimal(str(spend))
