"""Integration tests for Audit repository and service operations using isolated storage."""

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from sentinel_chain_drive.repositories.audit_repository import AuditRepository
from sentinel_chain_drive.schemas.audit import AuditLogCreate
from sentinel_chain_drive.services.audit_service import AuditService


@pytest.mark.asyncio
async def test_audit_repository_and_service_crud(sqlite_engine: AsyncEngine) -> None:
    """Verify storing, retrieving, and querying audit log events."""
    session_factory = async_sessionmaker(
        bind=sqlite_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        service = AuditService(session)

        # 1. Create audit entries
        log_input_1 = AuditLogCreate(
            event_type="SYSTEM_BOOT",
            severity="INFO",
            actor="system_daemon",
            description="System initialized successfully.",
            correlation_id="corr-boot-001",
            details={"modules_loaded": ["health", "system", "drunix_adapter"]},
        )
        created_1 = await service.log_event(log_input_1)
        await session.commit()

        assert created_1.id is not None
        assert created_1.event_type == "SYSTEM_BOOT"
        assert created_1.correlation_id == "corr-boot-001"
        assert created_1.details == {"modules_loaded": ["health", "system", "drunix_adapter"]}

        log_input_2 = AuditLogCreate(
            event_type="POLICY_EVAL",
            severity="WARNING",
            actor="agent_123",
            description="Agent step-up challenge required.",
            correlation_id="corr-boot-001",
            details={"risk_score": 75},
        )
        await service.log_event(log_input_2)
        await session.commit()

        # 2. Retrieve recent audit trail
        recent = await service.get_recent_audit_trail(limit=10)
        assert len(recent) == 2

        # 3. Retrieve by correlation ID via repository
        repo = AuditRepository(session)
        matching = await repo.list_by_correlation_id("corr-boot-001")
        assert len(matching) == 2
