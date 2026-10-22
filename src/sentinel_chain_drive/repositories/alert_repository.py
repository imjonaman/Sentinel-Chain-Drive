"""Data-access repository for MuleChain fraud intelligence alerts."""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.db.models.alert import (
    AlertSeverity,
    AlertStatus,
    DetectorType,
    FraudAlert,
)
from sentinel_chain_drive.repositories.base import BaseRepository


class AlertRepository(BaseRepository[FraudAlert]):
    """Encapsulates database operations for fraud alerts, evidence, and deduplication."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(FraudAlert, session)

    async def get_by_id_scoped(
        self,
        alert_id: uuid.UUID,
        institution_id: uuid.UUID,
    ) -> FraudAlert | None:
        """Fetch alert by ID ensuring strict tenant institution scoping."""
        stmt = select(FraudAlert).where(
            FraudAlert.id == alert_id,
            FraudAlert.primary_institution_id == institution_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_fingerprint(
        self,
        institution_id: uuid.UUID,
        dedup_fingerprint: str,
    ) -> FraudAlert | None:
        """Find existing alert by institution and deduplication fingerprint."""
        stmt = select(FraudAlert).where(
            FraudAlert.primary_institution_id == institution_id,
            FraudAlert.dedup_fingerprint == dedup_fingerprint,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_idempotent(
        self,
        alert: FraudAlert,
    ) -> tuple[FraudAlert, bool]:
        """Atomically persist alert or return existing record if already generated.

        Returns (alert, created) where created is True if new, False if deduplicated.
        """
        existing = await self.get_by_fingerprint(
            alert.primary_institution_id,
            alert.dedup_fingerprint,
        )
        if existing is not None:
            return existing, False

        self.session.add(alert)
        await self.session.flush()
        return alert, True

    async def list_alerts_scoped(
        self,
        institution_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
        detector_type: DetectorType | None = None,
        severity: AlertSeverity | None = None,
        status: AlertStatus | None = None,
        account_id: uuid.UUID | None = None,
    ) -> tuple[Sequence[FraudAlert], int]:
        """Fetch a paginated list of fraud alerts within the caller's institution scope."""
        base_query = select(FraudAlert).where(FraudAlert.primary_institution_id == institution_id)
        count_query = (
            select(func.count())
            .select_from(FraudAlert)
            .where(FraudAlert.primary_institution_id == institution_id)
        )

        if detector_type is not None:
            base_query = base_query.where(FraudAlert.detector_type == detector_type)
            count_query = count_query.where(FraudAlert.detector_type == detector_type)

        if severity is not None:
            base_query = base_query.where(FraudAlert.severity == severity)
            count_query = count_query.where(FraudAlert.severity == severity)

        if status is not None:
            base_query = base_query.where(FraudAlert.status == status)
            count_query = count_query.where(FraudAlert.status == status)

        if account_id is not None:
            base_query = base_query.where(FraudAlert.primary_account_id == account_id)
            count_query = count_query.where(FraudAlert.primary_account_id == account_id)

        base_query = (
            base_query.order_by(FraudAlert.created_at.desc(), FraudAlert.id.desc())
            .limit(limit)
            .offset(offset)
        )

        items_result = await self.session.execute(base_query)
        total_result = await self.session.execute(count_query)

        items = items_result.scalars().all()
        total = total_result.scalar_one()
        return items, total

    async def update_triage(
        self,
        alert_id: uuid.UUID,
        institution_id: uuid.UUID,
        status: AlertStatus | None = None,
        severity: AlertSeverity | None = None,
    ) -> FraudAlert | None:
        """Update lifecycle status or escalated severity of an alert."""
        alert = await self.get_by_id_scoped(alert_id, institution_id)
        if alert is None:
            return None
        if status is not None:
            alert.status = status
        if severity is not None:
            alert.severity = severity
        await self.session.flush()
        return alert
