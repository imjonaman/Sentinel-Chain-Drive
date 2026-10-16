"""AuditLog repository for persisting and querying immutable audit trails."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.db.models.audit_log import AuditLog
from sentinel_chain_drive.repositories.base import BaseRepository
from sentinel_chain_drive.schemas.audit import AuditLogCreate


class AuditRepository(BaseRepository[AuditLog]):
    """Specialized repository for AuditLog persistence operations."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(AuditLog, session)

    async def create_log(self, data: AuditLogCreate) -> AuditLog:
        """Create and flush a new audit log record."""
        audit_entry = AuditLog(
            event_type=data.event_type,
            severity=data.severity,
            actor=data.actor,
            description=data.description,
            correlation_id=data.correlation_id,
            details=data.details,
        )
        return await self.add(audit_entry)

    async def list_recent(self, limit: int = 50) -> Sequence[AuditLog]:
        """Retrieve recent audit logs in descending chronological order."""
        stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_by_correlation_id(self, correlation_id: str) -> Sequence[AuditLog]:
        """Retrieve all audit logs related to a specific correlation ID."""
        stmt = (
            select(AuditLog)
            .where(AuditLog.correlation_id == correlation_id)
            .order_by(AuditLog.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
