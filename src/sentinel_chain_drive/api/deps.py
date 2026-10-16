"""FastAPI dependency providers."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.db.session import get_db_session
from sentinel_chain_drive.services.agent_service import AgentService
from sentinel_chain_drive.services.audit_service import AuditService
from sentinel_chain_drive.services.banking_service import BankingService
from sentinel_chain_drive.services.system_service import SystemService


def get_system_service() -> SystemService:
    """Dependency provider for SystemService."""
    return SystemService()


def get_audit_service(session: AsyncSession = Depends(get_db_session)) -> AuditService:
    """Dependency provider for AuditService with injected database session."""
    return AuditService(session)


def get_banking_service(session: AsyncSession = Depends(get_db_session)) -> BankingService:
    """Dependency provider for BankingService with injected database session."""
    return BankingService(session)


def get_agent_service(session: AsyncSession = Depends(get_db_session)) -> AgentService:
    """Dependency provider for AgentService with injected database session."""
    return AgentService(session)


__all__ = [
    "get_agent_service",
    "get_audit_service",
    "get_banking_service",
    "get_db_session",
    "get_system_service",
]
