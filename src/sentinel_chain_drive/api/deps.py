"""FastAPI dependency providers."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.db.session import get_db_session
from sentinel_chain_drive.services.audit_service import AuditService
from sentinel_chain_drive.services.system_service import SystemService


def get_system_service() -> SystemService:
    """Dependency provider for SystemService."""
    return SystemService()


def get_audit_service(session: AsyncSession = Depends(get_db_session)) -> AuditService:
    """Dependency provider for AuditService with injected database session."""
    return AuditService(session)


__all__ = ["get_audit_service", "get_db_session", "get_system_service"]
