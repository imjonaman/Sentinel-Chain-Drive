"""Investigation Case Management Service.

Coordinates alert triage, case compilation, evidentiary audit packages, and
lifecycle state machine governance strictly bounded by institution tenant isolation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.core.errors import AppException, EntityNotFoundException
from sentinel_chain_drive.db.models.alert import AlertSeverity
from sentinel_chain_drive.db.models.authorization_record import AuthorizationRecord
from sentinel_chain_drive.db.models.case import (
    TERMINAL_CASE_STATUSES,
    VALID_CASE_TRANSITIONS,
    Case,
    CaseCategory,
    CaseEvidence,
    CasePriority,
    CaseStatus,
    EvidenceType,
)
from sentinel_chain_drive.db.models.drunix_outbox import DrunixEventType, DrunixOutboxEvent
from sentinel_chain_drive.db.models.ledger_submission import DrunixLedgerSubmission
from sentinel_chain_drive.db.models.policy_evaluation import PolicyEvaluationRecord
from sentinel_chain_drive.repositories.alert_repository import AlertRepository
from sentinel_chain_drive.repositories.audit_repository import AuditRepository
from sentinel_chain_drive.repositories.case_repository import CaseRepository
from sentinel_chain_drive.repositories.drunix_outbox_repository import DrunixOutboxRepository
from sentinel_chain_drive.schemas.audit import AuditLogCreate
from sentinel_chain_drive.schemas.case import (
    CaseAssignRequest,
    CaseCreateRequest,
    CaseDossierResponse,
    CaseEvidenceCreateRequest,
    CasePriorityUpdateRequest,
    CaseResponse,
    CaseStatusTransitionRequest,
)

logger = logging.getLogger(__name__)


class CaseService:
    """Service governing investigation cases, dossiers, and auditable evidence."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.case_repo = CaseRepository(session)
        self.alert_repo = AlertRepository(session)
        self.audit_repo = AuditRepository(session)
        self.outbox_repo = DrunixOutboxRepository(session)

    async def create_case(
        self,
        institution_id: uuid.UUID,
        payload: CaseCreateRequest,
        actor: str = "system",
        actor_role: str | None = None,
    ) -> Case:
        """Open a new investigation case, enforcing idempotency and tenant boundaries."""
        # 1. Idempotency Check on source_type and source_id
        if payload.source_id:
            existing = await self.case_repo.get_by_source(
                institution_id=institution_id,
                source_type=payload.source_type,
                source_id=payload.source_id,
            )
            if existing is not None:
                logger.info(
                    "Idempotent case match found for institution=%s, source_type=%s, source_id=%s. "
                    "Returning existing case_number=%s",
                    institution_id,
                    payload.source_type,
                    payload.source_id,
                    existing.case_number,
                )
                return existing

        # 2. Sequential Case Number
        case_number = await self.case_repo.generate_case_number(institution_id)

        # 3. Create Case
        case = Case(
            case_number=case_number,
            institution_id=institution_id,
            category=payload.category,
            source_type=payload.source_type,
            source_id=payload.source_id or case_number,
            status=CaseStatus.OPEN,
            priority=payload.priority,
            risk_score=payload.risk_score,
            summary=payload.summary,
            description=payload.description,
            assigned_analyst_id=payload.assigned_analyst_id,
            assigned_role=payload.assigned_role or actor_role,
            correlation_id=payload.correlation_id,
            notes_log=[],
            metadata_json=payload.metadata_json,
        )
        self.session.add(case)
        await self.session.flush()

        # 4. Associate initial transactions, alerts, accounts
        for tx_id in payload.transaction_ids:
            await self.case_repo.add_transaction_association(
                case_id=case.id,
                transaction_id=tx_id,
                relation_type="PRIMARY",
                added_by=actor,
            )

        for alert_id in payload.alert_ids:
            await self.case_repo.add_alert_association(
                case_id=case.id,
                alert_id=alert_id,
                relation_type="PRIMARY",
                added_by=actor,
            )

        for acct_id in payload.account_ids:
            await self.case_repo.add_account_association(
                case_id=case.id,
                account_id=acct_id,
                role="MULE_SUSPECT",
                added_by=actor,
            )

        # 5. Record lifecycle history
        await self.case_repo.record_history(
            case_id=case.id,
            actor=actor,
            from_status="NONE",
            to_status=CaseStatus.OPEN.value,
            transition_type="CASE_OPENED",
            reason="Investigation case opened.",
            details={"summary": payload.summary, "category": payload.category.value},
        )

        # 6. Immutable audit log
        await self.audit_repo.create_log(
            AuditLogCreate(
                event_type="CASE_OPENED",
                severity="INFO",
                actor=actor,
                correlation_id=payload.correlation_id,
                description=(
                    f"Investigation case {case_number} opened for institution {institution_id}."
                ),
                details={
                    "case_id": str(case.id),
                    "case_number": case_number,
                    "priority": payload.priority.value,
                    "risk_score": payload.risk_score,
                },
            )
        )

        # 7. Transactional Outbox Event
        outbox_payload = {
            "case_id": str(case.id),
            "case_number": case_number,
            "institution_id": str(institution_id),
            "status": CaseStatus.OPEN.value,
            "priority": payload.priority.value,
            "category": payload.category.value,
            "source_type": payload.source_type,
            "source_id": payload.source_id or case_number,
            "actor": actor,
            "reason": "Case initialized",
        }
        await self.outbox_repo.create_event(
            institution_id=institution_id,
            event_type=DrunixEventType.CASE_CREATED.value,
            aggregate_type="CASE",
            aggregate_id=case.id,
            idempotency_key=f"case_created:{case.id}",
            commitment_hash=hashlib.sha256(
                json.dumps(outbox_payload, sort_keys=True).encode()
            ).hexdigest(),
            payload=outbox_payload,
            correlation_id=payload.correlation_id,
            event_category="INVESTIGATION",
        )

        # Reload with relationships
        fresh_case = await self.case_repo.get_by_id_scoped(case.id, institution_id)
        return fresh_case or case

    async def create_case_from_event(
        self,
        institution_id: uuid.UUID,
        event_type: str,
        payload: dict[str, Any],
        correlation_id: str | None = None,
    ) -> Case:
        """Idempotently convert domain and fraud alerts into actionable cases."""
        if event_type == "FRAUD_ALERT_RAISED":
            alert_id_str = payload.get("alert_id") or payload.get("id")
            if not alert_id_str:
                raise ValueError("FRAUD_ALERT_RAISED event payload missing alert_id.")

            alert_id = uuid.UUID(str(alert_id_str))
            alert = await self.alert_repo.get_by_id_scoped(alert_id, institution_id)
            if alert is None:
                raise EntityNotFoundException("FraudAlert", str(alert_id))

            # Map alert severity to priority
            priority_map = {
                AlertSeverity.LOW: CasePriority.LOW,
                AlertSeverity.MEDIUM: CasePriority.MEDIUM,
                AlertSeverity.HIGH: CasePriority.HIGH,
                AlertSeverity.CRITICAL: CasePriority.CRITICAL,
            }
            mapped_priority = priority_map.get(alert.severity, CasePriority.MEDIUM)

            req = CaseCreateRequest(
                summary=f"MuleChain Alert: {alert.alert_code} (Severity: {alert.severity.value})",
                description=(
                    f"Automated case from detector {alert.detector_type.value}. "
                    f"Score: {alert.risk_score}/100. Rule: {alert.detection_rule_version}."
                ),
                category=CaseCategory.FRAUD_ALERT,
                priority=mapped_priority,
                risk_score=alert.risk_score,
                source_type="FRAUD_ALERT",
                source_id=str(alert.id),
                correlation_id=correlation_id,
                alert_ids=[alert.id],
                account_ids=[alert.primary_account_id] if alert.primary_account_id else [],
                metadata_json={
                    "alert_code": alert.alert_code,
                    "detector_type": alert.detector_type.value,
                    "analysis_window_start": alert.analysis_window_start.isoformat(),
                    "analysis_window_end": alert.analysis_window_end.isoformat(),
                },
            )
            return await self.create_case(institution_id, req, actor="event_processor")

        if event_type == "TRANSACTION_HELD":
            tx_id_str = payload.get("transaction_id") or payload.get("id")
            if not tx_id_str:
                raise ValueError("TRANSACTION_HELD event payload missing transaction_id.")
            tx_id = uuid.UUID(str(tx_id_str))

            req = CaseCreateRequest(
                summary=f"Held Transaction Investigation: {tx_id}",
                description=(
                    "Transaction placed on institutional HOLD by Policy Engine awaiting review."
                ),
                category=CaseCategory.POLICY_VIOLATION,
                priority=CasePriority.HIGH,
                risk_score=75,
                source_type="TRANSACTION_HOLD",
                source_id=str(tx_id),
                correlation_id=correlation_id,
                transaction_ids=[tx_id],
            )
            return await self.create_case(institution_id, req, actor="event_processor")

        raise ValueError(
            f"Event type '{event_type}' is not an eligible source for case generation."
        )

    async def get_case(self, case_id: uuid.UUID, institution_id: uuid.UUID) -> Case | None:
        """Fetch full case details ensuring strict tenant boundary."""
        return await self.case_repo.get_by_id_scoped(case_id, institution_id)

    async def list_cases(
        self,
        institution_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
        status: CaseStatus | None = None,
        priority: CasePriority | None = None,
        category: CaseCategory | None = None,
        assigned_analyst_id: str | None = None,
    ) -> tuple[list[CaseResponse], int]:
        """List cases scoped to institution, converted to schema responses."""
        cases, total = await self.case_repo.list_cases_scoped(
            institution_id=institution_id,
            limit=limit,
            offset=offset,
            status=status,
            priority=priority,
            category=category,
            assigned_analyst_id=assigned_analyst_id,
        )

        responses: list[CaseResponse] = []
        for c in cases:
            tx_ids = [ct.transaction_id for ct in c.case_transactions]
            al_ids = [ca.alert_id for ca in c.case_alerts]
            ac_ids = [ca.account_id for ca in c.case_accounts]
            resp = CaseResponse(
                id=c.id,
                case_number=c.case_number,
                institution_id=c.institution_id,
                category=c.category,
                source_type=c.source_type,
                source_id=c.source_id,
                status=c.status,
                priority=c.priority,
                risk_score=c.risk_score,
                summary=c.summary,
                description=c.description,
                assigned_analyst_id=c.assigned_analyst_id,
                assigned_role=c.assigned_role,
                correlation_id=c.correlation_id,
                resolution_category=c.resolution_category,
                resolution_notes=c.resolution_notes,
                closed_at=c.closed_at,
                closed_by=c.closed_by,
                reopened_at=c.reopened_at,
                reopened_by=c.reopened_by,
                reopen_reason=c.reopen_reason,
                notes_log=c.notes_log,
                metadata_json=c.metadata_json,
                created_at=c.created_at,
                updated_at=c.updated_at,
                associated_transaction_ids=tx_ids,
                associated_alert_ids=al_ids,
                associated_account_ids=ac_ids,
                evidence_count=len(c.evidence_items),
            )
            responses.append(resp)

        return responses, total

    async def assign_case(
        self,
        case_id: uuid.UUID,
        institution_id: uuid.UUID,
        payload: CaseAssignRequest,
        actor: str,
    ) -> Case:
        """Assign or reassign an investigator to a case."""
        case = await self.case_repo.get_by_id_scoped(case_id, institution_id)
        if case is None:
            raise EntityNotFoundException("Case", str(case_id))

        # Guard: Closed cases cannot be assigned without reopening
        if case.status in TERMINAL_CASE_STATUSES:
            raise AppException(
                message=(
                    f"Cannot assign case {case.case_number} while in closed "
                    f"state '{case.status.value}'. Reopen the case first."
                ),
                status_code=400,
                error_code="CASE_CLOSED",
            )

        old_analyst = case.assigned_analyst_id
        case.assigned_analyst_id = payload.assigned_analyst_id
        if payload.assigned_role:
            case.assigned_role = payload.assigned_role

        # Auto transition from OPEN to UNDER_INVESTIGATION
        from_status = case.status.value
        if case.status == CaseStatus.OPEN:
            case.status = CaseStatus.UNDER_INVESTIGATION

        if payload.notes:
            note_entry = {
                "author": actor,
                "timestamp": datetime.now(UTC).isoformat(),
                "note": f"Assignment Note: {payload.notes}",
            }
            case.notes_log = list(case.notes_log) + [note_entry]

        await self.session.flush()

        # Record history
        await self.case_repo.record_history(
            case_id=case.id,
            actor=actor,
            from_status=from_status,
            to_status=case.status.value,
            transition_type="ASSIGNMENT",
            reason=f"Assigned to {payload.assigned_analyst_id} ({payload.assigned_role})",
            details={
                "previous_analyst": old_analyst,
                "new_analyst": payload.assigned_analyst_id,
                "notes": payload.notes,
            },
        )

        await self.audit_repo.create_log(
            AuditLogCreate(
                event_type="CASE_ASSIGNED",
                severity="INFO",
                actor=actor,
                correlation_id=case.correlation_id,
                description=f"Case {case.case_number} assigned to {payload.assigned_analyst_id}.",
                details={"case_id": str(case.id), "assigned_role": payload.assigned_role},
            )
        )

        return case

    async def transition_status(
        self,
        case_id: uuid.UUID,
        institution_id: uuid.UUID,
        payload: CaseStatusTransitionRequest,
        actor: str,
        actor_role: str | None = None,
    ) -> Case:
        """Validate and execute an explicit lifecycle state transition."""
        case = await self.case_repo.get_by_id_scoped(case_id, institution_id)
        if case is None:
            raise EntityNotFoundException("Case", str(case_id))

        from_status = case.status
        target_status = payload.target_status

        # 1. State machine validation
        allowed_transitions = VALID_CASE_TRANSITIONS.get(from_status, set())
        if target_status not in allowed_transitions:
            raise AppException(
                message=(
                    f"Invalid case status transition from '{from_status.value}' "
                    f"to '{target_status.value}'. "
                    f"Permitted next states: {[s.value for s in allowed_transitions]}"
                ),
                status_code=422,
                error_code="INVALID_STATE_TRANSITION",
            )

        # 2. Closure validation
        if target_status in TERMINAL_CASE_STATUSES:
            if not payload.resolution_category or not payload.resolution_notes:
                raise AppException(
                    message=(
                        "Resolution category and resolution notes are mandatory "
                        "when closing an investigation."
                    ),
                    status_code=422,
                    error_code="MANDATORY_RESOLUTION_RATIONALE",
                )
            case.closed_at = datetime.now(UTC)
            case.closed_by = actor
            case.resolution_category = payload.resolution_category
            case.resolution_notes = payload.resolution_notes

        # 3. Reopening validation
        if target_status == CaseStatus.REOPENED:
            if not payload.reopen_reason:
                raise AppException(
                    message=(
                        "A recorded supervisory reason is mandatory when reopening a closed case."
                    ),
                    status_code=422,
                    error_code="MANDATORY_REOPEN_RATIONALE",
                )
            case.reopened_at = datetime.now(UTC)
            case.reopened_by = actor
            case.reopen_reason = payload.reopen_reason

        case.status = target_status
        await self.session.flush()

        # 4. Record lifecycle transition history
        transition_type = (
            "CLOSURE"
            if target_status in TERMINAL_CASE_STATUSES
            else ("REOPEN" if target_status == CaseStatus.REOPENED else "STATUS_CHANGE")
        )
        await self.case_repo.record_history(
            case_id=case.id,
            actor=actor,
            from_status=from_status.value,
            to_status=target_status.value,
            transition_type=transition_type,
            reason=payload.reason,
            details={
                "resolution_category": payload.resolution_category,
                "reopen_reason": payload.reopen_reason,
                "actor_role": actor_role,
            },
        )

        # 5. Audit Log
        await self.audit_repo.create_log(
            AuditLogCreate(
                event_type="CASE_STATUS_CHANGED",
                severity="INFO",
                actor=actor,
                correlation_id=case.correlation_id,
                description=(
                    f"Case {case.case_number} transitioned from {from_status.value} "
                    f"to {target_status.value}."
                ),
                details={
                    "case_id": str(case.id),
                    "reason": payload.reason,
                    "resolution_category": payload.resolution_category,
                },
            )
        )

        # 6. Transactional Outbox Event
        outbox_payload = {
            "case_id": str(case.id),
            "case_number": case.case_number,
            "institution_id": str(institution_id),
            "from_status": from_status.value,
            "to_status": target_status.value,
            "reason": payload.reason,
            "actor": actor,
        }
        await self.outbox_repo.create_event(
            institution_id=institution_id,
            event_type=DrunixEventType.CASE_STATUS_CHANGED.value,
            aggregate_type="CASE",
            aggregate_id=case.id,
            idempotency_key=f"case_status:{case.id}:{datetime.now(UTC).timestamp()}",
            commitment_hash=hashlib.sha256(
                json.dumps(outbox_payload, sort_keys=True).encode()
            ).hexdigest(),
            payload=outbox_payload,
            correlation_id=case.correlation_id,
            event_category="INVESTIGATION",
        )

        return case

    async def update_priority(
        self,
        case_id: uuid.UUID,
        institution_id: uuid.UUID,
        payload: CasePriorityUpdateRequest,
        actor: str,
    ) -> Case:
        """Escalate or modify case priority with recorded justification."""
        case = await self.case_repo.get_by_id_scoped(case_id, institution_id)
        if case is None:
            raise EntityNotFoundException("Case", str(case_id))

        if case.status in TERMINAL_CASE_STATUSES:
            raise AppException(
                message=(
                    f"Cannot change priority of closed case {case.case_number}. "
                    "Reopen the case first."
                ),
                status_code=400,
                error_code="CASE_CLOSED",
            )

        old_priority = case.priority
        case.priority = payload.priority
        await self.session.flush()

        await self.case_repo.record_history(
            case_id=case.id,
            actor=actor,
            from_status=case.status.value,
            to_status=case.status.value,
            transition_type="PRIORITY_ESCALATION",
            reason=payload.reason,
            details={"old_priority": old_priority.value, "new_priority": payload.priority.value},
        )

        await self.audit_repo.create_log(
            AuditLogCreate(
                event_type="CASE_PRIORITY_CHANGED",
                severity="INFO",
                actor=actor,
                correlation_id=case.correlation_id,
                description=(
                    f"Case {case.case_number} priority changed from {old_priority.value} "
                    f"to {payload.priority.value}."
                ),
                details={"reason": payload.reason},
            )
        )

        return case

    async def add_note(
        self,
        case_id: uuid.UUID,
        institution_id: uuid.UUID,
        note_text: str,
        author: str,
    ) -> Case:
        """Append an investigation comment to the case's chronological notes log."""
        case = await self.case_repo.get_by_id_scoped(case_id, institution_id)
        if case is None:
            raise EntityNotFoundException("Case", str(case_id))

        note_entry = {
            "author": author,
            "timestamp": datetime.now(UTC).isoformat(),
            "note": note_text,
        }
        case.notes_log = list(case.notes_log) + [note_entry]
        await self.session.flush()

        await self.audit_repo.create_log(
            AuditLogCreate(
                event_type="CASE_NOTE_ADDED",
                severity="INFO",
                actor=author,
                correlation_id=case.correlation_id,
                description=f"Note appended to case {case.case_number}.",
                details={"case_id": str(case.id)},
            )
        )
        return case

    async def add_evidence(
        self,
        case_id: uuid.UUID,
        institution_id: uuid.UUID,
        payload: CaseEvidenceCreateRequest,
        author: str,
    ) -> CaseEvidence:
        """Attach verified evidentiary artifacts with cryptographic checksum."""
        case = await self.case_repo.get_by_id_scoped(case_id, institution_id)
        if case is None:
            raise EntityNotFoundException("Case", str(case_id))

        if case.status in TERMINAL_CASE_STATUSES:
            raise AppException(
                message=(
                    f"Cannot add evidence to closed case {case.case_number}. Reopen the case first."
                ),
                status_code=400,
                error_code="CASE_CLOSED",
            )

        # Compute SHA-256 checksum over canonical payload
        canonical_bytes = json.dumps(payload.payload_json, sort_keys=True).encode("utf-8")
        checksum = hashlib.sha256(canonical_bytes).hexdigest()

        evidence = await self.case_repo.add_evidence(
            case_id=case_id,
            evidence_type=payload.evidence_type,
            title=payload.title,
            description=payload.description,
            reference_uri=payload.reference_uri,
            payload_json=payload.payload_json,
            checksum_sha256=checksum,
            added_by=author,
        )

        await self.audit_repo.create_log(
            AuditLogCreate(
                event_type="CASE_EVIDENCE_ATTACHED",
                severity="INFO",
                actor=author,
                correlation_id=case.correlation_id,
                description=f"Evidence '{payload.title}' attached to case {case.case_number}.",
                details={"evidence_id": str(evidence.id), "checksum_sha256": checksum},
            )
        )
        return evidence

    async def compile_dossier(
        self,
        case_id: uuid.UUID,
        institution_id: uuid.UUID,
        compiled_by: str,
    ) -> CaseDossierResponse:
        """Compile a complete, tamper-evident evidentiary dossier for an investigation."""
        case = await self.case_repo.get_by_id_scoped(case_id, institution_id)
        if case is None:
            raise EntityNotFoundException("Case", str(case_id))

        now = datetime.now(UTC)

        # 1. Transactions and related policy/authorization records
        tx_data: list[dict[str, Any]] = []
        policy_eval_data: list[dict[str, Any]] = []
        agent_auth_data: list[dict[str, Any]] = []

        for ct in case.case_transactions:
            tx = ct.transaction
            if tx:
                tx_data.append(
                    {
                        "transaction_id": str(tx.id),
                        "amount": str(tx.amount),
                        "currency": tx.currency,
                        "status": tx.status.value,
                        "purpose_code": tx.purpose_code,
                        "origin_account_id": str(tx.origin_account_id),
                        "destination_account_id": str(tx.destination_account_id),
                        "relation_type": ct.relation_type,
                        "created_at": tx.created_at.isoformat(),
                    }
                )

                # Fetch policy evaluations for transaction
                stmt_eval = select(PolicyEvaluationRecord).where(
                    PolicyEvaluationRecord.transaction_id == tx.id
                )
                eval_res = await self.session.execute(stmt_eval)
                for pe in eval_res.scalars().all():
                    risk_val = None
                    if pe.evaluation_evidence and isinstance(pe.evaluation_evidence, dict):
                        risk_val = pe.evaluation_evidence.get("risk_score")
                    policy_eval_data.append(
                        {
                            "evaluation_id": str(pe.id),
                            "transaction_id": str(tx.id),
                            "decision": pe.decision.value,
                            "reason_codes": pe.reason_codes,
                            "risk_score": risk_val,
                            "evaluated_at": pe.created_at.isoformat(),
                        }
                    )

                # Fetch agent authorizations for transaction if present
                if tx.agent_id:
                    stmt_auth = select(AuthorizationRecord).where(
                        AuthorizationRecord.agent_id == tx.agent_id
                    )
                    auth_res = await self.session.execute(stmt_auth)
                    for ar in auth_res.scalars().all():
                        agent_auth_data.append(
                            {
                                "authorization_id": str(ar.id),
                                "agent_id": str(ar.agent_id),
                                "decision": ar.decision,
                                "reason_code": ar.decision_reasons[0]
                                if ar.decision_reasons
                                else None,
                                "signature_algorithm": "ED25519",
                                "evaluated_at": ar.evaluated_at.isoformat(),
                            }
                        )

        # 2. Fraud Alerts
        alert_data: list[dict[str, Any]] = []
        for ca in case.case_alerts:
            al = ca.alert
            if al:
                alert_data.append(
                    {
                        "alert_id": str(al.id),
                        "alert_code": al.alert_code,
                        "detector_type": al.detector_type.value,
                        "severity": al.severity.value,
                        "risk_score": al.risk_score,
                        "dedup_fingerprint": al.dedup_fingerprint,
                        "evidence_data": al.evidence_data,
                        "detection_rule_version": al.detection_rule_version,
                        "created_at": al.created_at.isoformat(),
                    }
                )

        # 3. Accounts
        account_data: list[dict[str, Any]] = []
        for cacct in case.case_accounts:
            acct = cacct.account
            if acct:
                account_data.append(
                    {
                        "account_id": str(acct.id),
                        "account_number_masked": f"***{acct.account_number[-4:]}",
                        "account_type": acct.account_type.value,
                        "currency": acct.currency,
                        "status": acct.status.value,
                        "role_in_case": cacct.role,
                    }
                )

        # 4. Ledger submissions
        target_agg_ids = [ct.transaction_id for ct in case.case_transactions] + [
            ca.alert_id for ca in case.case_alerts
        ]
        ledger_data: list[dict[str, Any]] = []
        if target_agg_ids:
            stmt_ledger = (
                select(DrunixLedgerSubmission)
                .join(
                    DrunixOutboxEvent,
                    DrunixLedgerSubmission.outbox_event_id == DrunixOutboxEvent.id,
                )
                .where(DrunixOutboxEvent.aggregate_id.in_(target_agg_ids))
            )
            ledger_res = await self.session.execute(stmt_ledger)
            for sub in ledger_res.scalars().all():
                ledger_data.append(
                    {
                        "submission_id": str(sub.id),
                        "submission_type": sub.submission_type,
                        "status": sub.status.value,
                        "commitment_hash": sub.commitment_hash,
                        "tx_receipt": sub.receipt_data,
                        "submitted_at": sub.created_at.isoformat(),
                    }
                )

        # 5. Evidence items
        evidence_data: list[dict[str, Any]] = []
        stmt_ev = (
            select(CaseEvidence)
            .where(CaseEvidence.case_id == case.id)
            .order_by(CaseEvidence.created_at.asc())
        )
        ev_res = await self.session.execute(stmt_ev)
        for ev in ev_res.scalars().all():
            evidence_data.append(
                {
                    "evidence_id": str(ev.id),
                    "evidence_type": ev.evidence_type.value,
                    "title": ev.title,
                    "description": ev.description,
                    "reference_uri": ev.reference_uri,
                    "checksum_sha256": ev.checksum_sha256,
                    "added_by": ev.added_by,
                    "created_at": ev.created_at.isoformat(),
                }
            )

        # 6. Status History
        history_data: list[dict[str, Any]] = []
        for hr in case.history_records:
            history_data.append(
                {
                    "history_id": str(hr.id),
                    "actor": hr.actor,
                    "from_status": hr.from_status,
                    "to_status": hr.to_status,
                    "transition_type": hr.transition_type,
                    "reason": hr.reason,
                    "created_at": hr.created_at.isoformat(),
                }
            )

        case_summary = {
            "case_id": str(case.id),
            "case_number": case.case_number,
            "institution_id": str(case.institution_id),
            "category": case.category.value,
            "status": case.status.value,
            "priority": case.priority.value,
            "risk_score": case.risk_score,
            "summary": case.summary,
            "assigned_analyst_id": case.assigned_analyst_id,
            "created_at": case.created_at.isoformat(),
        }

        # Canonicalize dossier dictionary for SHA-256 tamper-evident checksum
        dossier_dict: dict[str, Any] = {
            "case_summary": case_summary,
            "transactions": tx_data,
            "alerts": alert_data,
            "accounts": account_data,
            "policy_evaluations": policy_eval_data,
            "agent_authorizations": agent_auth_data,
            "ledger_attestations": ledger_data,
            "evidence_items": evidence_data,
            "status_history": history_data,
        }

        canonical_json = json.dumps(dossier_dict, sort_keys=True)
        dossier_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

        # Attach dossier package to case evidence
        await self.case_repo.add_evidence(
            case_id=case.id,
            evidence_type=EvidenceType.DOSSIER_PACKAGE,
            title=f"Evidentiary Dossier Package ({now.strftime('%Y-%m-%d')})",
            description=f"Compiled tamper-evident investigation package by {compiled_by}.",
            reference_uri=None,
            payload_json={
                "dossier_hash": dossier_hash,
                "items_count": len(tx_data) + len(alert_data),
            },
            checksum_sha256=dossier_hash,
            added_by=compiled_by,
        )

        return CaseDossierResponse(
            case_id=case.id,
            case_number=case.case_number,
            institution_id=institution_id,
            dossier_hash_sha256=dossier_hash,
            is_tamper_evident=True,
            compiled_at=now,
            compiled_by=compiled_by,
            case_summary=case_summary,
            transactions=tx_data,
            alerts=alert_data,
            accounts=account_data,
            policy_evaluations=policy_eval_data,
            agent_authorizations=agent_auth_data,
            ledger_attestations=ledger_data,
            evidence_items=evidence_data,
            status_history=history_data,
        )
