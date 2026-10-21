import hashlib
import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.core.errors import AppException, EntityNotFoundException
from sentinel_chain_drive.db.models.account import (
    VALID_ACCOUNT_TRANSITIONS,
    Account,
    AccountStatus,
)
from sentinel_chain_drive.db.models.drunix_outbox import DrunixEventType
from sentinel_chain_drive.db.models.institution import (
    VALID_INSTITUTION_TRANSITIONS,
    Institution,
    InstitutionStatus,
)
from sentinel_chain_drive.db.models.transaction import (
    VALID_TRANSACTION_TRANSITIONS,
    Transaction,
    TransactionStatus,
)
from sentinel_chain_drive.repositories.account_repository import AccountRepository
from sentinel_chain_drive.repositories.audit_repository import AuditRepository
from sentinel_chain_drive.repositories.drunix_outbox_repository import DrunixOutboxRepository
from sentinel_chain_drive.repositories.institution_repository import InstitutionRepository
from sentinel_chain_drive.repositories.transaction_repository import TransactionRepository
from sentinel_chain_drive.schemas.account import (
    AccountCreate,
    AccountListResponse,
    AccountResponse,
    AccountStatusUpdate,
)
from sentinel_chain_drive.schemas.audit import AuditLogCreate
from sentinel_chain_drive.schemas.institution import (
    InstitutionCreate,
    InstitutionListResponse,
    InstitutionResponse,
    InstitutionStatusUpdate,
    InstitutionUpdate,
)
from sentinel_chain_drive.schemas.transaction import (
    SimulationAction,
    TransactionListResponse,
    TransactionResponse,
    TransactionSimulationActionRequest,
    TransactionSubmitRequest,
)

logger = logging.getLogger(__name__)

# Maximum allowed transaction amount for simulation to prevent overflow
MAX_SIMULATION_TRANSACTION_AMOUNT = Decimal("100000000.0000")
SUPPORTED_CURRENCIES = {"USD", "EUR", "GBP"}


