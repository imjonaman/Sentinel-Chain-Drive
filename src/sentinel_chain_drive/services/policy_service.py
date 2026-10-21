"""Service orchestrating the 10-step deterministic policy evaluation pipeline and workflows."""

import asyncio
import hashlib
import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.core.crypto import (
    SUPPORTED_SIGNING_ALGORITHMS,
    compute_transaction_intent_hash,
    verify_signature,
)
from sentinel_chain_drive.core.errors import AppException, EntityNotFoundException
from sentinel_chain_drive.db.models.drunix_outbox import DrunixEventType
from sentinel_chain_drive.db.models.policy import Policy
from sentinel_chain_drive.db.models.policy_evaluation import (
    HoldStatus,
    PolicyEvaluationRecord,
    PolicyOutcome,
    SpendingReservationStatus,
    StepUpChallenge,
    StepUpStatus,
    TransactionHold,
)
from sentinel_chain_drive.db.models.transaction import TransactionStatus
from sentinel_chain_drive.repositories.account_repository import AccountRepository
from sentinel_chain_drive.repositories.agent_repository import AgentRepository
from sentinel_chain_drive.repositories.audit_repository import AuditRepository
from sentinel_chain_drive.repositories.authorization_repository import AuthorizationRepository
from sentinel_chain_drive.repositories.capability_repository import CapabilityRepository
from sentinel_chain_drive.repositories.credential_repository import CredentialRepository
from sentinel_chain_drive.repositories.drunix_outbox_repository import DrunixOutboxRepository
from sentinel_chain_drive.repositories.institution_repository import InstitutionRepository
from sentinel_chain_drive.repositories.policy_evaluation_repository import (
    PolicyEvaluationRepository,
)
from sentinel_chain_drive.repositories.policy_repository import PolicyRepository
from sentinel_chain_drive.repositories.transaction_repository import TransactionRepository
from sentinel_chain_drive.schemas.audit import AuditLogCreate
from sentinel_chain_drive.schemas.policy import (
    HoldInfo,
    HoldResolutionRequest,
    PolicyCreate,
    PolicyDecisionResponse,
    PolicyEvaluationDetailResponse,
    PolicyEvaluationRequest,
    PolicyListResponse,
    PolicyResponse,
    StepUpChallengeInfo,
    StepUpChallengeResponse,
    StepUpCompletionRequest,
    TransactionHoldResponse,
)
from sentinel_chain_drive.services.policy_engine import (
    DeterministicPolicyEngine,
    PolicyEvaluationResult,
    ensure_utc,
)

logger = logging.getLogger(__name__)

MAX_CLOCK_SKEW_SECONDS = 300
DEFAULT_RESERVATION_EXPIRY_MINUTES = 60


class AgentLockManager:
    """In-process asyncio synchronization locks per agent and idempotency key.

    Complements database-level row locks (SELECT ... FOR UPDATE) by serializing
    concurrent async coroutines within the application process.
    """

    _locks: dict[uuid.UUID, asyncio.Lock] = {}
    _idemp_locks: dict[tuple[uuid.UUID, str], asyncio.Lock] = {}
    _global_lock: asyncio.Lock | None = None

    @classmethod
    def _get_global_lock(cls) -> asyncio.Lock:
        if cls._global_lock is None:
            cls._global_lock = asyncio.Lock()
        return cls._global_lock

    @classmethod
    async def get_agent_lock(cls, agent_id: uuid.UUID) -> asyncio.Lock:
        async with cls._get_global_lock():
            if agent_id not in cls._locks:
                cls._locks[agent_id] = asyncio.Lock()
            return cls._locks[agent_id]

    @classmethod
    async def get_idempotency_lock(
        cls, institution_id: uuid.UUID, idempotency_key: str
    ) -> asyncio.Lock:
        async with cls._get_global_lock():
            key = (institution_id, idempotency_key)
            if key not in cls._idemp_locks:
                cls._idemp_locks[key] = asyncio.Lock()
            return cls._idemp_locks[key]


