"""Data-access repository for policy evaluation audit records, step-up challenges,
holds, and spending reservations.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.db.models.agent import Agent
from sentinel_chain_drive.db.models.policy_evaluation import (
    HoldStatus,
    PolicyEvaluationRecord,
    SpendingReservation,
    SpendingReservationStatus,
    StepUpChallenge,
    StepUpStatus,
    TransactionHold,
)
from sentinel_chain_drive.repositories.base import BaseRepository


class PolicyEvaluationRepository(BaseRepository[PolicyEvaluationRecord]):
    """Encapsulates persistence operations for policy decisions, reservations,
    challenges, and holds.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(PolicyEvaluationRecord, session)

    async def lock_agent_for_update(self, agent_id: uuid.UUID) -> Agent | None:
        """Lock agent row with SELECT ... FOR UPDATE to serialize concurrent spending requests."""
        stmt = select(Agent).where(Agent.id == agent_id).with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(
        self, institution_id: uuid.UUID, idempotency_key: str
    ) -> PolicyEvaluationRecord | None:
        """Look up existing policy evaluation record by tenant and idempotency key."""
        stmt = select(PolicyEvaluationRecord).where(
            PolicyEvaluationRecord.institution_id == institution_id,
            PolicyEvaluationRecord.idempotency_key == idempotency_key,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_reservations_sum(
        self,
        agent_id: uuid.UUID,
        currency: str,
        now: datetime,
    ) -> Decimal:
        """Calculate total volume of active spending reservations for the agent in currency."""
        stmt = select(func.coalesce(func.sum(SpendingReservation.amount), Decimal("0.0000"))).where(
            SpendingReservation.agent_id == agent_id,
            SpendingReservation.currency == currency,
            SpendingReservation.status == SpendingReservationStatus.ACTIVE,
            SpendingReservation.expires_at > now,
        )
        result = await self.session.execute(stmt)
        val = result.scalar_one()
        return Decimal(str(val))

    async def create_spending_reservation(
        self,
        agent_id: uuid.UUID,
        institution_id: uuid.UUID,
        amount: Decimal,
        currency: str,
        expires_at: datetime,
        transaction_id: uuid.UUID | None = None,
        policy_evaluation_id: uuid.UUID | None = None,
    ) -> SpendingReservation:
        """Atomically persist a pending-spend velocity reservation."""
        reservation = SpendingReservation(
            agent_id=agent_id,
            institution_id=institution_id,
            transaction_id=transaction_id,
            policy_evaluation_id=policy_evaluation_id,
            amount=amount,
            currency=currency,
            status=SpendingReservationStatus.ACTIVE,
            expires_at=expires_at,
        )
        self.session.add(reservation)
        await self.session.flush()
        return reservation

    async def update_reservation_status(
        self,
        reservation_id: uuid.UUID,
        status: SpendingReservationStatus,
    ) -> SpendingReservation | None:
        """Update reservation lifecycle state."""
        stmt = select(SpendingReservation).where(SpendingReservation.id == reservation_id)
        result = await self.session.execute(stmt)
        res = result.scalar_one_or_none()
        if res is not None:
            res.status = status
            await self.session.flush()
        return res

    async def expire_stale_reservations(self, now: datetime) -> int:
        """Mark active reservations whose expiry timestamp has passed as EXPIRED."""
        stmt = (
            update(SpendingReservation)
            .where(
                SpendingReservation.status == SpendingReservationStatus.ACTIVE,
                SpendingReservation.expires_at <= now,
            )
            .values(status=SpendingReservationStatus.EXPIRED)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        count = getattr(result, "rowcount", 0)
        return int(count) if count is not None else 0

    async def create_step_up_challenge(
        self,
        policy_evaluation_id: uuid.UUID,
        transaction_intent_hash: str,
        policy_id: uuid.UUID,
        policy_version: int,
        initiating_agent_id: uuid.UUID,
        institution_id: uuid.UUID,
        expires_at: datetime,
        transaction_id: uuid.UUID | None = None,
        verification_type: str = "SUPERVISOR_APPROVAL",
        required_role: str = "SUPERVISOR",
    ) -> StepUpChallenge:
        """Persist a step-up challenge bound to transaction intent and policy version."""
        challenge = StepUpChallenge(
            policy_evaluation_id=policy_evaluation_id,
            transaction_id=transaction_id,
            transaction_intent_hash=transaction_intent_hash,
            policy_id=policy_id,
            policy_version=policy_version,
            initiating_agent_id=initiating_agent_id,
            institution_id=institution_id,
            verification_type=verification_type,
            required_role=required_role,
            status=StepUpStatus.PENDING,
            expires_at=expires_at,
        )
        self.session.add(challenge)
        await self.session.flush()
        return challenge

    async def get_step_up_challenge(self, challenge_id: uuid.UUID) -> StepUpChallenge | None:
        """Fetch step-up challenge by ID."""
        stmt = select(StepUpChallenge).where(StepUpChallenge.id == challenge_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_transaction_hold(
        self,
        policy_evaluation_id: uuid.UUID,
        transaction_intent_hash: str,
        institution_id: uuid.UUID,
        hold_reason: str,
        transaction_id: uuid.UUID | None = None,
        review_workflow: str = "FRAUD_INVESTIGATION",
    ) -> TransactionHold:
        """Persist an institutional review hold."""
        hold = TransactionHold(
            policy_evaluation_id=policy_evaluation_id,
            transaction_id=transaction_id,
            transaction_intent_hash=transaction_intent_hash,
            institution_id=institution_id,
            hold_reason=hold_reason,
            review_workflow=review_workflow,
            status=HoldStatus.ACTIVE,
        )
        self.session.add(hold)
        await self.session.flush()
        return hold

    async def get_transaction_hold(self, hold_id: uuid.UUID) -> TransactionHold | None:
        """Fetch hold record by ID."""
        stmt = select(TransactionHold).where(TransactionHold.id == hold_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_evaluations(
        self,
        limit: int = 50,
        offset: int = 0,
        institution_id: uuid.UUID | None = None,
        agent_id: uuid.UUID | None = None,
    ) -> tuple[Sequence[PolicyEvaluationRecord], int]:
        """Paginated list of policy evaluation records."""
        stmt = select(PolicyEvaluationRecord)
        count_stmt = select(func.count()).select_from(PolicyEvaluationRecord)

        conditions = []
        if institution_id is not None:
            conditions.append(PolicyEvaluationRecord.institution_id == institution_id)
        if agent_id is not None:
            conditions.append(PolicyEvaluationRecord.agent_id == agent_id)

        if conditions:
            stmt = stmt.where(*conditions)
            count_stmt = count_stmt.where(*conditions)

        stmt = stmt.order_by(PolicyEvaluationRecord.evaluated_at.desc()).offset(offset).limit(limit)

        items_res = await self.session.execute(stmt)
        total_res = await self.session.execute(count_stmt)
        return items_res.scalars().all(), total_res.scalar_one()
