"""Controlled Recovery Request Orchestration Service.

Provides simulated inter-bank recovery workflows with strict dual control (separation of duties),
idempotency, and reconciliation of uncertain outcomes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.core.errors import AppException, EntityNotFoundException
from sentinel_chain_drive.db.models.case import TERMINAL_CASE_STATUSES, CaseStatus
from sentinel_chain_drive.db.models.drunix_outbox import DrunixEventType
from sentinel_chain_drive.db.models.recovery import (
    RecoveryRequest,
    RecoveryStatus,
)
from sentinel_chain_drive.db.models.transaction import Transaction
from sentinel_chain_drive.repositories.audit_repository import AuditRepository
from sentinel_chain_drive.repositories.case_repository import CaseRepository
from sentinel_chain_drive.repositories.drunix_outbox_repository import DrunixOutboxRepository
from sentinel_chain_drive.repositories.recovery_repository import RecoveryRepository
from sentinel_chain_drive.schemas.audit import AuditLogCreate
from sentinel_chain_drive.schemas.recovery import (
    RecoveryApprovalRequest,
    RecoveryReconcileRequest,
    RecoveryRejectionRequest,
    RecoveryRequestCreate,
    RecoverySubmissionRequest,
)

logger = logging.getLogger(__name__)


class RecoveryService:
    """Service orchestrating simulated recovery requests under dual control."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.recovery_repo = RecoveryRepository(session)
        self.case_repo = CaseRepository(session)
        self.audit_repo = AuditRepository(session)
        self.outbox_repo = DrunixOutboxRepository(session)

    async def create_recovery_request(
        self,
        case_id: uuid.UUID,
        institution_id: uuid.UUID,
        payload: RecoveryRequestCreate,
        requester_id: str,
        requester_role: str = "INVESTIGATOR",
    ) -> RecoveryRequest:
        """Create a controlled recovery request in PENDING_APPROVAL status."""
        # 1. Validate Case Ownership & Lifecycle
        case = await self.case_repo.get_by_id_scoped(case_id, institution_id)
        if case is None:
            raise EntityNotFoundException("Case", str(case_id))

        if case.status in TERMINAL_CASE_STATUSES:
            raise AppException(
                message=(
                    f"Cannot initiate recovery for case {case.case_number} "
                    f"while in closed status '{case.status.value}'. Reopen the case first."
                ),
                status_code=400,
                error_code="CASE_CLOSED",
            )

        # 2. Check Idempotency Key
        existing = await self.recovery_repo.get_by_idempotency_key(
            institution_id=institution_id,
            idempotency_key=payload.idempotency_key,
        )
        if existing is not None:
            if existing.case_id != case_id or existing.transaction_id != payload.transaction_id:
                raise AppException(
                    message=(
                        "Idempotency key conflict: request exists with "
                        "different case or transaction attributes."
                    ),
                    status_code=409,
                    error_code="IDEMPOTENCY_CONFLICT",
                )
            logger.info(
                "Idempotent match for recovery key=%s, returning existing request_number=%s",
                payload.idempotency_key,
                existing.request_number,
            )
            return existing

        # 3. Validate Transaction exists
        stmt_tx = await self.session.get(Transaction, payload.transaction_id)
        if stmt_tx is None:
            raise EntityNotFoundException("Transaction", str(payload.transaction_id))

        # 4. Generate Request Number
        request_number = await self.recovery_repo.generate_request_number(institution_id)

        # 5. Persist Request
        recovery_req = RecoveryRequest(
            request_number=request_number,
            case_id=case_id,
            transaction_id=payload.transaction_id,
            requesting_institution_id=institution_id,
            target_institution_id=payload.target_institution_id,
            amount=payload.amount,
            currency=payload.currency,
            action_type=payload.action_type,
            status=RecoveryStatus.PENDING_APPROVAL,
            rationale=payload.rationale,
            requester_id=requester_id,
            requester_role=requester_role,
            idempotency_key=payload.idempotency_key,
            submission_attempt_count=0,
            is_simulated=True,
            metadata_json=payload.metadata_json,
        )
        self.session.add(recovery_req)
        await self.session.flush()

        # Update case status to PENDING_RECOVERY if not already
        if case.status in [CaseStatus.OPEN, CaseStatus.UNDER_INVESTIGATION, CaseStatus.IN_REVIEW]:
            old_status = case.status.value
            case.status = CaseStatus.PENDING_RECOVERY
            await self.case_repo.record_history(
                case_id=case.id,
                actor=requester_id,
                from_status=old_status,
                to_status=CaseStatus.PENDING_RECOVERY.value,
                transition_type="STATUS_CHANGE",
                reason=f"Recovery request {request_number} initiated.",
                details={"recovery_request_id": str(recovery_req.id)},
            )

        # Record history
        await self.recovery_repo.record_history(
            recovery_request_id=recovery_req.id,
            actor=requester_id,
            action="CREATE",
            from_status="NONE",
            to_status=RecoveryStatus.PENDING_APPROVAL.value,
            reason="Recovery request drafted and submitted for dual-control approval.",
            details={"action_type": payload.action_type.value, "amount": str(payload.amount)},
        )

        await self.audit_repo.create_log(
            AuditLogCreate(
                event_type="RECOVERY_REQUEST_CREATED",
                severity="INFO",
                actor=requester_id,
                correlation_id=case.correlation_id,
                description=(
                    f"Recovery request {request_number} drafted for case {case.case_number}."
                ),
                details={
                    "recovery_request_id": str(recovery_req.id),
                    "amount": str(payload.amount),
                    "currency": payload.currency,
                    "target_institution_id": str(payload.target_institution_id),
                },
            )
        )

        return recovery_req

    async def approve_recovery_request(
        self,
        request_id: uuid.UUID,
        institution_id: uuid.UUID,
        payload: RecoveryApprovalRequest,
        approver_id: str,
        approver_role: str | None = None,
    ) -> RecoveryRequest:
        """Approve recovery request under dual control (requester != approver)."""
        req = await self.recovery_repo.get_by_id_scoped(request_id, institution_id)
        if req is None:
            raise EntityNotFoundException("RecoveryRequest", str(request_id))

        if req.status != RecoveryStatus.PENDING_APPROVAL:
            raise AppException(
                message=(
                    f"Cannot approve recovery request in status '{req.status.value}'. "
                    "Must be PENDING_APPROVAL."
                ),
                status_code=422,
                error_code="INVALID_RECOVERY_STATUS",
            )

        # Strict Dual Control Check
        if approver_id == req.requester_id:
            raise AppException(
                message=(
                    f"Dual control separation of duties violation: Requester '{req.requester_id}' "
                    "cannot approve their own recovery request. "
                    "A separate authorized supervisor must approve."
                ),
                status_code=403,
                error_code="DUAL_CONTROL_VIOLATION",
            )

        req.status = RecoveryStatus.APPROVED
        req.approver_id = approver_id
        req.approver_role = approver_role or "SUPERVISOR"
        req.approval_notes = payload.approval_notes
        req.approved_at = datetime.now(UTC)
        await self.session.flush()

        await self.recovery_repo.record_history(
            recovery_request_id=req.id,
            actor=approver_id,
            action="APPROVE",
            from_status=RecoveryStatus.PENDING_APPROVAL.value,
            to_status=RecoveryStatus.APPROVED.value,
            reason="Approved under dual-control authorization.",
            details={"notes": payload.approval_notes, "approver_role": req.approver_role},
        )

        await self.audit_repo.create_log(
            AuditLogCreate(
                event_type="RECOVERY_REQUEST_APPROVED",
                severity="INFO",
                actor=approver_id,
                description=(
                    f"Recovery request {req.request_number} approved by supervisor {approver_id}."
                ),
                details={"recovery_request_id": str(req.id), "requester_id": req.requester_id},
            )
        )

        return req

    async def reject_recovery_request(
        self,
        request_id: uuid.UUID,
        institution_id: uuid.UUID,
        payload: RecoveryRejectionRequest,
        rejected_by: str,
    ) -> RecoveryRequest:
        """Reject a recovery request."""
        req = await self.recovery_repo.get_by_id_scoped(request_id, institution_id)
        if req is None:
            raise EntityNotFoundException("RecoveryRequest", str(request_id))

        if req.status not in [
            RecoveryStatus.DRAFT,
            RecoveryStatus.PENDING_APPROVAL,
            RecoveryStatus.APPROVED,
        ]:
            raise AppException(
                message=(
                    "Cannot reject recovery request in terminal or dispatched "
                    f"status '{req.status.value}'."
                ),
                status_code=422,
                error_code="INVALID_RECOVERY_STATUS",
            )

        from_status = req.status.value
        req.status = RecoveryStatus.REJECTED
        req.rejected_by = rejected_by
        req.rejection_reason = payload.rejection_reason
        req.rejected_at = datetime.now(UTC)
        await self.session.flush()

        await self.recovery_repo.record_history(
            recovery_request_id=req.id,
            actor=rejected_by,
            action="REJECT",
            from_status=from_status,
            to_status=RecoveryStatus.REJECTED.value,
            reason=payload.rejection_reason,
            details={},
        )

        await self.audit_repo.create_log(
            AuditLogCreate(
                event_type="RECOVERY_REQUEST_REJECTED",
                severity="INFO",
                actor=rejected_by,
                description=(
                    f"Recovery request {req.request_number} rejected: {payload.rejection_reason}."
                ),
                details={"recovery_request_id": str(req.id)},
            )
        )

        return req

    async def submit_recovery_request(
        self,
        request_id: uuid.UUID,
        institution_id: uuid.UUID,
        payload: RecoverySubmissionRequest,
        actor: str,
    ) -> RecoveryRequest:
        """Submit approved recovery request to simulated inter-bank rails."""
        req = await self.recovery_repo.get_by_id_scoped(request_id, institution_id)
        if req is None:
            raise EntityNotFoundException("RecoveryRequest", str(request_id))

        # Idempotent re-submission check
        if req.status in [
            RecoveryStatus.SUBMITTED,
            RecoveryStatus.ACKNOWLEDGED,
            RecoveryStatus.SETTLED,
        ]:
            logger.info(
                "Recovery request %s already submitted/acknowledged. Returning current state.",
                req.request_number,
            )
            return req

        if req.status != RecoveryStatus.APPROVED:
            raise AppException(
                message=(
                    "Recovery request must be in APPROVED status prior to submission "
                    f"(current: '{req.status.value}')."
                ),
                status_code=422,
                error_code="RECOVERY_NOT_APPROVED",
            )

        req.submission_attempt_count += 1
        req.submitted_at = datetime.now(UTC)

        outcome = payload.simulated_outcome.upper()
        if outcome == "ACKNOWLEDGE":
            req.status = RecoveryStatus.ACKNOWLEDGED
            req.external_reference = f"MOCK-ACK-{uuid.uuid4().hex[:10].upper()}"
            req.acknowledged_at = datetime.now(UTC)
        elif outcome == "REJECT":
            req.status = RecoveryStatus.REJECTED
            req.rejection_reason = (
                "Simulated recipient bank rejected recovery: account empty or restricted."
            )
            req.rejected_at = datetime.now(UTC)
        elif outcome == "TIMEOUT":
            req.status = RecoveryStatus.OUTCOME_UNKNOWN
            metadata = dict(req.metadata_json)
            metadata["timeout_encountered"] = True
            metadata["timeout_timestamp"] = datetime.now(UTC).isoformat()
            req.metadata_json = metadata
        else:
            req.status = RecoveryStatus.SUBMITTED

        await self.session.flush()

        # Record History
        await self.recovery_repo.record_history(
            recovery_request_id=req.id,
            actor=actor,
            action="SUBMIT",
            from_status=RecoveryStatus.APPROVED.value,
            to_status=req.status.value,
            reason=f"Dispatched via rail {payload.target_rail} (Outcome: {outcome})",
            details={
                "attempt": req.submission_attempt_count,
                "external_reference": req.external_reference,
                "simulated_outcome": outcome,
            },
        )

        # Audit Log
        await self.audit_repo.create_log(
            AuditLogCreate(
                event_type="RECOVERY_REQUEST_SUBMITTED",
                severity="INFO",
                actor=actor,
                description=(
                    f"Recovery request {req.request_number} submitted to {payload.target_rail}."
                ),
                details={
                    "recovery_request_id": str(req.id),
                    "status": req.status.value,
                    "external_reference": req.external_reference,
                },
            )
        )

        # Transactional Outbox Event
        outbox_payload = {
            "recovery_request_id": str(req.id),
            "request_number": req.request_number,
            "case_id": str(req.case_id),
            "transaction_id": str(req.transaction_id),
            "requesting_institution_id": str(institution_id),
            "target_institution_id": str(req.target_institution_id),
            "amount": str(req.amount),
            "currency": req.currency,
            "action_type": req.action_type.value,
            "status": req.status.value,
            "requester_id": req.requester_id,
            "approver_id": req.approver_id,
            "is_simulated": True,
        }
        await self.outbox_repo.create_event(
            institution_id=institution_id,
            event_type=DrunixEventType.RECOVERY_REQUESTED.value,
            aggregate_type="RECOVERY_REQUEST",
            aggregate_id=req.id,
            idempotency_key=f"recovery_submit:{req.id}:{payload.idempotency_key}",
            commitment_hash=hashlib.sha256(
                json.dumps(outbox_payload, sort_keys=True).encode()
            ).hexdigest(),
            payload=outbox_payload,
            event_category="INVESTIGATION",
        )

        return req

    async def acknowledge_recovery_request(
        self,
        request_id: uuid.UUID,
        institution_id: uuid.UUID,
        external_reference: str,
        actor: str,
        notes: str | None = None,
    ) -> RecoveryRequest:
        """Record external counterparty acknowledgement."""
        req = await self.recovery_repo.get_by_id_scoped(request_id, institution_id)
        if req is None:
            raise EntityNotFoundException("RecoveryRequest", str(request_id))

        if req.status not in [RecoveryStatus.SUBMITTED, RecoveryStatus.OUTCOME_UNKNOWN]:
            raise AppException(
                message=(
                    f"Cannot acknowledge recovery request in status '{req.status.value}'. "
                    "Must be SUBMITTED or OUTCOME_UNKNOWN."
                ),
                status_code=422,
                error_code="INVALID_RECOVERY_STATUS",
            )

        from_status = req.status.value
        req.status = RecoveryStatus.ACKNOWLEDGED
        req.external_reference = external_reference
        req.acknowledged_at = datetime.now(UTC)
        await self.session.flush()

        await self.recovery_repo.record_history(
            recovery_request_id=req.id,
            actor=actor,
            action="ACKNOWLEDGE",
            from_status=from_status,
            to_status=RecoveryStatus.ACKNOWLEDGED.value,
            reason=f"Acknowledged by counterparty. Ref: {external_reference}",
            details={"notes": notes},
        )

        await self.audit_repo.create_log(
            AuditLogCreate(
                event_type="RECOVERY_REQUEST_ACKNOWLEDGED",
                severity="INFO",
                actor=actor,
                description=(
                    f"Recovery request {req.request_number} acknowledged by counterparty "
                    f"reference {external_reference}."
                ),
                details={"recovery_request_id": str(req.id)},
            )
        )

        return req

    async def reconcile_recovery_request(
        self,
        request_id: uuid.UUID,
        institution_id: uuid.UUID,
        payload: RecoveryReconcileRequest,
        actor: str,
    ) -> RecoveryRequest:
        """Reconcile an uncertain outcome (OUTCOME_UNKNOWN) or finalize settlement."""
        req = await self.recovery_repo.get_by_id_scoped(request_id, institution_id)
        if req is None:
            raise EntityNotFoundException("RecoveryRequest", str(request_id))

        target_status_str = payload.reconciliation_status.upper()
        if target_status_str not in ["SETTLED", "REJECTED"]:
            raise AppException(
                message=(
                    f"Invalid reconciliation target status '{target_status_str}'. "
                    "Must be SETTLED or REJECTED."
                ),
                status_code=422,
                error_code="INVALID_RECONCILIATION_STATUS",
            )

        from_status = req.status.value
        req.status = RecoveryStatus[target_status_str]
        req.reconciliation_status = target_status_str
        req.reconciliation_notes = payload.reconciliation_notes
        req.reconciled_at = datetime.now(UTC)
        req.reconciled_by = actor
        await self.session.flush()

        await self.recovery_repo.record_history(
            recovery_request_id=req.id,
            actor=actor,
            action="RECONCILE",
            from_status=from_status,
            to_status=req.status.value,
            reason=f"Reconciled as {target_status_str}: {payload.reconciliation_notes}",
            details={},
        )

        await self.audit_repo.create_log(
            AuditLogCreate(
                event_type="RECOVERY_REQUEST_RECONCILED",
                severity="INFO",
                actor=actor,
                description=(
                    f"Recovery request {req.request_number} reconciled as {target_status_str}."
                ),
                details={"recovery_request_id": str(req.id), "notes": payload.reconciliation_notes},
            )
        )

        return req

    async def get_recovery_request(
        self,
        request_id: uuid.UUID,
        institution_id: uuid.UUID,
    ) -> RecoveryRequest | None:
        """Fetch recovery request ensuring institution ownership boundary."""
        return await self.recovery_repo.get_by_id_scoped(request_id, institution_id)

    async def list_by_case(
        self,
        case_id: uuid.UUID,
        institution_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[RecoveryRequest], int]:
        """List recovery requests belonging to a case."""
        items, total = await self.recovery_repo.list_by_case_scoped(
            case_id=case_id,
            institution_id=institution_id,
            limit=limit,
            offset=offset,
        )
        return list(items), total

    async def list_requests(
        self,
        institution_id: uuid.UUID,
        status: RecoveryStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[RecoveryRequest], int]:
        """List all recovery requests for an institution."""
        items, total = await self.recovery_repo.list_requests_scoped(
            institution_id=institution_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return list(items), total