class PolicyService:
    """Orchestrates policy governance, evaluation pipeline, step-up challenges, and holds."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.policy_repo = PolicyRepository(session)
        self.evaluation_repo = PolicyEvaluationRepository(session)
        self.agent_repo = AgentRepository(session)
        self.capability_repo = CapabilityRepository(session)
        self.credential_repo = CredentialRepository(session)
        self.auth_repo = AuthorizationRepository(session)
        self.institution_repo = InstitutionRepository(session)
        self.account_repo = AccountRepository(session)
        self.transaction_repo = TransactionRepository(session)
        self.audit_repo = AuditRepository(session)
        self.engine = DeterministicPolicyEngine()

    # -------------------------------------------------------------------------
    # Policy Administration
    # -------------------------------------------------------------------------

    async def get_or_create_default_policy(self) -> Policy:
        """Ensure a global baseline default policy exists."""
        existing = await self.policy_repo.get_active_policy(
            institution_id=None, policy_code="DEFAULT_BANKING_POLICY"
        )
        if existing is not None:
            return existing

        default_policy = Policy(
            institution_id=None,
            policy_code="DEFAULT_BANKING_POLICY",
            version=1,
            name="Global Baseline Banking Policy",
            description=(
                "Default deterministic evaluation policy with standard dual-control and "
                "risk thresholds"
            ),
            priority=100,
            rules={
                "max_transaction_amount": "50000.0000",
                "step_up_threshold_amount": "10000.0000",
                "step_up_risk_threshold": 0.50,
                "hold_risk_threshold": 0.85,
                "require_whitelisted_beneficiary": False,
                "allowed_currencies": ["USD", "EUR", "GBP"],
                "allowed_purpose_codes": [
                    "TRANSFER",
                    "PAYMENT",
                    "VENDOR_PAYMENT",
                    "PAYROLL",
                    "SUPPLIER_PAYMENT",
                    "SETTLEMENT",
                    "BOOK_TRANSFER",
                ],
                "dual_control_roles": ["SUPERVISOR"],
                "manual_review_roles": ["FRAUD_ANALYST"],
            },
            is_active=True,
            activated_at=datetime.now(UTC),
            activated_by="system",
        )
        self.session.add(default_policy)
        await self.session.flush()
        return default_policy

    async def create_policy(self, data: PolicyCreate, actor: str = "system") -> PolicyResponse:
        """Create and activate a versioned authorization policy."""
        if data.institution_id is not None:
            inst = await self.institution_repo.get_by_id(data.institution_id)
            if inst is None:
                raise EntityNotFoundException("Institution", str(data.institution_id))

        next_version = await self.policy_repo.get_next_version(
            data.institution_id, data.policy_code
        )

        policy = Policy(
            institution_id=data.institution_id,
            policy_code=data.policy_code,
            version=next_version,
            name=data.name,
            description=data.description,
            priority=data.priority,
            rules=data.rules.model_dump(mode="json"),
            is_active=True,
            activated_at=datetime.now(UTC),
            activated_by=actor,
        )
        self.session.add(policy)
        await self.session.flush()

        # Deactivate older versions of this policy code
        await self.policy_repo.deactivate_previous_versions(
            institution_id=data.institution_id,
            policy_code=data.policy_code,
            current_active_id=policy.id,
        )

        await self.audit_repo.create_log(
            AuditLogCreate(
                actor=actor,
                event_type="POLICY_CREATED_AND_ACTIVATED",
                description=(
                    f"Policy '{policy.policy_code}' v{policy.version} created and activated."
                ),
                details={
                    "policy_id": str(policy.id),
                    "policy_code": policy.policy_code,
                    "version": policy.version,
                    "priority": policy.priority,
                    "institution_id": str(policy.institution_id) if policy.institution_id else None,
                },
            )
        )
        await self.session.flush()
        return PolicyResponse.model_validate(policy)

    async def get_policy(self, policy_id: uuid.UUID) -> PolicyResponse:
        """Retrieve policy details by ID."""
        pol = await self.policy_repo.get_by_id(policy_id)
        if pol is None:
            raise EntityNotFoundException("Policy", str(policy_id))
        return PolicyResponse.model_validate(pol)

    async def list_policies(
        self,
        limit: int = 50,
        offset: int = 0,
        institution_id: uuid.UUID | None = None,
        is_active: bool | None = None,
    ) -> PolicyListResponse:
        """List policies with optional scoping filters."""
        items, total = await self.policy_repo.list_policies(
            limit=limit,
            offset=offset,
            institution_id=institution_id,
            is_active=is_active,
            include_global=True,
        )
        return PolicyListResponse(
            items=[PolicyResponse.model_validate(p) for p in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    # -------------------------------------------------------------------------
    # The 10-Step Evaluation Pipeline
    # -------------------------------------------------------------------------

    async def evaluate_transaction_policy(
        self,
        req: PolicyEvaluationRequest,
        actor: str = "policy_gateway",
        correlation_id: str | None = None,
    ) -> PolicyDecisionResponse:
        """Execute the deterministic policy evaluation pipeline with in-process and DB locking."""
        agent_lock = await AgentLockManager.get_agent_lock(req.agent_id)
        idemp_lock = await AgentLockManager.get_idempotency_lock(
            req.institution_id, req.idempotency_key
        )

        async with idemp_lock, agent_lock:
            res = await self._evaluate_transaction_policy_internal(
                req=req,
                actor=actor,
                correlation_id=correlation_id,
            )
            # Ensure database transaction is committed before releasing the lock
            await self.session.commit()
            return res

    async def _evaluate_transaction_policy_internal(
        self,
        req: PolicyEvaluationRequest,
        actor: str = "policy_gateway",
        correlation_id: str | None = None,
    ) -> PolicyDecisionResponse:
        """Internal execution of the deterministic policy pipeline."""
        now = datetime.now(UTC)

        # 1. Validate Schema and Monetary fields
        if req.transaction.amount <= Decimal("0.0000"):
            raise AppException(
                message="Transaction amount must be strictly greater than 0.",
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="INVALID_AMOUNT",
            )

        # 2. Check Idempotency before locking
        existing_evaluation = await self.evaluation_repo.get_by_idempotency_key(
            institution_id=req.institution_id,
            idempotency_key=req.idempotency_key,
        )
        tx_hash = compute_transaction_intent_hash(
            intent_or_origin_institution_code=req.transaction.origin_institution_code,
            origin_account_number=req.transaction.origin_account_number,
            destination_institution_code=req.transaction.destination_institution_code,
            destination_account_number=req.transaction.destination_account_number,
            amount=str(req.transaction.amount),
            currency=req.transaction.currency,
            transaction_type=req.transaction.transaction_type,
            purpose_code=req.transaction.purpose_code,
        )

        if existing_evaluation is not None:
            if existing_evaluation.transaction_intent_hash == tx_hash:
                # Idempotent match: return recorded decision
                return self._build_decision_response(existing_evaluation)
            # Idempotency collision with different intent
            raise AppException(
                message=(
                    f"Idempotency key '{req.idempotency_key}' was previously used "
                    "with conflicting transaction parameters."
                ),
                status_code=status.HTTP_409_CONFLICT,
                error_code="IDEMPOTENCY_CONFLICT",
            )

        # 3. Row-level Lock on Agent to prevent concurrent TOCTOU race conditions
        agent = await self.evaluation_repo.lock_agent_for_update(req.agent_id)
        if agent is None:
            return await self._record_fail_closed_decline(
                req=req,
                tx_hash=tx_hash,
                reason="AGENT_NOT_FOUND",
                now=now,
                actor=actor,
                correlation_id=correlation_id,
            )

        # 3.1. Re-check Idempotency after acquiring row lock in case a competing
        # concurrent request completed while this transaction was waiting for the lock
        post_lock_eval = await self.evaluation_repo.get_by_idempotency_key(
            institution_id=req.institution_id,
            idempotency_key=req.idempotency_key,
        )
        if post_lock_eval is not None:
            if post_lock_eval.transaction_intent_hash == tx_hash:
                return self._build_decision_response(post_lock_eval)
            raise AppException(
                message=(
                    f"Idempotency key '{req.idempotency_key}' was previously used "
                    "with conflicting transaction parameters."
                ),
                status_code=status.HTTP_409_CONFLICT,
                error_code="IDEMPOTENCY_CONFLICT",
            )

        # 4. Verify AgentID Credential and Clock Skew
        req_ts = ensure_utc(req.request_timestamp) or now
        clock_skew = abs((now - req_ts).total_seconds())
        if clock_skew > MAX_CLOCK_SKEW_SECONDS:
            return await self._record_fail_closed_decline(
                req=req,
                tx_hash=tx_hash,
                reason=(
                    f"CLOCK_SKEW_EXCEEDED: Skew {clock_skew:.1f}s exceeds "
                    f"{MAX_CLOCK_SKEW_SECONDS}s window"
                ),
                now=now,
                actor=actor,
                correlation_id=correlation_id,
            )

        # Check single-use nonce
        if await self.auth_repo.is_nonce_processed(req.nonce):
            return await self._record_fail_closed_decline(
                req=req,
                tx_hash=tx_hash,
                reason="REPLAY_DETECTED_NONCE_REUSED",
                now=now,
                actor=actor,
                correlation_id=correlation_id,
            )

        try:
            await self.auth_repo.record_nonce(
                nonce=req.nonce,
                agent_id=req.agent_id,
                request_timestamp=req_ts,
                expires_at=now + timedelta(seconds=MAX_CLOCK_SKEW_SECONDS * 2),
            )
        except IntegrityError:
            await self.session.rollback()
            return await self._record_fail_closed_decline(
                req=req,
                tx_hash=tx_hash,
                reason="REPLAY_DETECTED_NONCE_REUSED",
                now=now,
                actor=actor,
                correlation_id=correlation_id,
            )

        # Credential lookup and verification
        cred = await self.credential_repo.get_by_credential_id(req.credential_id)
        cred_reasons: list[str] = []
        cred_valid = True

        if cred is None:
            cred_valid = False
            cred_reasons.append("CREDENTIAL_NOT_FOUND")
        elif cred.agent_id != req.agent_id:
            cred_valid = False
            cred_reasons.append("CREDENTIAL_AGENT_MISMATCH")
        elif cred.institution_id != req.institution_id:
            cred_valid = False
            cred_reasons.append("CREDENTIAL_INSTITUTION_MISMATCH")
        elif cred.is_revoked:
            cred_valid = False
            cred_reasons.append("CREDENTIAL_REVOKED")
        elif cred.expires_at and ensure_utc(cred.expires_at) < now:  # type: ignore[operator]
            cred_valid = False
            cred_reasons.append("CREDENTIAL_EXPIRED")
        elif cred.key_version != agent.key_version:
            cred_valid = False
            cred_reasons.append("KEY_VERSION_MISMATCH")
        elif req.expected_audience is not None and cred.audience != req.expected_audience:
            cred_valid = False
            cred_reasons.append(
                f"INVALID_CREDENTIAL_AUDIENCE: Expected '{req.expected_audience}', "
                f"got '{cred.audience}'"
            )
        elif req.expected_issuer is not None and cred.issuer_id != req.expected_issuer:
            cred_valid = False
            cred_reasons.append(
                f"INVALID_CREDENTIAL_ISSUER: Expected '{req.expected_issuer}', "
                f"got '{cred.issuer_id}'"
            )

        # 5. Ed25519 Signature Verification
        if cred_valid:
            if agent.key_algorithm not in SUPPORTED_SIGNING_ALGORITHMS:
                cred_valid = False
                cred_reasons.append(f"UNSUPPORTED_SIGNING_ALGORITHM: '{agent.key_algorithm}'")
            else:
                canonical_auth_payload = {
                    "credential_id": req.credential_id,
                    "agent_id": str(req.agent_id),
                    "institution_id": str(req.institution_id),
                    "nonce": req.nonce,
                    "request_timestamp": req.request_timestamp.isoformat(),
                    "transaction_hash": tx_hash,
                }
                try:
                    sig_ok = verify_signature(
                        public_key_pem=agent.public_key,
                        payload=canonical_auth_payload,
                        signature_hex=req.signature,
                        algorithm=agent.key_algorithm,
                    )
                    if not sig_ok and "+00:00" in canonical_auth_payload["request_timestamp"]:
                        alt_payload = dict(canonical_auth_payload)
                        alt_payload["request_timestamp"] = canonical_auth_payload[
                            "request_timestamp"
                        ].replace("+00:00", "Z")
                        sig_ok = verify_signature(
                            public_key_pem=agent.public_key,
                            payload=alt_payload,
                            signature_hex=req.signature,
                            algorithm=agent.key_algorithm,
                        )
                    if not sig_ok:
                        cred_valid = False
                        cred_reasons.append("INVALID_SIGNATURE")
                except Exception as err:
                    logger.warning("PolicyEngine signature error: %s", err)
                    cred_valid = False
                    cred_reasons.append(f"INVALID_SIGNATURE: {err}")

        # 6. Load Active Policy
        policy = await self.policy_repo.get_active_policy(institution_id=req.institution_id)
        if policy is None:
            policy = await self.get_or_create_default_policy()

        # 7. Load Capabilities, Accounts, and Institutions
        capabilities = list(await self.capability_repo.get_active_by_agent(agent.id))
        origin_inst = await self.institution_repo.get_by_id(req.institution_id)

        # Origin and destination accounts by account number & institution
        origin_account = None
        destination_account = None
        if origin_inst is not None:
            acct = await self.account_repo.get_by_number(req.transaction.origin_account_number)
            if acct is not None and acct.institution_id == origin_inst.id:
                origin_account = acct

        dest_inst = await self.institution_repo.get_by_code(
            req.transaction.destination_institution_code
        )
        if dest_inst is not None:
            acct = await self.account_repo.get_by_number(req.transaction.destination_account_number)
            if acct is not None and acct.institution_id == dest_inst.id:
                destination_account = acct

        # 8. Calculate Velocity: 24h settled spend + active spending reservations
        past_24h = now - timedelta(hours=24)
        spend_24h = await self.auth_repo.get_24h_spend_sum(
            agent.id, since=past_24h, currency=req.transaction.currency
        )
        active_reservations = await self.evaluation_repo.get_active_reservations_sum(
            agent.id, currency=req.transaction.currency, now=now
        )

        # 9. Evaluate Deterministic Policy Rules
        eval_result: PolicyEvaluationResult = self.engine.evaluate(
            policy=policy,
            agent=agent,
            capabilities=capabilities,
            transaction=req.transaction,
            origin_institution=origin_inst,
            origin_account=origin_account,
            destination_account=destination_account,
            spend_24h=spend_24h,
            active_reservations_amount=active_reservations,
            risk_signals=req.risk_signals,
            evaluation_time=now,
            credential_check_passed=cred_valid,
            credential_reasons=cred_reasons,
        )

        # 10. Atomic Persistence of Decision, Reservations, and Lifecycle Coordination
        step_up_challenge: StepUpChallenge | None = None
        transaction_hold: TransactionHold | None = None
        spending_reservation = None

        if eval_result.outcome in (PolicyOutcome.ALLOW, PolicyOutcome.STEP_UP, PolicyOutcome.HOLD):
            # Create a spending reservation to prevent double-spending
            res_expiry = now + timedelta(minutes=DEFAULT_RESERVATION_EXPIRY_MINUTES)
            spending_reservation = await self.evaluation_repo.create_spending_reservation(
                agent_id=agent.id,
                institution_id=req.institution_id,
                amount=req.transaction.amount,
                currency=req.transaction.currency,
                expires_at=res_expiry,
                transaction_id=req.transaction_id,
            )

        eval_record_id = uuid.uuid4()

        if eval_result.outcome == PolicyOutcome.STEP_UP:
            step_up_expiry = now + timedelta(hours=1)
            step_up_challenge = await self.evaluation_repo.create_step_up_challenge(
                policy_evaluation_id=eval_record_id,
                transaction_intent_hash=tx_hash,
                policy_id=policy.id,
                policy_version=policy.version,
                initiating_agent_id=agent.id,
                institution_id=req.institution_id,
                expires_at=step_up_expiry,
                transaction_id=req.transaction_id,
                verification_type=eval_result.verification_type,
                required_role=eval_result.step_up_role,
            )

        elif eval_result.outcome == PolicyOutcome.HOLD:
            transaction_hold = await self.evaluation_repo.create_transaction_hold(
                policy_evaluation_id=eval_record_id,
                transaction_intent_hash=tx_hash,
                institution_id=req.institution_id,
                hold_reason=eval_result.hold_reason or "Automated policy review hold",
                transaction_id=req.transaction_id,
                review_workflow=eval_result.hold_workflow,
            )

        # Coordinate linked transaction status if present
        if req.transaction_id is not None:
            await self._update_linked_transaction_status(
                transaction_id=req.transaction_id,
                outcome=eval_result.outcome,
                reason=eval_result.reason_codes[0]
                if eval_result.reason_codes
                else "Policy decision applied",
                actor=actor,
                correlation_id=correlation_id,
            )

        eval_record = PolicyEvaluationRecord(
            id=eval_record_id,
            idempotency_key=req.idempotency_key,
            institution_id=req.institution_id,
            agent_id=req.agent_id,
            transaction_id=req.transaction_id,
            transaction_intent_hash=tx_hash,
            policy_id=policy.id,
            policy_version=policy.version,
            decision=eval_result.outcome,
            reason_codes=eval_result.reason_codes,
            applicable_rule_ids=eval_result.applicable_rule_ids,
            evaluation_evidence=eval_result.evidence,
            step_up_challenge_id=step_up_challenge.id if step_up_challenge else None,
            hold_id=transaction_hold.id if transaction_hold else None,
            spending_reservation_id=spending_reservation.id if spending_reservation else None,
            amount=req.transaction.amount,
            currency=req.transaction.currency,
            evaluated_at=now,
            correlation_id=correlation_id,
        )
        try:
            self.session.add(eval_record)
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
            existing = await self.evaluation_repo.get_by_idempotency_key(
                institution_id=req.institution_id,
                idempotency_key=req.idempotency_key,
            )
            if existing is not None:
                if existing.transaction_intent_hash == tx_hash:
                    return self._build_decision_response(existing)
                raise AppException(
                    message=(
                        f"Idempotency key '{req.idempotency_key}' was previously used "
                        "with conflicting transaction parameters."
                    ),
                    status_code=status.HTTP_409_CONFLICT,
                    error_code="IDEMPOTENCY_CONFLICT",
                ) from None
            raise

        # Audit log creation
        await self.audit_repo.create_log(
            AuditLogCreate(
                actor=actor,
                event_type=f"POLICY_EVALUATION_{eval_result.outcome.value}",
                description=(
                    f"Policy evaluation outcome: {eval_result.outcome.value} "
                    f"for agent '{req.agent_id}'. "
                    f"Reasons: {', '.join(eval_result.reason_codes)}"
                ),
                correlation_id=correlation_id,
                details={
                    "evaluation_id": str(eval_record.id),
                    "policy_id": str(policy.id),
                    "policy_version": policy.version,
                    "decision": eval_result.outcome.value,
                    "reasons": eval_result.reason_codes,
                    "rules": eval_result.applicable_rule_ids,
                    "amount": str(req.transaction.amount),
                    "currency": req.transaction.currency,
                    "idempotency_key": req.idempotency_key,
                },
            )
        )
        # DRUNIX Transactional Outbox Integration (Phase 7):
        # External delivery MUST NEVER override internal DECLINE, HOLD, or unresolved STEP_UP.
        # Only eligible, fully authorized (ALLOW) operations create outbox submission events.
        if eval_result.outcome == PolicyOutcome.ALLOW:
            outbox_repo = DrunixOutboxRepository(self.session)
            outbox_payload = {
                "decision_id": str(eval_record.id),
                "agent_id": str(agent.id),
                "institution_id": str(req.institution_id),
                "decision": PolicyOutcome.ALLOW.value,
                "transaction_intent_hash": tx_hash,
                "amount": str(req.transaction.amount),
                "currency": req.transaction.currency,
                "evaluated_at": now.isoformat(),
            }
            attestation_commitment = hashlib.sha256(
                f"{eval_record.id}:{agent.id}:ALLOW:{tx_hash}".encode()
            ).hexdigest()
            tx_id = req.transaction_id
            ordering_key = f"tx:{tx_id}" if tx_id else f"eval:{eval_record.id}"
            await outbox_repo.create_event(
                institution_id=req.institution_id,
                event_type=DrunixEventType.AUTH_ATTESTATION,
                aggregate_type="POLICY_EVALUATION",
                aggregate_id=eval_record.id,
                idempotency_key=f"drunix:auth:{eval_record.id}",
                commitment_hash=attestation_commitment,
                payload=outbox_payload,
                correlation_id=correlation_id,
                causation_id=str(tx_id) if tx_id else None,
                ordering_key=ordering_key,
                sequence_number=2 if tx_id else 1,
                event_category="DRUNIX_DELIVERY",
            )

        await self.session.flush()

        return self._build_decision_response(eval_record, step_up_challenge, transaction_hold)

    async def _update_linked_transaction_status(
        self,
        transaction_id: uuid.UUID,
        outcome: PolicyOutcome,
        reason: str,
        actor: str,
        correlation_id: str | None,
    ) -> None:
        """Update transaction status in accordance with policy outcome."""
        tx = await self.transaction_repo.get_with_history(transaction_id)
        if tx is None:
            return

        target_status: TransactionStatus | None = None
        if outcome == PolicyOutcome.ALLOW:
            target_status = TransactionStatus.AUTHORIZED
        elif outcome == PolicyOutcome.HOLD:
            target_status = TransactionStatus.HELD
        elif outcome == PolicyOutcome.DECLINE:
            target_status = TransactionStatus.REJECTED

        if target_status is not None and target_status != tx.status:
            try:
                await self.transaction_repo.update_status_with_history(
                    transaction=tx,
                    new_status=target_status,
                    reason=f"Policy engine evaluated {outcome.value}: {reason}",
                    actor=actor,
                    correlation_id=correlation_id,
                )
            except Exception as err:
                logger.warning(
                    "Could not transition transaction %s to %s: %s",
                    transaction_id,
                    target_status,
                    err,
                )

    async def _record_fail_closed_decline(
        self,
        req: PolicyEvaluationRequest,
        tx_hash: str,
        reason: str,
        now: datetime,
        actor: str,
        correlation_id: str | None,
    ) -> PolicyDecisionResponse:
        """Fail-closed fallback recording DECLINE when preliminary prerequisites fail."""
        policy = await self.get_or_create_default_policy()
        eval_record_id = uuid.uuid4()
        eval_record = PolicyEvaluationRecord(
            id=eval_record_id,
            idempotency_key=req.idempotency_key,
            institution_id=req.institution_id,
            agent_id=req.agent_id,
            transaction_id=req.transaction_id,
            transaction_intent_hash=tx_hash,
            policy_id=policy.id,
            policy_version=policy.version,
            decision=PolicyOutcome.DECLINE,
            reason_codes=[reason],
            applicable_rule_ids=["RULE_FAIL_CLOSED_PRE_CHECK"],
            evaluation_evidence={"fail_closed_reason": reason},
            amount=req.transaction.amount,
            currency=req.transaction.currency,
            evaluated_at=now,
            correlation_id=correlation_id,
        )
        try:
            self.session.add(eval_record)
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
            existing = await self.evaluation_repo.get_by_idempotency_key(
                institution_id=req.institution_id,
                idempotency_key=req.idempotency_key,
            )
            if existing is not None:
                return self._build_decision_response(existing)
            raise

        await self.audit_repo.create_log(
            AuditLogCreate(
                actor=actor,
                event_type="POLICY_EVALUATION_DECLINE",
                description=f"Fail-closed DECLINE for agent '{req.agent_id}': {reason}",
                correlation_id=correlation_id,
                details={"reason": reason, "idempotency_key": req.idempotency_key},
            )
        )
        await self.session.flush()

        return self._build_decision_response(eval_record)

    def _build_decision_response(
        self,
        record: PolicyEvaluationRecord,
        challenge: StepUpChallenge | None = None,
        hold: TransactionHold | None = None,
    ) -> PolicyDecisionResponse:
        """Construct shielded public response."""
        challenge_info = None
        if challenge is not None or record.step_up_challenge is not None:
            c = challenge or record.step_up_challenge
            if c:
                challenge_info = StepUpChallengeInfo(
                    challenge_id=c.id,
                    verification_type=c.verification_type,
                    required_role=c.required_role,
                    status=c.status,
                    expires_at=c.expires_at,
                )

        hold_info = None
        if hold is not None or record.hold is not None:
            h = hold or record.hold
            if h:
                hold_info = HoldInfo(
                    hold_id=h.id,
                    hold_reason=h.hold_reason,
                    review_workflow=h.review_workflow,
                    status=h.status,
                )

        return PolicyDecisionResponse(
            decision=record.decision,
            reason_codes=record.reason_codes,
            policy_id=record.policy_id,
            policy_version=record.policy_version,
            agent_id=record.agent_id,
            institution_id=record.institution_id,
            transaction_id=record.transaction_id,
            transaction_intent_hash=record.transaction_intent_hash,
            evaluated_at=record.evaluated_at,
            correlation_id=record.correlation_id,
            idempotency_key=record.idempotency_key,
            step_up_challenge=challenge_info,
            hold=hold_info,
            audit_record_id=record.id,
        )

    # -------------------------------------------------------------------------
    # Evaluation Retrieval
    # -------------------------------------------------------------------------

    async def get_evaluation_decision(
        self,
        evaluation_id: uuid.UUID,
        institution_id: uuid.UUID | None = None,
    ) -> PolicyDecisionResponse:
        """Retrieve decision by internal ID."""
        rec = await self.evaluation_repo.get_by_id(evaluation_id)
        if rec is None:
            raise EntityNotFoundException("PolicyEvaluation", str(evaluation_id))
        if institution_id is not None and rec.institution_id != institution_id:
            raise AppException(
                message="Access to evaluation belonging to another institution is forbidden.",
                status_code=status.HTTP_403_FORBIDDEN,
                error_code="CROSS_INSTITUTION_ACCESS_FORBIDDEN",
            )
        return self._build_decision_response(rec)

    async def get_evaluation_detail(
        self,
        evaluation_id: uuid.UUID,
        institution_id: uuid.UUID | None = None,
    ) -> PolicyEvaluationDetailResponse:
        """Retrieve full diagnostic evidence for authorized investigators."""
        rec = await self.evaluation_repo.get_by_id(evaluation_id)
        if rec is None:
            raise EntityNotFoundException("PolicyEvaluation", str(evaluation_id))
        if institution_id is not None and rec.institution_id != institution_id:
            raise AppException(
                message="Access to evaluation belonging to another institution is forbidden.",
                status_code=status.HTTP_403_FORBIDDEN,
                error_code="CROSS_INSTITUTION_ACCESS_FORBIDDEN",
            )
        resp = self._build_decision_response(rec)
        return PolicyEvaluationDetailResponse(
            **resp.model_dump(),
            applicable_rule_ids=rec.applicable_rule_ids,
            evaluation_evidence=rec.evaluation_evidence,
            spending_reservation_id=rec.spending_reservation_id,
        )

    # -------------------------------------------------------------------------
    # Step-Up Resolution Workflow
    # -------------------------------------------------------------------------

    async def get_step_up_challenge(
        self,
        challenge_id: uuid.UUID,
        institution_id: uuid.UUID | None = None,
    ) -> StepUpChallengeResponse:
        """Fetch step-up challenge details."""
        ch = await self.evaluation_repo.get_step_up_challenge(challenge_id)
        if ch is None:
            raise EntityNotFoundException("StepUpChallenge", str(challenge_id))
        if institution_id is not None and ch.institution_id != institution_id:
            raise AppException(
                message=(
                    "Access to step-up challenge belonging to another institution is forbidden."
                ),
                status_code=status.HTTP_403_FORBIDDEN,
                error_code="CROSS_INSTITUTION_ACCESS_FORBIDDEN",
            )
        return StepUpChallengeResponse.model_validate(ch)

    async def complete_step_up(
        self,
        challenge_id: uuid.UUID,
        data: StepUpCompletionRequest,
        institution_id: uuid.UUID | None = None,
        actor: str = "supervisor",
    ) -> StepUpChallengeResponse:
        """Complete a step-up challenge with dual-control authorization."""
        now = datetime.now(UTC)
        ch = await self.evaluation_repo.get_step_up_challenge(challenge_id)
        if ch is None:
            raise EntityNotFoundException("StepUpChallenge", str(challenge_id))
        if institution_id is not None and ch.institution_id != institution_id:
            raise AppException(
                message="Cannot complete challenge belonging to another institution.",
                status_code=status.HTTP_403_FORBIDDEN,
                error_code="CROSS_INSTITUTION_ACCESS_FORBIDDEN",
            )

        if ch.status != StepUpStatus.PENDING:
            raise AppException(
                message=f"Challenge is already {ch.status.value}; cannot resolve.",
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="CHALLENGE_ALREADY_RESOLVED",
            )

        # Check expiry
        if ensure_utc(ch.expires_at) < now:  # type: ignore[operator]
            ch.status = StepUpStatus.EXPIRED
            await self.session.flush()
            raise AppException(
                message="Step-up verification challenge has expired.",
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="CHALLENGE_EXPIRED",
            )

        # Separation of duties: approver cannot be initiating agent
        if data.approver_id == str(ch.initiating_agent_id):
            raise AppException(
                message="Separation of duties violation: Approver cannot be the initiating agent.",
                status_code=status.HTTP_403_FORBIDDEN,
                error_code="SEPARATION_OF_DUTIES_VIOLATION",
            )

        ch.approver_id = data.approver_id
        ch.decision_reason = data.reason
        ch.completed_at = now

        eval_rec = await self.evaluation_repo.get_by_id(ch.policy_evaluation_id)

        if data.decision == "APPROVED":
            ch.status = StepUpStatus.COMPLETED
            if eval_rec is not None:
                eval_rec.decision = PolicyOutcome.ALLOW
                eval_rec.reason_codes = ["STEP_UP_APPROVED_BY_SUPERVISOR"]
                outbox_repo = DrunixOutboxRepository(self.session)
                outbox_payload = {
                    "decision_id": str(eval_rec.id),
                    "challenge_id": str(ch.id),
                    "initiating_agent_id": str(ch.initiating_agent_id),
                    "approver_id": data.approver_id,
                    "institution_id": str(ch.institution_id),
                    "decision": PolicyOutcome.ALLOW.value,
                    "transaction_intent_hash": ch.transaction_intent_hash,
                    "evaluated_at": now.isoformat(),
                }
                attestation_commitment = hashlib.sha256(
                    f"{eval_rec.id}:{ch.initiating_agent_id}:ALLOW:{ch.transaction_intent_hash}".encode()
                ).hexdigest()
                tx_id = ch.transaction_id
                ordering_key = f"tx:{tx_id}" if tx_id else f"eval:{eval_rec.id}"
                await outbox_repo.create_event(
                    institution_id=ch.institution_id,
                    event_type=DrunixEventType.AUTH_ATTESTATION,
                    aggregate_type="POLICY_EVALUATION",
                    aggregate_id=eval_rec.id,
                    idempotency_key=f"drunix:auth:{eval_rec.id}",
                    commitment_hash=attestation_commitment,
                    payload=outbox_payload,
                    correlation_id=None,
                    causation_id=str(tx_id) if tx_id else None,
                    ordering_key=ordering_key,
                    sequence_number=2 if tx_id else 1,
                    event_category="DRUNIX_DELIVERY",
                )
            if ch.transaction_id is not None:
                await self._update_linked_transaction_status(
                    transaction_id=ch.transaction_id,
                    outcome=PolicyOutcome.ALLOW,
                    reason=f"Step-up approved by {data.approver_id}",
                    actor=actor,
                    correlation_id=None,
                )
        else:
            ch.status = StepUpStatus.REJECTED
            if eval_rec is not None:
                eval_rec.decision = PolicyOutcome.DECLINE
                eval_rec.reason_codes = ["STEP_UP_REJECTED_BY_SUPERVISOR"]
                # Release spending reservation
                if eval_rec.spending_reservation_id:
                    await self.evaluation_repo.update_reservation_status(
                        eval_rec.spending_reservation_id, SpendingReservationStatus.RELEASED
                    )
            if ch.transaction_id is not None:
                await self._update_linked_transaction_status(
                    transaction_id=ch.transaction_id,
                    outcome=PolicyOutcome.DECLINE,
                    reason=f"Step-up rejected by {data.approver_id}",
                    actor=actor,
                    correlation_id=None,
                )

        await self.session.flush()

        await self.audit_repo.create_log(
            AuditLogCreate(
                actor=data.approver_id,
                event_type=f"STEP_UP_{ch.status.value}",
                description=f"Step-up challenge {ch.id} resolved as {ch.status.value}",
                details={
                    "challenge_id": str(ch.id),
                    "decision": data.decision,
                    "reason": data.reason,
                    "initiating_agent_id": str(ch.initiating_agent_id),
                },
            )
        )
        await self.session.flush()
        return StepUpChallengeResponse.model_validate(ch)

    # -------------------------------------------------------------------------
    # Hold Resolution Workflow
    # -------------------------------------------------------------------------

    async def get_transaction_hold(
        self,
        hold_id: uuid.UUID,
        institution_id: uuid.UUID | None = None,
    ) -> TransactionHoldResponse:
        """Fetch transaction hold details."""
        h = await self.evaluation_repo.get_transaction_hold(hold_id)
        if h is None:
            raise EntityNotFoundException("TransactionHold", str(hold_id))
        if institution_id is not None and h.institution_id != institution_id:
            raise AppException(
                message="Access to hold belonging to another institution is forbidden.",
                status_code=status.HTTP_403_FORBIDDEN,
                error_code="CROSS_INSTITUTION_ACCESS_FORBIDDEN",
            )
        return TransactionHoldResponse.model_validate(h)

    async def resolve_transaction_hold(
        self,
        hold_id: uuid.UUID,
        data: HoldResolutionRequest,
        institution_id: uuid.UUID | None = None,
        actor: str = "fraud_analyst",
    ) -> TransactionHoldResponse:
        """Resolve an active institutional review hold."""
        now = datetime.now(UTC)
        h = await self.evaluation_repo.get_transaction_hold(hold_id)
        if h is None:
            raise EntityNotFoundException("TransactionHold", str(hold_id))
        if institution_id is not None and h.institution_id != institution_id:
            raise AppException(
                message="Cannot resolve hold belonging to another institution.",
                status_code=status.HTTP_403_FORBIDDEN,
                error_code="CROSS_INSTITUTION_ACCESS_FORBIDDEN",
            )

        if h.status != HoldStatus.ACTIVE:
            raise AppException(
                message=f"Hold is already {h.status.value}; cannot resolve.",
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="HOLD_ALREADY_RESOLVED",
            )

        h.resolved_by = data.resolved_by
        h.resolution_notes = data.notes
        h.resolved_at = now

        eval_rec = await self.evaluation_repo.get_by_id(h.policy_evaluation_id)

        if data.resolution == "RELEASE":
            h.status = HoldStatus.RELEASED
            if eval_rec is not None:
                eval_rec.decision = PolicyOutcome.ALLOW
                eval_rec.reason_codes = ["HOLD_RELEASED_BY_INVESTIGATOR"]
                outbox_repo = DrunixOutboxRepository(self.session)
                outbox_payload = {
                    "decision_id": str(eval_rec.id),
                    "hold_id": str(h.id),
                    "resolved_by": data.resolved_by,
                    "institution_id": str(h.institution_id),
                    "decision": PolicyOutcome.ALLOW.value,
                    "transaction_intent_hash": h.transaction_intent_hash,
                    "evaluated_at": now.isoformat(),
                }
                attestation_commitment = hashlib.sha256(
                    f"{eval_rec.id}:HOLD_RELEASED:ALLOW:{h.transaction_intent_hash}".encode()
                ).hexdigest()
                tx_id = h.transaction_id
                ordering_key = f"tx:{tx_id}" if tx_id else f"eval:{eval_rec.id}"
                await outbox_repo.create_event(
                    institution_id=h.institution_id,
                    event_type=DrunixEventType.AUTH_ATTESTATION,
                    aggregate_type="POLICY_EVALUATION",
                    aggregate_id=eval_rec.id,
                    idempotency_key=f"drunix:auth:{eval_rec.id}",
                    commitment_hash=attestation_commitment,
                    payload=outbox_payload,
                    correlation_id=None,
                    causation_id=str(tx_id) if tx_id else None,
                    ordering_key=ordering_key,
                    sequence_number=2 if tx_id else 1,
                    event_category="DRUNIX_DELIVERY",
                )
            if h.transaction_id is not None:
                await self._update_linked_transaction_status(
                    transaction_id=h.transaction_id,
                    outcome=PolicyOutcome.ALLOW,
                    reason=f"Hold released by {data.resolved_by}",
                    actor=actor,
                    correlation_id=None,
                )
        else:
            h.status = HoldStatus.CONFIRMED_DECLINE
            if eval_rec is not None:
                eval_rec.decision = PolicyOutcome.DECLINE
                eval_rec.reason_codes = ["HOLD_CONFIRMED_DECLINE_BY_INVESTIGATOR"]
                if eval_rec.spending_reservation_id:
                    await self.evaluation_repo.update_reservation_status(
                        eval_rec.spending_reservation_id, SpendingReservationStatus.RELEASED
                    )
            if h.transaction_id is not None:
                await self._update_linked_transaction_status(
                    transaction_id=h.transaction_id,
                    outcome=PolicyOutcome.DECLINE,
                    reason=f"Hold declined by {data.resolved_by}",
                    actor=actor,
                    correlation_id=None,
                )

        await self.session.flush()

        await self.audit_repo.create_log(
            AuditLogCreate(
                actor=data.resolved_by,
                event_type=f"HOLD_{h.status.value}",
                description=f"Transaction hold {h.id} resolved as {h.status.value}",
                details={
                    "hold_id": str(h.id),
                    "resolution": data.resolution,
                    "notes": data.notes,
                },
            )
        )
        await self.session.flush()
        return TransactionHoldResponse.model_validate(h)
