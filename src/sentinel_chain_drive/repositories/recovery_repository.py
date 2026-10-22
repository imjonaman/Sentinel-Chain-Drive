"""Repository for inter-bank recovery request orchestration and audit history."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from sentinel_chain_drive.db.models.recovery import (
    RecoveryRequest,
    RecoveryStatus,
    RecoveryStatusHistory,
)
from sentinel_chain_drive.repositories.base import BaseRepository


class RecoveryRepository(BaseRepository[RecoveryRequest]):
    """Encapsulates database operations for controlled recovery requests."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(RecoveryRequest, session)

    async def get_by_id_scoped(
        self,
        request_id: uuid.UUID,
        institution_id: uuid.UUID,
    ) -> RecoveryRequest | None:
        """Fetch recovery request ensuring institution ownership boundary."""
        stmt = (
            select(RecoveryRequest)
            .where(
                RecoveryRequest.id == request_id,
                RecoveryRequest.requesting_institution_id == institution_id,
            )
            .options(
                selectinload(RecoveryRequest.case),
                selectinload(RecoveryRequest.transaction),
                selectinload(RecoveryRequest.history_records),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(
        self,
        institution_id: uuid.UUID,
        idempotency_key: str,
    ) -> RecoveryRequest | None:
        """Fetch recovery request by institution and idempotency key."""
        stmt = (
            select(RecoveryRequest)
            .where(
                RecoveryRequest.requesting_institution_id == institution_id,
                RecoveryRequest.idempotency_key == idempotency_key,
            )
            .options(
                selectinload(RecoveryRequest.case),
                selectinload(RecoveryRequest.transaction),
                selectinload(RecoveryRequest.history_records),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def generate_request_number(self, institution_id: uuid.UUID) -> str:
        """Generate a sequential unique request number for recovery tracking."""
        current_year = datetime.now(UTC).year
        stmt = (
            select(func.count())
            .select_from(RecoveryRequest)
            .where(
                RecoveryRequest.requesting_institution_id == institution_id,
                RecoveryRequest.request_number.like(f"REC-{current_year}-%"),
            )
        )
        result = await self.session.execute(stmt)
        count = result.scalar_one() or 0
        return f"REC-{current_year}-{(count + 1):04d}"

    async def list_by_case_scoped(
        self,
        case_id: uuid.UUID,
        institution_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[RecoveryRequest], int]:
        """Fetch paginated recovery requests for a specific case."""
        base_query = (
            select(RecoveryRequest)
            .where(
                RecoveryRequest.case_id == case_id,
                RecoveryRequest.requesting_institution_id == institution_id,
            )
            .options(
                selectinload(RecoveryRequest.case),
                selectinload(RecoveryRequest.transaction),
            )
            .order_by(RecoveryRequest.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        count_query = (
            select(func.count())
            .select_from(RecoveryRequest)
            .where(
                RecoveryRequest.case_id == case_id,
                RecoveryRequest.requesting_institution_id == institution_id,
            )
        )

        items_res = await self.session.execute(base_query)
        count_res = await self.session.execute(count_query)

        return items_res.scalars().all(), count_res.scalar_one() or 0

    async def list_requests_scoped(
        self,
        institution_id: uuid.UUID,
        status: RecoveryStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[RecoveryRequest], int]:
        """Fetch paginated recovery requests scoped to the caller's institution."""
        base_query = (
            select(RecoveryRequest)
            .where(RecoveryRequest.requesting_institution_id == institution_id)
            .options(
                selectinload(RecoveryRequest.case),
                selectinload(RecoveryRequest.transaction),
            )
        )
        count_query = (
            select(func.count())
            .select_from(RecoveryRequest)
            .where(RecoveryRequest.requesting_institution_id == institution_id)
        )

        if status is not None:
            base_query = base_query.where(RecoveryRequest.status == status)
            count_query = count_query.where(RecoveryRequest.status == status)

        base_query = (
            base_query.order_by(RecoveryRequest.created_at.desc()).limit(limit).offset(offset)
        )

        items_res = await self.session.execute(base_query)
        count_res = await self.session.execute(count_query)

        return items_res.scalars().all(), count_res.scalar_one() or 0

    async def record_history(
        self,
        recovery_request_id: uuid.UUID,
        actor: str,
        action: str,
        from_status: str,
        to_status: str,
        reason: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> RecoveryStatusHistory:
        """Persist an immutable transition record in recovery history."""
        history = RecoveryStatusHistory(
            recovery_request_id=recovery_request_id,
            actor=actor,
            action=action,
            from_status=from_status,
            to_status=to_status,
            reason=reason,
            details=details or {},
        )
        self.session.add(history)
        await self.session.flush()
        return history

    async def get_request_history(
        self, recovery_request_id: uuid.UUID
    ) -> Sequence[RecoveryStatusHistory]:
        """Retrieve chronological history for a recovery request."""
        stmt = (
            select(RecoveryStatusHistory)
            .where(RecoveryStatusHistory.recovery_request_id == recovery_request_id)
            .order_by(RecoveryStatusHistory.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