class BankingService:
    """Orchestrates banking domain operations, lifecycle rules, and transaction boundaries."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.institution_repo = InstitutionRepository(session)
        self.account_repo = AccountRepository(session)
        self.transaction_repo = TransactionRepository(session)
        self.audit_repo = AuditRepository(session)

    # ---------------------------------------------------------------------------
    # Institution Operations
    # ---------------------------------------------------------------------------

    async def create_institution(
        self,
        data: InstitutionCreate,
        actor: str = "system",
        correlation_id: str | None = None,
    ) -> InstitutionResponse:
        """Register a new simulated financial institution."""
        # 1. Uniqueness check on institution code
        existing_code = await self.institution_repo.get_by_code(data.institution_code)
        if existing_code is not None:
            raise AppException(
                message=f"Institution code '{data.institution_code}' is already registered.",
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="DUPLICATE_INSTITUTION_CODE",
            )

        # 2. Uniqueness check on routing identifier
        existing_routing = await self.institution_repo.get_by_routing(data.routing_identifier)
        if existing_routing is not None:
            raise AppException(
                message=f"Routing identifier '{data.routing_identifier}' is already in use.",
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="DUPLICATE_ROUTING_ID",
            )

        institution = Institution(
            institution_code=data.institution_code.upper(),
            name=data.name,
            routing_identifier=data.routing_identifier,
            status=InstitutionStatus.ACTIVE,
            settings=data.settings,
        )
        created = await self.institution_repo.add(institution)

        # Audit trail
        await self.audit_repo.create_log(
            AuditLogCreate(
                event_type="INSTITUTION_CREATED",
                severity="INFO",
                actor=actor,
                description=f"Created institution {created.institution_code} ({created.name})",
                correlation_id=correlation_id,
                details={
                    "institution_id": str(created.id),
                    "routing_id": created.routing_identifier,
                },
            )
        )
        return InstitutionResponse.model_validate(created)

    async def get_institution(self, institution_id: uuid.UUID) -> InstitutionResponse:
        """Retrieve an institution by internal identifier."""
        institution = await self.institution_repo.get_by_id(institution_id)
        if institution is None:
            raise EntityNotFoundException("Institution", str(institution_id))
        return InstitutionResponse.model_validate(institution)

    async def list_institutions(
        self,
        limit: int = 50,
        offset: int = 0,
        status_filter: InstitutionStatus | None = None,
    ) -> InstitutionListResponse:
        """Fetch a paginated list of institutions."""
        items, total = await self.institution_repo.list_paginated(
            limit=limit, offset=offset, status=status_filter
        )
        return InstitutionListResponse(
            items=[InstitutionResponse.model_validate(inst) for inst in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def update_institution(
        self,
        institution_id: uuid.UUID,
        data: InstitutionUpdate,
        actor: str = "system",
        correlation_id: str | None = None,
    ) -> InstitutionResponse:
        """Update permitted metadata of an existing institution."""
        institution = await self.institution_repo.get_by_id(institution_id)
        if institution is None:
            raise EntityNotFoundException("Institution", str(institution_id))

        if data.name is not None:
            institution.name = data.name
        if data.settings is not None:
            institution.settings = data.settings

        await self.audit_repo.create_log(
            AuditLogCreate(
                event_type="INSTITUTION_METADATA_UPDATED",
                severity="INFO",
                actor=actor,
                description=f"Updated metadata for institution {institution.institution_code}",
                correlation_id=correlation_id,
                details={"institution_id": str(institution.id)},
            )
        )
        return InstitutionResponse.model_validate(institution)

    async def update_institution_status(
        self,
        institution_id: uuid.UUID,
        data: InstitutionStatusUpdate,
        actor: str = "system",
        correlation_id: str | None = None,
    ) -> InstitutionResponse:
        """Transition an institution's operational status adhering to valid transitions."""
        institution = await self.institution_repo.get_by_id(institution_id)
        if institution is None:
            raise EntityNotFoundException("Institution", str(institution_id))

        current_status = institution.status
        if current_status == data.status:
            return InstitutionResponse.model_validate(institution)

        allowed_targets = VALID_INSTITUTION_TRANSITIONS.get(current_status, set())
        if data.status not in allowed_targets:
            raise AppException(
                message=(
                    f"Invalid institution status transition from {current_status.value} "
                    f"to {data.status.value}."
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="INVALID_STATUS_TRANSITION",
            )

        institution.status = data.status

        await self.audit_repo.create_log(
            AuditLogCreate(
                event_type="INSTITUTION_STATUS_CHANGED",
                severity="WARNING" if data.status != InstitutionStatus.ACTIVE else "INFO",
                actor=actor,
                description=(
                    f"Transitioned institution {institution.institution_code} "
                    f"from {current_status.value} to {data.status.value}"
                ),
                correlation_id=correlation_id,
                details={
                    "institution_id": str(institution.id),
                    "previous_status": current_status.value,
                    "new_status": data.status.value,
                    "reason": data.reason,
                },
            )
        )
        return InstitutionResponse.model_validate(institution)

    # ---------------------------------------------------------------------------
    # Account Operations
    # ---------------------------------------------------------------------------

    async def create_account(
        self,
        data: AccountCreate,
        actor: str = "system",
        correlation_id: str | None = None,
        requesting_institution_id: uuid.UUID | None = None,
    ) -> AccountResponse:
        """Create a synthetic account associated with an active institution."""
        # Enforce institution boundary if header provided
        if requesting_institution_id and requesting_institution_id != data.institution_id:
            raise AppException(
                message="Cannot create account for another institution.",
                status_code=status.HTTP_403_FORBIDDEN,
                error_code="CROSS_INSTITUTION_ACCESS_FORBIDDEN",
            )

        # 1. Verify institution exists and is ACTIVE
        institution = await self.institution_repo.get_by_id(data.institution_id)
        if institution is None:
            raise EntityNotFoundException("Institution", str(data.institution_id))
        if institution.status != InstitutionStatus.ACTIVE:
            raise AppException(
                message=(
                    f"Cannot create account: Institution '{institution.institution_code}' "
                    f"is {institution.status.value}."
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="INSTITUTION_NOT_ACTIVE",
            )

        # 2. Verify currency support
        if data.currency not in SUPPORTED_CURRENCIES:
            raise AppException(
                message=(
                    f"Currency '{data.currency}' is unsupported. "
                    f"Supported currencies: {sorted(SUPPORTED_CURRENCIES)}"
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="UNSUPPORTED_CURRENCY",
            )

        # 3. Check account number uniqueness
        existing_acct = await self.account_repo.get_by_number(data.account_number)
        if existing_acct is not None:
            raise AppException(
                message=f"Account number '{data.account_number}' already exists.",
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="DUPLICATE_ACCOUNT_NUMBER",
            )

        account = Account(
            institution_id=data.institution_id,
            account_number=data.account_number,
            account_type=data.account_type,
            currency=data.currency,
            balance=data.initial_balance,
            status=AccountStatus.ACTIVE,
            risk_flags=data.risk_flags,
        )
        created = await self.account_repo.add(account)

        await self.audit_repo.create_log(
            AuditLogCreate(
                event_type="ACCOUNT_CREATED",
                severity="INFO",
                actor=actor,
                description=f"Created {data.account_type.value} account {data.account_number}",
                correlation_id=correlation_id,
                details={
                    "account_id": str(created.id),
                    "institution_id": str(created.institution_id),
                    "currency": created.currency,
                    "initial_balance": str(created.balance),
                },
            )
        )
        return AccountResponse.model_validate(created)

    async def get_account(
        self,
        account_id: uuid.UUID,
        requesting_institution_id: uuid.UUID | None = None,
    ) -> AccountResponse:
        """Fetch an account by ID, verifying tenant boundary if requested."""
        account = await self.account_repo.get_by_id(account_id)
        if account is None:
            raise EntityNotFoundException("Account", str(account_id))

        if requesting_institution_id and requesting_institution_id != account.institution_id:
            raise AppException(
                message="Access to account belonging to another institution is forbidden.",
                status_code=status.HTTP_403_FORBIDDEN,
                error_code="CROSS_INSTITUTION_ACCESS_FORBIDDEN",
            )
        return AccountResponse.model_validate(account)

    async def list_accounts(
        self,
        limit: int = 50,
        offset: int = 0,
        institution_id: uuid.UUID | None = None,
        status_filter: AccountStatus | None = None,
        requesting_institution_id: uuid.UUID | None = None,
    ) -> AccountListResponse:
        """Fetch a paginated list of accounts with tenant boundary enforcement."""
        effective_institution_id = institution_id
        if requesting_institution_id:
            if institution_id and institution_id != requesting_institution_id:
                raise AppException(
                    message="Cannot query accounts of another institution.",
                    status_code=status.HTTP_403_FORBIDDEN,
                    error_code="CROSS_INSTITUTION_ACCESS_FORBIDDEN",
                )
            effective_institution_id = requesting_institution_id

        items, total = await self.account_repo.list_paginated(
            limit=limit,
            offset=offset,
            institution_id=effective_institution_id,
            status=status_filter,
        )
        return AccountListResponse(
            items=[AccountResponse.model_validate(acct) for acct in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def update_account_status(
        self,
        account_id: uuid.UUID,
        data: AccountStatusUpdate,
        actor: str = "system",
        correlation_id: str | None = None,
        requesting_institution_id: uuid.UUID | None = None,
    ) -> AccountResponse:
        """Update account status enforcing state machine rules."""
        account = await self.account_repo.get_by_id(account_id)
        if account is None:
            raise EntityNotFoundException("Account", str(account_id))

        if requesting_institution_id and requesting_institution_id != account.institution_id:
            raise AppException(
                message="Cannot update account belonging to another institution.",
                status_code=status.HTTP_403_FORBIDDEN,
                error_code="CROSS_INSTITUTION_ACCESS_FORBIDDEN",
            )

        current_status = account.status
        if current_status == data.status:
            return AccountResponse.model_validate(account)

        allowed_targets = VALID_ACCOUNT_TRANSITIONS.get(current_status, set())
        if data.status not in allowed_targets:
            raise AppException(
                message=(
                    f"Invalid account status transition from {current_status.value} "
                    f"to {data.status.value}."
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="INVALID_STATUS_TRANSITION",
            )

        account.status = data.status

        await self.audit_repo.create_log(
            AuditLogCreate(
                event_type="ACCOUNT_STATUS_CHANGED",
                severity="WARNING" if data.status != AccountStatus.ACTIVE else "INFO",
                actor=actor,
                description=f"Transitioned account {account.account_number} to {data.status.value}",
                correlation_id=correlation_id,
                details={
                    "account_id": str(account.id),
                    "previous_status": current_status.value,
                    "new_status": data.status.value,
                    "reason": data.reason,
                },
            )
        )
        return AccountResponse.model_validate(account)

    # ---------------------------------------------------------------------------
    # Transaction Domain & Lifecycle
    # ---------------------------------------------------------------------------

    async def submit_transaction(
        self,
        data: TransactionSubmitRequest,
        actor: str = "system",
        correlation_id: str | None = None,
        requesting_institution_id: uuid.UUID | None = None,
    ) -> tuple[TransactionResponse, bool]:
        """Submit a simulated transaction enforcing idempotency, validation, and PENDING state.

        Returns:
            (TransactionResponse, is_newly_created)
        """
        # Tenant boundary check
        if requesting_institution_id and requesting_institution_id != data.origin_institution_id:
            raise AppException(
                message="Cannot submit transaction on behalf of another origin institution.",
                status_code=status.HTTP_403_FORBIDDEN,
                error_code="CROSS_INSTITUTION_ACCESS_FORBIDDEN",
            )

        # 1. Idempotency Check
        existing_tx = await self.transaction_repo.get_by_idempotency_key(data.idempotency_key)
        if existing_tx is not None:
            # Check if payload parameters match exactly
            matches = (
                existing_tx.amount == data.amount
                and existing_tx.currency == data.currency
                and existing_tx.origin_institution_id == data.origin_institution_id
                and existing_tx.origin_account_id == data.origin_account_id
                and existing_tx.destination_institution_id == data.destination_institution_id
                and existing_tx.destination_account_id == data.destination_account_id
                and existing_tx.transaction_type == data.transaction_type
                and existing_tx.purpose_code == data.purpose_code
            )
            if matches:
                logger.info(
                    "Idempotent transaction submission matched existing record %s",
                    existing_tx.id,
                )
                return TransactionResponse.model_validate(existing_tx), False
            raise AppException(
                message=(
                    f"Idempotency key '{data.idempotency_key}' was previously used with "
                    f"conflicting transaction parameters."
                ),
                status_code=status.HTTP_409_CONFLICT,
                error_code="IDEMPOTENCY_CONFLICT",
            )

        # 2. Amount and Currency Validation
        if data.amount <= Decimal("0.0000"):
            raise AppException(
                message="Transaction amount must be strictly greater than zero.",
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="INVALID_AMOUNT",
            )
        if data.amount > MAX_SIMULATION_TRANSACTION_AMOUNT:
            raise AppException(
                message=(
                    f"Transaction amount exceeds the simulation limit of "
                    f"{MAX_SIMULATION_TRANSACTION_AMOUNT}."
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="EXCESSIVE_AMOUNT",
            )
        if data.currency not in SUPPORTED_CURRENCIES:
            raise AppException(
                message=(
                    f"Currency '{data.currency}' is unsupported. "
                    f"Supported: {sorted(SUPPORTED_CURRENCIES)}"
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="UNSUPPORTED_CURRENCY",
            )

        # 3. Origin and Destination Institution Validation
        origin_inst = await self.institution_repo.get_by_id(data.origin_institution_id)
        if origin_inst is None:
            raise AppException(
                message="Origin institution does not exist.",
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="INVALID_ORIGIN_INSTITUTION",
            )
        if origin_inst.status != InstitutionStatus.ACTIVE:
            raise AppException(
                message=(
                    f"Origin institution '{origin_inst.institution_code}' is "
                    f"{origin_inst.status.value}; transactions not permitted."
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="ORIGIN_INSTITUTION_INACTIVE",
            )

        dest_inst = await self.institution_repo.get_by_id(data.destination_institution_id)
        if dest_inst is None:
            raise AppException(
                message="Destination institution does not exist.",
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="INVALID_DESTINATION_INSTITUTION",
            )
        if dest_inst.status != InstitutionStatus.ACTIVE:
            raise AppException(
                message=(
                    f"Destination institution '{dest_inst.institution_code}' is "
                    f"{dest_inst.status.value}; transactions not permitted."
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="DESTINATION_INSTITUTION_INACTIVE",
            )

        # 4. Origin and Destination Account Validation
        origin_acct = await self.account_repo.get_by_id(data.origin_account_id)
        if origin_acct is None:
            raise AppException(
                message="Origin account does not exist.",
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="INVALID_ORIGIN_ACCOUNT",
            )
        if origin_acct.institution_id != data.origin_institution_id:
            raise AppException(
                message="Origin account does not belong to the stated origin institution.",
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="ACCOUNT_INSTITUTION_MISMATCH",
            )
        if origin_acct.status != AccountStatus.ACTIVE:
            raise AppException(
                message=(
                    f"Origin account '{origin_acct.account_number}' is "
                    f"{origin_acct.status.value}; transactions not permitted."
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="ORIGIN_ACCOUNT_NOT_ACTIVE",
            )
        if origin_acct.currency != data.currency:
            raise AppException(
                message=(
                    f"Currency mismatch: Origin account is in '{origin_acct.currency}', "
                    f"requested '{data.currency}'."
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="CURRENCY_MISMATCH",
            )

        dest_acct = await self.account_repo.get_by_id(data.destination_account_id)
        if dest_acct is None:
            raise AppException(
                message="Destination account does not exist.",
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="INVALID_DESTINATION_ACCOUNT",
            )
        if dest_acct.institution_id != data.destination_institution_id:
            raise AppException(
                message="Destination account does not belong to stated institution.",
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="ACCOUNT_INSTITUTION_MISMATCH",
            )
        if dest_acct.status != AccountStatus.ACTIVE:
            raise AppException(
                message=(
                    f"Destination account '{dest_acct.account_number}' is "
                    f"{dest_acct.status.value}; cannot accept funds."
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="DESTINATION_ACCOUNT_NOT_ACTIVE",
            )
        if dest_acct.currency != data.currency:
            raise AppException(
                message=(
                    f"Currency mismatch: Destination account is in '{dest_acct.currency}', "
                    f"requested '{data.currency}'."
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="CURRENCY_MISMATCH",
            )

        # 5. Persist Transaction in PENDING_AUTHORIZATION state
        # IMPORTANT: A submitted transaction is NOT authorized or settled.
        transaction = Transaction(
            idempotency_key=data.idempotency_key,
            origin_institution_id=data.origin_institution_id,
            origin_account_id=data.origin_account_id,
            destination_institution_id=data.destination_institution_id,
            destination_account_id=data.destination_account_id,
            amount=data.amount,
            currency=data.currency,
            transaction_type=data.transaction_type,
            status=TransactionStatus.PENDING_AUTHORIZATION,
            purpose_code=data.purpose_code,
            correlation_id=correlation_id,
            simulation_metadata=data.simulation_metadata,
        )

        try:
            created_tx = await self.transaction_repo.create_with_initial_history(
                transaction=transaction,
                reason="Transaction submitted and validated; awaiting policy authorization",
                actor=actor,
                correlation_id=correlation_id,
            )
        except IntegrityError:
            await self.session.rollback()
            existing_tx = await self.transaction_repo.get_by_idempotency_key(data.idempotency_key)
            if existing_tx is not None:
                matches = (
                    existing_tx.amount == data.amount
                    and existing_tx.currency == data.currency
                    and existing_tx.origin_institution_id == data.origin_institution_id
                    and existing_tx.origin_account_id == data.origin_account_id
                    and existing_tx.destination_institution_id == data.destination_institution_id
                    and existing_tx.destination_account_id == data.destination_account_id
                    and existing_tx.transaction_type == data.transaction_type
                    and existing_tx.purpose_code == data.purpose_code
                )
                if matches:
                    return TransactionResponse.model_validate(existing_tx), False
                raise AppException(
                    message=(
                        f"Idempotency key '{data.idempotency_key}' was previously used with "
                        f"conflicting transaction parameters."
                    ),
                    status_code=status.HTTP_409_CONFLICT,
                    error_code="IDEMPOTENCY_CONFLICT",
                ) from None
            raise

        # Atomically persist domain outbox event
        outbox_repo = DrunixOutboxRepository(self.session)
        sub_iso = (created_tx.created_at or datetime.now(UTC)).isoformat()
        outbox_payload = {
            "transaction_id": str(created_tx.id),
            "idempotency_key": created_tx.idempotency_key,
            "origin_institution_id": str(created_tx.origin_institution_id),
            "destination_institution_id": str(created_tx.destination_institution_id),
            "amount": str(created_tx.amount),
            "currency": created_tx.currency,
            "purpose_code": created_tx.purpose_code,
            "submitted_at": sub_iso,
        }
        commitment = hashlib.sha256(
            f"{created_tx.id}:SUBMITTED:{created_tx.amount}:{created_tx.currency}".encode()
        ).hexdigest()
        await outbox_repo.create_event(
            institution_id=created_tx.origin_institution_id,
            event_type=DrunixEventType.TRANSACTION_SUBMITTED,
            aggregate_type="TRANSACTION",
            aggregate_id=created_tx.id,
            idempotency_key=f"event:tx_submitted:{created_tx.id}",
            commitment_hash=commitment,
            payload=outbox_payload,
            correlation_id=correlation_id,
            event_category="DOMAIN",
            ordering_key=f"tx:{created_tx.id}",
            sequence_number=1,
        )

        await self.audit_repo.create_log(
            AuditLogCreate(
                event_type="TRANSACTION_SUBMITTED",
                severity="INFO",
                actor=actor,
                description=(
                    f"Transaction {created_tx.id} submitted for "
                    f"{created_tx.amount} {created_tx.currency}"
                ),
                correlation_id=correlation_id,
                details={
                    "transaction_id": str(created_tx.id),
                    "idempotency_key": created_tx.idempotency_key,
                    "amount": str(created_tx.amount),
                    "currency": created_tx.currency,
                },
            )
        )
        # Reload with history to return full response
        loaded_tx = await self.transaction_repo.get_with_history(created_tx.id)
        return TransactionResponse.model_validate(loaded_tx), True

    async def get_transaction(
        self,
        transaction_id: uuid.UUID,
        requesting_institution_id: uuid.UUID | None = None,
    ) -> TransactionResponse:
        """Retrieve a transaction by ID with full status history."""
        tx = await self.transaction_repo.get_with_history(transaction_id)
        if tx is None:
            raise EntityNotFoundException("Transaction", str(transaction_id))

        if requesting_institution_id:
            is_involved = requesting_institution_id in (
                tx.origin_institution_id,
                tx.destination_institution_id,
            )
            if not is_involved:
                raise AppException(
                    message="Access to transaction belonging to other institutions is forbidden.",
                    status_code=status.HTTP_403_FORBIDDEN,
                    error_code="CROSS_INSTITUTION_ACCESS_FORBIDDEN",
                )
        return TransactionResponse.model_validate(tx)

    async def list_transactions(
        self,
        limit: int = 50,
        offset: int = 0,
        institution_id: uuid.UUID | None = None,
        status_filter: TransactionStatus | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        requesting_institution_id: uuid.UUID | None = None,
    ) -> TransactionListResponse:
        """List transactions with optional filters and tenant boundary enforcement."""
        effective_institution_id = institution_id
        if requesting_institution_id:
            if institution_id and institution_id != requesting_institution_id:
                raise AppException(
                    message="Cannot query transactions of another institution.",
                    status_code=status.HTTP_403_FORBIDDEN,
                    error_code="CROSS_INSTITUTION_ACCESS_FORBIDDEN",
                )
            effective_institution_id = requesting_institution_id

        items, total = await self.transaction_repo.list_paginated(
            limit=limit,
            offset=offset,
            institution_id=effective_institution_id,
            status=status_filter,
            from_time=from_time,
            to_time=to_time,
        )
        return TransactionListResponse(
            items=[TransactionResponse.model_validate(tx) for tx in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def execute_simulation_action(
        self,
        transaction_id: uuid.UUID,
        data: TransactionSimulationActionRequest,
        actor: str = "simulation_engine",
        correlation_id: str | None = None,
    ) -> TransactionResponse:
        """Perform an explicit simulation action (SIMULATE_SETTLE, SIMULATE_HOLD, CANCEL)."""
        tx = await self.transaction_repo.get_with_history(transaction_id)
        if tx is None:
            raise EntityNotFoundException("Transaction", str(transaction_id))

        # Map simulation action to target transaction status
        action_mapping = {
            SimulationAction.SIMULATE_AUTHORIZE: TransactionStatus.AUTHORIZED,
            SimulationAction.AUTHORIZE: TransactionStatus.AUTHORIZED,
            SimulationAction.SIMULATE_SETTLE: TransactionStatus.SETTLED,
            SimulationAction.SETTLE: TransactionStatus.SETTLED,
            SimulationAction.SIMULATE_HOLD: TransactionStatus.HELD,
            SimulationAction.HOLD: TransactionStatus.HELD,
            SimulationAction.SIMULATE_REJECT: TransactionStatus.REJECTED,
            SimulationAction.REJECT: TransactionStatus.REJECTED,
            SimulationAction.CANCEL: TransactionStatus.CANCELLED,
        }
        target_status = action_mapping[data.action]

        current_status = tx.status
        allowed_targets = VALID_TRANSACTION_TRANSITIONS.get(current_status, set())
        if target_status not in allowed_targets:
            raise AppException(
                message=(
                    f"Simulation action '{data.action.value}' not allowed: Invalid "
                    f"transition from {current_status.value} to {target_status.value}."
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="INVALID_STATUS_TRANSITION",
            )

        settled_at = datetime.now(UTC) if target_status == TransactionStatus.SETTLED else None

        updated_tx = await self.transaction_repo.update_status_with_history(
            transaction=tx,
            new_status=target_status,
            reason=data.reason or f"Executed simulation action {data.action.value}",
            actor=actor,
            correlation_id=correlation_id,
            settled_at=settled_at,
        )

        if target_status == TransactionStatus.SETTLED:
            outbox_repo = DrunixOutboxRepository(self.session)
            settled_iso = (settled_at or datetime.now(UTC)).isoformat()
            outbox_payload = {
                "transaction_id": str(updated_tx.id),
                "institution_id": str(updated_tx.origin_institution_id),
                "amount": str(updated_tx.amount),
                "currency": updated_tx.currency,
                "settled_at": settled_iso,
                "receipt_reference": None,
            }
            settle_commitment = hashlib.sha256(
                f"{updated_tx.id}:SETTLED:{updated_tx.amount}:{settled_iso}".encode()
            ).hexdigest()
            await outbox_repo.create_event(
                institution_id=updated_tx.origin_institution_id,
                event_type=DrunixEventType.SETTLEMENT_RECORD,
                aggregate_type="TRANSACTION",
                aggregate_id=updated_tx.id,
                idempotency_key=f"drunix:settlement:{updated_tx.id}",
                commitment_hash=settle_commitment,
                payload=outbox_payload,
                correlation_id=correlation_id,
                causation_id=str(updated_tx.id),
                event_category="DRUNIX_DELIVERY",
                ordering_key=f"tx:{updated_tx.id}",
                sequence_number=3,
            )

        await self.audit_repo.create_log(
            AuditLogCreate(
                event_type="TRANSACTION_STATUS_UPDATED",
                severity="INFO",
                actor=actor,
                description=f"Transaction {updated_tx.id} transitioned to {target_status.value}",
                correlation_id=correlation_id,
                details={
                    "transaction_id": str(updated_tx.id),
                    "action": data.action.value,
                    "previous_status": current_status.value,
                    "new_status": target_status.value,
                    "reason": data.reason,
                },
            )
        )

        # Reload with history
        loaded_tx = await self.transaction_repo.get_with_history(updated_tx.id)
        return TransactionResponse.model_validate(loaded_tx)
