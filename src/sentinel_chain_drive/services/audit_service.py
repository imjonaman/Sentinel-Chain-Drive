"""Audit service managing event creation and history."""

import logging
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.repositories.audit_repository import AuditRepository
from sentinel_chain_drive.schemas.audit import AuditLogCreate, AuditLogResponse

logger = logging.getLogger(__name__)


class AuditService:
    """Business service governing system audit logging and compliance event records."""

    def __init__(self, session: AsyncSession) -> None:
        self.repository = AuditRepository(session)

    async def log_event(self, event_data: AuditLogCreate) -> AuditLogResponse:
        """Create and persist an immutable audit trail entry."""
        audit_record = await self.repository.create_log(event_data)
        logger.info(
            "Audit event [%s] recorded by actor '%s': %s",
            audit_record.event_type,
            audit_record.actor,
            audit_record.description,
        )
        return AuditLogResponse.model_validate(audit_record)

    async def get_recent_audit_trail(self, limit: int = 50) -> Sequence[AuditLogResponse]:
        """Fetch chronological recent audit events."""
        records = await self.repository.list_recent(limit=limit)
        return [AuditLogResponse.model_validate(r) for r in records]
