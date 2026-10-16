"""Business logic for AgentID registration, capability governance, and verification."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.core.crypto import (
    SUPPORTED_SIGNING_ALGORITHMS,
    compute_transaction_intent_hash,
    verify_signature,
)
from sentinel_chain_drive.core.errors import AppException, EntityNotFoundException
from sentinel_chain_drive.db.models.agent import (
    VALID_AGENT_TRANSITIONS,
    Agent,
    AgentStatus,
)
from sentinel_chain_drive.db.models.agent_credential import AgentCredential
from sentinel_chain_drive.db.models.authorization_record import (
    AuthorizationRecord,
)
from sentinel_chain_drive.db.models.capability import Capability
from sentinel_chain_drive.db.models.institution import InstitutionStatus
from sentinel_chain_drive.repositories.agent_repository import AgentRepository
from sentinel_chain_drive.repositories.audit_repository import AuditRepository
from sentinel_chain_drive.repositories.authorization_repository import AuthorizationRepository
from sentinel_chain_drive.repositories.capability_repository import CapabilityRepository
from sentinel_chain_drive.repositories.credential_repository import CredentialRepository
from sentinel_chain_drive.repositories.institution_repository import InstitutionRepository
from sentinel_chain_drive.schemas.agent import (
    AgentCreate,
    AgentKeyRotation,
    AgentListResponse,
    AgentResponse,
    AgentStatusUpdate,
    AgentUpdate,
)
from sentinel_chain_drive.schemas.audit import AuditLogCreate
from sentinel_chain_drive.schemas.capability import (
    CapabilityCreate,
    CapabilityListResponse,
    CapabilityResponse,
    CapabilityUpdate,
)
from sentinel_chain_drive.schemas.credential import (
    AuthorizationVerificationRequest,
    AuthorizationVerificationResponse,
    CredentialIssueRequest,
    CredentialListResponse,
    CredentialResponse,
)

logger = logging.getLogger(__name__)

# Maximum allowable request timestamp clock skew in seconds
MAX_CLOCK_SKEW_SECONDS = 300


def ensure_utc(dt: datetime | None) -> datetime | None:
    """Normalize datetime to UTC, ensuring compatibility with SQLite and PostgreSQL."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


class AgentService:
    """Service governing AgentID identity, capabilities, credentials, and verification."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.agent_repo = AgentRepository(session)
        self.capability_repo = CapabilityRepository(session)
        self.credential_repo = CredentialRepository(session)
        self.auth_repo = AuthorizationRepository(session)
        self.institution_repo = InstitutionRepository(session)
        self.audit_repo = AuditRepository(session)

    # -------------------------------------------------------------------------
    # Agent Identity & Lifecycle
    # -------------------------------------------------------------------------

    async def register_agent(
        self,
        institution_id: uuid.UUID,
        data: AgentCreate,
        actor: str = "system",
    ) -> AgentResponse:
        """Register a new AI agent under an active institution."""
        if institution_id != data.institution_id:
            raise AppException(
                message="Institution ID in URL does not match payload",
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="INSTITUTION_MISMATCH",
            )

        institution = await self.institution_repo.get_by_id(institution_id)
        if institution is None:
            raise EntityNotFoundException("Institution", str(institution_id))
        if institution.status != InstitutionStatus.ACTIVE:
            raise AppException(
                message=f"Institution is not ACTIVE (status: {institution.status.value})",
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="INSTITUTION_NOT_ACTIVE",
            )

        agent = Agent(
            institution_id=institution_id,
            name=data.name,
            description=data.description,
            owner_contact=data.owner_contact,
            agent_type=data.agent_type,
            public_key=data.public_key,
            key_algorithm="Ed25519",
            key_version=1,
            status=AgentStatus.PENDING_APPROVAL,
            valid_until=data.valid_until,
        )
        self.session.add(agent)
        await self.session.flush()

        await self.audit_repo.create_log(
            AuditLogCreate(
                actor=actor,
                event_type="AGENT_REGISTERED",
                description=f"Agent '{agent.name}' registered with status PENDING_APPROVAL",
                details={
                    "institution_id": str(institution_id),
                    "agent_id": str(agent.id),
                    "name": agent.name,
                    "agent_type": agent.agent_type,
                    "key_algorithm": agent.key_algorithm,
                },
            )
        )
        await self.session.flush()
        return AgentResponse.model_validate(agent)

    async def get_agent(
        self,
        institution_id: uuid.UUID,
        agent_id: uuid.UUID,
    ) -> AgentResponse:
        """Fetch agent details scoped to an institution."""
        agent = await self.agent_repo.get_by_institution_and_id(institution_id, agent_id)
        if agent is None:
            raise EntityNotFoundException("Agent", str(agent_id))
        return AgentResponse.model_validate(agent)

    async def list_agents(
        self,
        limit: int = 50,
        offset: int = 0,
        institution_id: uuid.UUID | None = None,
        agent_status: AgentStatus | None = None,
    ) -> AgentListResponse:
        """Fetch paginated list of agents."""
        items, total = await self.agent_repo.list_paginated(
            limit=limit,
            offset=offset,
            institution_id=institution_id,
            status=agent_status,
        )
        return AgentListResponse(
            items=[AgentResponse.model_validate(a) for a in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def update_agent(
        self,
        institution_id: uuid.UUID,
        agent_id: uuid.UUID,
        data: AgentUpdate,
        actor: str = "system",
    ) -> AgentResponse:
        """Update non-sensitive metadata for an agent."""
        agent = await self.agent_repo.get_by_institution_and_id(institution_id, agent_id)
        if agent is None:
            raise EntityNotFoundException("Agent", str(agent_id))

        if data.name is not None:
            agent.name = data.name
        if data.description is not None:
            agent.description = data.description
        if data.owner_contact is not None:
            agent.owner_contact = data.owner_contact

        await self.session.flush()

        await self.audit_repo.create_log(
            AuditLogCreate(
                actor=actor,
                event_type="AGENT_METADATA_UPDATED",
                description=f"Agent '{agent.id}' metadata updated",
                details={
                    "institution_id": str(institution_id),
                    "agent_id": str(agent.id),
                },
            )
        )
        await self.session.flush()
        return AgentResponse.model_validate(agent)

    async def update_agent_status(
        self,
        institution_id: uuid.UUID,
        agent_id: uuid.UUID,
        data: AgentStatusUpdate,
        actor: str = "system",
    ) -> AgentResponse:
        """Enforce strict lifecycle transitions for an agent."""
        agent = await self.agent_repo.get_by_institution_and_id(institution_id, agent_id)
        if agent is None:
            raise EntityNotFoundException("Agent", str(agent_id))

        current_status = agent.status
        target_status = data.status

        # Check legal transitions
        allowed_transitions = VALID_AGENT_TRANSITIONS.get(current_status, set())
        if target_status not in allowed_transitions:
            raise AppException(
                message=(
                    f"Illegal lifecycle transition: cannot change agent from "
                    f"'{current_status.value}' to '{target_status.value}'"
                ),
                status_code=status.HTTP_409_CONFLICT,
                error_code="ILLEGAL_AGENT_STATUS_TRANSITION",
                details={
                    "current_status": current_status.value,
                    "target_status": target_status.value,
                    "allowed_transitions": [s.value for s in allowed_transitions],
                },
            )

        now = datetime.now(UTC)
        agent.status = target_status
        if target_status == AgentStatus.ACTIVE and agent.activated_at is None:
            agent.activated_at = now
        elif target_status == AgentStatus.REVOKED:
            agent.revoked_at = now

        await self.session.flush()

        await self.audit_repo.create_log(
            AuditLogCreate(
                actor=actor,
                event_type="AGENT_STATUS_TRANSITION",
                description=(
                    f"Agent '{agent.id}' status changed from '{current_status.value}' "
                    f"to '{target_status.value}'. Reason: {data.reason or 'None'}"
                ),
                details={
                    "institution_id": str(institution_id),
                    "agent_id": str(agent.id),
                    "old_status": current_status.value,
                    "new_status": target_status.value,
                    "reason": data.reason,
                },
            )
        )
        await self.session.flush()
        return AgentResponse.model_validate(agent)

    async def rotate_agent_key(
        self,
        institution_id: uuid.UUID,
        agent_id: uuid.UUID,
        data: AgentKeyRotation,
        actor: str = "system",
    ) -> AgentResponse:
        """Rotate an agent's cryptographic public key and bump key version."""
        agent = await self.agent_repo.get_by_institution_and_id(institution_id, agent_id)
        if agent is None:
            raise EntityNotFoundException("Agent", str(agent_id))

        if agent.status in (AgentStatus.REVOKED, AgentStatus.EXPIRED):
            raise AppException(
                message=f"Cannot rotate key for agent in status '{agent.status.value}'",
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="CANNOT_ROTATE_KEY",
            )

        old_version = agent.key_version
        agent.public_key = data.new_public_key
        agent.key_version += 1

        await self.session.flush()

        await self.audit_repo.create_log(
            AuditLogCreate(
                actor=actor,
                event_type="AGENT_KEY_ROTATED",
                description=(
                    f"Agent '{agent.id}' rotated key from version {old_version} to "
                    f"{agent.key_version}. Reason: {data.reason or 'None'}"
                ),
                details={
                    "institution_id": str(institution_id),
                    "agent_id": str(agent.id),
                    "old_version": old_version,
                    "new_version": agent.key_version,
                    "reason": data.reason,
                },
            )
        )
        await self.session.flush()
        return AgentResponse.model_validate(agent)

    # -------------------------------------------------------------------------
    # Capability Governance
    # -------------------------------------------------------------------------

    async def create_capability(
        self,
        institution_id: uuid.UUID,
        data: CapabilityCreate,
        actor: str = "system",
    ) -> CapabilityResponse:
        """Assign an authorization capability boundary to an active agent."""
        agent = await self.agent_repo.get_by_institution_and_id(institution_id, data.agent_id)
        if agent is None:
            raise EntityNotFoundException("Agent", str(data.agent_id))

        if agent.status in (AgentStatus.REVOKED, AgentStatus.SUSPENDED, AgentStatus.EXPIRED):
            raise AppException(
                message=f"Cannot assign capability to agent with status '{agent.status.value}'",
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="INVALID_AGENT_STATUS",
            )

        now = datetime.now(UTC)
        valid_from = data.valid_from or now

        capability = Capability(
            agent_id=data.agent_id,
            institution_id=institution_id,
            name=data.name,
            description=data.description,
            permitted_transaction_types=data.permitted_transaction_types,
            permitted_currencies=data.permitted_currencies,
            max_amount_per_transaction=data.max_amount_per_transaction,
            max_daily_cumulative_amount=data.max_daily_cumulative_amount,
            allowed_origin_accounts=data.allowed_origin_accounts,
            allowed_destination_accounts=data.allowed_destination_accounts,
            purpose_codes=data.purpose_codes,
            operating_start_hour_utc=data.operating_start_hour_utc,
            operating_end_hour_utc=data.operating_end_hour_utc,
            valid_from=valid_from,
            valid_until=data.valid_until,
            is_active=True,
            created_by=data.created_by,
            approved_by=actor,
        )
        self.session.add(capability)
        await self.session.flush()

        await self.audit_repo.create_log(
            AuditLogCreate(
                actor=actor,
                event_type="CAPABILITY_ASSIGNED",
                description=(
                    f"Capability '{capability.name}' assigned to agent '{agent.id}' "
                    f"with max single amount {capability.max_amount_per_transaction}"
                ),
                details={
                    "institution_id": str(institution_id),
                    "capability_id": str(capability.id),
                    "agent_id": str(agent.id),
                    "name": capability.name,
                    "max_amount": str(capability.max_amount_per_transaction),
                    "max_daily": str(capability.max_daily_cumulative_amount),
                },
            )
        )
        await self.session.flush()
        return CapabilityResponse.model_validate(capability)

    async def get_capability(
        self,
        institution_id: uuid.UUID,
        capability_id: uuid.UUID,
    ) -> CapabilityResponse:
        """Fetch capability details scoped to an institution."""
        capability = await self.capability_repo.get_by_id(capability_id)
        if capability is None or capability.institution_id != institution_id:
            raise EntityNotFoundException("Capability", str(capability_id))
        return CapabilityResponse.model_validate(capability)

    async def list_capabilities(
        self,
        limit: int = 50,
        offset: int = 0,
        agent_id: uuid.UUID | None = None,
        institution_id: uuid.UUID | None = None,
        is_active: bool | None = None,
    ) -> CapabilityListResponse:
        """Fetch paginated capabilities."""
        items, total = await self.capability_repo.list_paginated(
            limit=limit,
            offset=offset,
            agent_id=agent_id,
            institution_id=institution_id,
            is_active=is_active,
        )
        return CapabilityListResponse(
            items=[CapabilityResponse.model_validate(c) for c in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def update_capability(
        self,
        institution_id: uuid.UUID,
        capability_id: uuid.UUID,
        data: CapabilityUpdate,
        actor: str = "system",
    ) -> CapabilityResponse:
        """Update an existing capability."""
        capability = await self.capability_repo.get_by_id(capability_id)
        if capability is None or capability.institution_id != institution_id:
            raise EntityNotFoundException("Capability", str(capability_id))

        new_single = (
            data.max_amount_per_transaction
            if data.max_amount_per_transaction is not None
            else capability.max_amount_per_transaction
        )
        new_daily = (
            data.max_daily_cumulative_amount
            if data.max_daily_cumulative_amount is not None
            else capability.max_daily_cumulative_amount
        )
        if new_daily < new_single:
            raise AppException(
                message=(
                    f"Invalid capability limits: max_daily_cumulative_amount ({new_daily}) "
                    f"must be >= max_amount_per_transaction ({new_single})"
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="INVALID_CAPABILITY_LIMITS",
            )

        new_start = (
            data.operating_start_hour_utc
            if data.operating_start_hour_utc is not None
            else capability.operating_start_hour_utc
        )
        new_end = (
            data.operating_end_hour_utc
            if data.operating_end_hour_utc is not None
            else capability.operating_end_hour_utc
        )
        if (new_start is not None and new_end is None) or (
            new_start is None and new_end is not None
        ):
            raise AppException(
                message=(
                    "Both operating_start_hour_utc and operating_end_hour_utc must be set "
                    "together, or neither."
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="INVALID_OPERATING_HOURS",
            )

        if data.max_amount_per_transaction is not None:
            capability.max_amount_per_transaction = data.max_amount_per_transaction
        if data.max_daily_cumulative_amount is not None:
            capability.max_daily_cumulative_amount = data.max_daily_cumulative_amount
        if data.allowed_origin_accounts is not None:
            capability.allowed_origin_accounts = data.allowed_origin_accounts
        if data.allowed_destination_accounts is not None:
            capability.allowed_destination_accounts = data.allowed_destination_accounts
        if data.purpose_codes is not None:
            capability.purpose_codes = data.purpose_codes
        if data.operating_start_hour_utc is not None:
            capability.operating_start_hour_utc = data.operating_start_hour_utc
        if data.operating_end_hour_utc is not None:
            capability.operating_end_hour_utc = data.operating_end_hour_utc
        if data.valid_until is not None:
            capability.valid_until = data.valid_until
        if data.is_active is not None:
            capability.is_active = data.is_active
        if data.approved_by is not None:
            capability.approved_by = data.approved_by

        await self.session.flush()

        await self.audit_repo.create_log(
            AuditLogCreate(
                actor=actor,
                event_type="CAPABILITY_UPDATED",
                description=f"Capability '{capability.id}' updated",
                details={
                    "institution_id": str(institution_id),
                    "capability_id": str(capability.id),
                },
            )
        )
        await self.session.flush()
        return CapabilityResponse.model_validate(capability)

    # -------------------------------------------------------------------------
    # Credential Issuance & Revocation
    # -------------------------------------------------------------------------

    async def issue_credential(
        self,
        institution_id: uuid.UUID,
        data: CredentialIssueRequest,
        actor: str = "system",
    ) -> CredentialResponse:
        """Register/issue a cryptographic credential for an active agent."""
        if institution_id != data.institution_id:
            raise AppException(
                message="Institution ID in URL does not match payload",
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="INSTITUTION_MISMATCH",
            )

        agent = await self.agent_repo.get_by_institution_and_id(institution_id, data.agent_id)
        if agent is None:
            raise EntityNotFoundException("Agent", str(data.agent_id))

        if agent.status != AgentStatus.ACTIVE:
            raise AppException(
                message=f"Agent is not ACTIVE (status: {agent.status.value})",
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="AGENT_NOT_ACTIVE",
            )

        now = datetime.now(UTC)
        expires_at = now + timedelta(hours=data.valid_hours)
        credential_id = f"cred_{uuid.uuid4().hex}"

        credential = AgentCredential(
            credential_id=credential_id,
            agent_id=agent.id,
            institution_id=institution_id,
            issuer_id=data.issuer_id,
            audience=data.audience,
            key_version=agent.key_version,
            algorithm=agent.key_algorithm,
            issued_at=now,
            expires_at=expires_at,
            is_revoked=False,
            claims=data.claims,
            signature=data.signature,
        )
        self.session.add(credential)
        await self.session.flush()

        await self.audit_repo.create_log(
            AuditLogCreate(
                actor=actor,
                event_type="CREDENTIAL_ISSUED",
                description=(
                    f"Credential '{credential_id}' issued for agent '{agent.id}' "
                    f"expiring at {expires_at.isoformat()}"
                ),
                details={
                    "institution_id": str(institution_id),
                    "credential_id": credential_id,
                    "agent_id": str(agent.id),
                    "issuer_id": data.issuer_id,
                    "audience": data.audience,
                    "key_version": agent.key_version,
                },
            )
        )
        await self.session.flush()
        return CredentialResponse.model_validate(credential)

    async def get_credential(
        self,
        institution_id: uuid.UUID,
        credential_id: str,
    ) -> CredentialResponse:
        """Fetch credential metadata."""
        cred = await self.credential_repo.get_by_credential_id(credential_id)
        if cred is None or cred.institution_id != institution_id:
            raise EntityNotFoundException("Credential", credential_id)
        return CredentialResponse.model_validate(cred)

    async def list_credentials(
        self,
        limit: int = 50,
        offset: int = 0,
        agent_id: uuid.UUID | None = None,
        institution_id: uuid.UUID | None = None,
        is_revoked: bool | None = None,
    ) -> CredentialListResponse:
        """Fetch paginated credentials."""
        items, total = await self.credential_repo.list_paginated(
            limit=limit,
            offset=offset,
            agent_id=agent_id,
            institution_id=institution_id,
            is_revoked=is_revoked,
        )
        return CredentialListResponse(
            items=[CredentialResponse.model_validate(c) for c in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def revoke_credential(
        self,
        institution_id: uuid.UUID,
        credential_id: str,
        reason: str,
        actor: str = "system",
    ) -> CredentialResponse:
        """Revoke a credential immediately."""
        cred = await self.credential_repo.get_by_credential_id(credential_id)
        if cred is None or cred.institution_id != institution_id:
            raise EntityNotFoundException("Credential", credential_id)

        if cred.is_revoked:
            raise AppException(
                message="Credential is already revoked",
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="CREDENTIAL_ALREADY_REVOKED",
            )

        now = datetime.now(UTC)
        cred.is_revoked = True
        cred.revoked_at = now
        cred.revocation_reason = reason

        await self.session.flush()

        await self.audit_repo.create_log(
            AuditLogCreate(
                actor=actor,
                event_type="CREDENTIAL_REVOKED",
                description=f"Credential '{credential_id}' revoked. Reason: {reason}",
                details={
                    "institution_id": str(institution_id),
                    "credential_id": credential_id,
                    "agent_id": str(cred.agent_id),
                    "reason": reason,
                },
            )
        )
        await self.session.flush()
        return CredentialResponse.model_validate(cred)

    # -------------------------------------------------------------------------
    # Authorization Verification Pipeline
    # -------------------------------------------------------------------------

    async def verify_authorization(
        self,
        req: AuthorizationVerificationRequest,
        actor: str = "system",
    ) -> AuthorizationVerificationResponse:
        """Fail-closed cryptographic and capability verification pipeline."""
        now = datetime.now(UTC)
        reasons: list[str] = []
        is_authorized = False
        matched_capability_id: uuid.UUID | None = None

        # Canonical digest of the transaction intent
        tx_intent_dict = req.transaction.model_dump(exclude_none=True)
        tx_hash = compute_transaction_intent_hash(tx_intent_dict)

        try:
            # 1. Clock skew check
            req_ts = ensure_utc(req.request_timestamp) or now
            skew_seconds = abs((now - req_ts).total_seconds())
            if skew_seconds > MAX_CLOCK_SKEW_SECONDS:
                reasons.append(
                    f"CLOCK_SKEW_EXCEEDED: Request timestamp skew {skew_seconds:.1f}s "
                    f"exceeds tolerance of {MAX_CLOCK_SKEW_SECONDS}s"
                )
                return await self._record_and_return(
                    req, tx_hash, False, reasons, None, now, actor, can_persist_auth_record=False
                )

            # 2. Institution verification
            institution = await self.institution_repo.get_by_id(req.institution_id)
            if institution is None:
                reasons.append("INSTITUTION_NOT_FOUND")
                return await self._record_and_return(
                    req, tx_hash, False, reasons, None, now, actor, can_persist_auth_record=False
                )
            if institution.status != InstitutionStatus.ACTIVE:
                reasons.append(f"INSTITUTION_NOT_ACTIVE: Status is '{institution.status.value}'")
                return await self._record_and_return(
                    req, tx_hash, False, reasons, None, now, actor, can_persist_auth_record=False
                )

            # 3. Agent lookup & lifecycle check with row-level locking for concurrency safety
            agent = await self.agent_repo.get_by_id(req.agent_id, for_update=True)
            if agent is None:
                reasons.append("AGENT_NOT_FOUND")
                return await self._record_and_return(
                    req, tx_hash, False, reasons, None, now, actor, can_persist_auth_record=False
                )

            if agent.institution_id != req.institution_id:
                reasons.append("INSTITUTION_MISMATCH")
                return await self._record_and_return(
                    req, tx_hash, False, reasons, None, now, actor, can_persist_auth_record=True
                )

            if agent.status != AgentStatus.ACTIVE:
                reasons.append(f"AGENT_NOT_ACTIVE: Agent status is '{agent.status.value}'")
                return await self._record_and_return(
                    req, tx_hash, False, reasons, None, now, actor, can_persist_auth_record=True
                )

            agent_valid_until = ensure_utc(agent.valid_until)
            if agent_valid_until is not None and agent_valid_until < now:
                reasons.append("AGENT_EXPIRED")
                return await self._record_and_return(
                    req, tx_hash, False, reasons, None, now, actor, can_persist_auth_record=True
                )

            # 4. Replay check (unique nonce) & Nonce persistence
            if await self.auth_repo.is_nonce_processed(req.nonce):
                reasons.append("REPLAY_DETECTED_NONCE_REUSED")
                return await self._record_and_return(
                    req, tx_hash, False, reasons, None, now, actor, can_persist_auth_record=True
                )

            # Record the nonce immediately in the session
            await self.auth_repo.record_nonce(
                nonce=req.nonce,
                agent_id=req.agent_id,
                request_timestamp=req_ts,
                expires_at=now + timedelta(seconds=MAX_CLOCK_SKEW_SECONDS * 2),
            )

            # 5. Credential lookup & state check
            cred = await self.credential_repo.get_by_credential_id(req.credential_id)
            if cred is None:
                reasons.append("CREDENTIAL_NOT_FOUND")
                return await self._record_and_return(
                    req, tx_hash, False, reasons, None, now, actor, can_persist_auth_record=True
                )

            if cred.agent_id != req.agent_id:
                reasons.append("CREDENTIAL_AGENT_MISMATCH")
                return await self._record_and_return(
                    req, tx_hash, False, reasons, None, now, actor, can_persist_auth_record=True
                )

            if cred.institution_id != req.institution_id:
                reasons.append("CREDENTIAL_INSTITUTION_MISMATCH")
                return await self._record_and_return(
                    req, tx_hash, False, reasons, None, now, actor, can_persist_auth_record=True
                )

            if cred.is_revoked:
                reasons.append("CREDENTIAL_REVOKED")
                return await self._record_and_return(
                    req, tx_hash, False, reasons, None, now, actor, can_persist_auth_record=True
                )

            cred_expires_at = ensure_utc(cred.expires_at)
            if cred_expires_at is not None and cred_expires_at < now:
                reasons.append("CREDENTIAL_EXPIRED")
                return await self._record_and_return(
                    req, tx_hash, False, reasons, None, now, actor, can_persist_auth_record=True
                )

            if cred.key_version != agent.key_version:
                reasons.append("KEY_VERSION_MISMATCH")
                return await self._record_and_return(
                    req, tx_hash, False, reasons, None, now, actor, can_persist_auth_record=True
                )

            if req.expected_audience is not None and cred.audience != req.expected_audience:
                reasons.append(
                    f"INVALID_CREDENTIAL_AUDIENCE: Expected '{req.expected_audience}', "
                    f"got '{cred.audience}'"
                )
                return await self._record_and_return(
                    req, tx_hash, False, reasons, None, now, actor, can_persist_auth_record=True
                )

            if req.expected_issuer is not None and cred.issuer_id != req.expected_issuer:
                reasons.append(
                    f"INVALID_CREDENTIAL_ISSUER: Expected '{req.expected_issuer}', "
                    f"got '{cred.issuer_id}'"
                )
                return await self._record_and_return(
                    req, tx_hash, False, reasons, None, now, actor, can_persist_auth_record=True
                )

            # 6. Cryptographic signature verification
            if agent.key_algorithm not in SUPPORTED_SIGNING_ALGORITHMS:
                reasons.append(f"UNSUPPORTED_SIGNING_ALGORITHM: '{agent.key_algorithm}'")
                return await self._record_and_return(
                    req, tx_hash, False, reasons, None, now, actor, can_persist_auth_record=True
                )

            canonical_auth_payload = {
                "credential_id": req.credential_id,
                "agent_id": str(req.agent_id),
                "institution_id": str(req.institution_id),
                "nonce": req.nonce,
                "request_timestamp": req.request_timestamp.isoformat(),
                "transaction_hash": tx_hash,
            }

            try:
                sig_valid = verify_signature(
                    public_key_pem=agent.public_key,
                    payload=canonical_auth_payload,
                    signature_hex=req.signature,
                    algorithm=agent.key_algorithm,
                )
                if not sig_valid and "+00:00" in canonical_auth_payload["request_timestamp"]:
                    alt_payload = dict(canonical_auth_payload)
                    alt_payload["request_timestamp"] = canonical_auth_payload[
                        "request_timestamp"
                    ].replace("+00:00", "Z")
                    sig_valid = verify_signature(
                        public_key_pem=agent.public_key,
                        payload=alt_payload,
                        signature_hex=req.signature,
                        algorithm=agent.key_algorithm,
                    )
                if not sig_valid:
                    reasons.append("INVALID_SIGNATURE")
                    return await self._record_and_return(
                        req, tx_hash, False, reasons, None, now, actor, can_persist_auth_record=True
                    )
            except Exception as err:
                logger.warning("Signature verification raised error: %s", err)
                reasons.append(f"INVALID_SIGNATURE: {err}")
                return await self._record_and_return(
                    req, tx_hash, False, reasons, None, now, actor, can_persist_auth_record=True
                )

            # 7. Capability evaluation
            active_capabilities = await self.capability_repo.get_active_by_agent(agent.id)
            if not active_capabilities:
                reasons.append("NO_ACTIVE_CAPABILITIES")
                return await self._record_and_return(
                    req, tx_hash, False, reasons, None, now, actor, can_persist_auth_record=True
                )

            # Check 24-hour spend aggregate scoped to currency
            past_24h = now - timedelta(hours=24)
            spend_24h = await self.auth_repo.get_24h_spend_sum(
                agent.id, since=past_24h, currency=req.transaction.currency
            )
            new_projected_spend = spend_24h + req.transaction.amount

            matched_cap: Capability | None = None
            cap_rejection_reasons: list[str] = []

            for cap in active_capabilities:
                # Check capability validity window
                cap_from = ensure_utc(cap.valid_from) or now
                cap_until = ensure_utc(cap.valid_until) or now
                if now < cap_from or now > cap_until:
                    cap_rejection_reasons.append(f"Capability '{cap.name}' validity period expired")
                    continue

                # Check operating hours (UTC)
                if (
                    cap.operating_start_hour_utc is not None
                    and cap.operating_end_hour_utc is not None
                ):
                    current_hour = now.hour
                    if not (
                        cap.operating_start_hour_utc <= current_hour <= cap.operating_end_hour_utc
                    ):
                        cap_rejection_reasons.append(
                            f"Current hour {current_hour} outside operating window "
                            f"[{cap.operating_start_hour_utc}, {cap.operating_end_hour_utc}]"
                        )
                        continue

                # Check permitted transaction types
                if req.transaction.transaction_type not in cap.permitted_transaction_types:
                    cap_rejection_reasons.append(
                        f"Transaction type '{req.transaction.transaction_type}' not permitted"
                    )
                    continue

                # Check permitted currencies
                if req.transaction.currency not in cap.permitted_currencies:
                    cap_rejection_reasons.append(
                        f"Currency '{req.transaction.currency}' not permitted"
                    )
                    continue

                # Check single transaction limit
                if req.transaction.amount > cap.max_amount_per_transaction:
                    cap_rejection_reasons.append(
                        f"Amount {req.transaction.amount} exceeds single limit "
                        f"{cap.max_amount_per_transaction}"
                    )
                    continue

                # Check 24-hour cumulative spending ceiling
                if new_projected_spend > cap.max_daily_cumulative_amount:
                    cap_rejection_reasons.append(
                        f"Projected 24h spend {new_projected_spend} exceeds daily limit "
                        f"{cap.max_daily_cumulative_amount}"
                    )
                    continue

                # Check origin account whitelist
                if cap.allowed_origin_accounts is not None and (
                    req.transaction.origin_account_number not in cap.allowed_origin_accounts
                ):
                    cap_rejection_reasons.append(
                        f"Origin account '{req.transaction.origin_account_number}' not whitelisted"
                    )
                    continue

                # Check destination account whitelist
                if cap.allowed_destination_accounts is not None and (
                    req.transaction.destination_account_number
                    not in cap.allowed_destination_accounts
                ):
                    cap_rejection_reasons.append(
                        f"Destination account '{req.transaction.destination_account_number}' "
                        f"not whitelisted"
                    )
                    continue

                # Check purpose codes
                if (
                    cap.purpose_codes is not None
                    and req.transaction.purpose_code is not None
                    and req.transaction.purpose_code not in cap.purpose_codes
                ):
                    cap_rejection_reasons.append(
                        f"Purpose code '{req.transaction.purpose_code}' not permitted"
                    )
                    continue

                # All capability constraints satisfied!
                matched_cap = cap
                break

            if matched_cap is None:
                reasons.extend(cap_rejection_reasons or ["CAPABILITY_LIMITS_EXCEEDED"])
                return await self._record_and_return(
                    req, tx_hash, False, reasons, None, now, actor, can_persist_auth_record=True
                )

            # Verification successful!
            is_authorized = True
            matched_capability_id = matched_cap.id
            reasons.append("AUTHORIZED")

            return await self._record_and_return(
                req,
                tx_hash,
                is_authorized,
                reasons,
                matched_capability_id,
                now,
                actor,
                can_persist_auth_record=True,
            )

        except IntegrityError:
            # Replay nonce unique constraint violation caught by database
            await self.session.rollback()
            reasons.append("REPLAY_DETECTED_NONCE_REUSED")
            # In a new sub-transaction, record the rejected authorization
            return await self._record_and_return(
                req, tx_hash, False, reasons, None, now, actor, can_persist_auth_record=True
            )

    async def _record_and_return(
        self,
        req: AuthorizationVerificationRequest,
        tx_hash: str,
        is_authorized: bool,
        reasons: list[str],
        capability_id: uuid.UUID | None,
        now: datetime,
        actor: str,
        can_persist_auth_record: bool = True,
    ) -> AuthorizationVerificationResponse:
        """Persist immutable authorization audit record and return response."""
        decision = "AUTHORIZED" if is_authorized else "REJECTED"

        if can_persist_auth_record:
            auth_record = AuthorizationRecord(
                agent_id=req.agent_id,
                institution_id=req.institution_id,
                credential_id=req.credential_id,
                nonce=req.nonce,
                decision=decision,
                decision_reasons=reasons,
                transaction_hash=tx_hash,
                amount=req.transaction.amount,
                currency=req.transaction.currency,
                capability_id=capability_id,
                evaluated_at=now,
            )
            self.session.add(auth_record)
            await self.session.flush()

        await self.audit_repo.create_log(
            AuditLogCreate(
                actor=actor,
                event_type=f"AUTHORIZATION_{decision}",
                description=(
                    f"Agent '{req.agent_id}' authorization evaluation result: {decision}. "
                    f"Reasons: {', '.join(reasons)}"
                ),
                details={
                    "institution_id": str(req.institution_id),
                    "agent_id": str(req.agent_id),
                    "credential_id": req.credential_id,
                    "nonce": req.nonce,
                    "decision": decision,
                    "reasons": reasons,
                    "amount": str(req.transaction.amount),
                    "currency": req.transaction.currency,
                },
            )
        )
        await self.session.flush()

        return AuthorizationVerificationResponse(
            authorized=is_authorized,
            decision=decision,
            reasons=reasons,
            agent_id=req.agent_id,
            institution_id=req.institution_id,
            credential_id=req.credential_id,
            nonce=req.nonce,
            evaluated_at=now,
        )
