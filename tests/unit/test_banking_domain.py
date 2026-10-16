"""Unit tests for banking domain models, transitions, and decimal safety."""

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from sentinel_chain_drive.db.models.account import (
    VALID_ACCOUNT_TRANSITIONS,
    AccountStatus,
    AccountType,
)
from sentinel_chain_drive.db.models.institution import (
    VALID_INSTITUTION_TRANSITIONS,
    InstitutionStatus,
)
from sentinel_chain_drive.db.models.transaction import (
    VALID_TRANSACTION_TRANSITIONS,
    TransactionStatus,
    TransactionType,
)
from sentinel_chain_drive.schemas.account import AccountCreate
from sentinel_chain_drive.schemas.institution import InstitutionCreate
from sentinel_chain_drive.schemas.transaction import TransactionSubmitRequest


def test_institution_transitions_validity() -> None:
    """Verify valid and invalid institution transitions."""
    # Active -> Suspended is allowed
    assert InstitutionStatus.SUSPENDED in VALID_INSTITUTION_TRANSITIONS[InstitutionStatus.ACTIVE]
    # Active -> Inactive is allowed
    assert InstitutionStatus.INACTIVE in VALID_INSTITUTION_TRANSITIONS[InstitutionStatus.ACTIVE]
    # Suspended -> Active is allowed
    assert InstitutionStatus.ACTIVE in VALID_INSTITUTION_TRANSITIONS[InstitutionStatus.SUSPENDED]
    # Inactive is terminal: no transitions allowed
    assert len(VALID_INSTITUTION_TRANSITIONS[InstitutionStatus.INACTIVE]) == 0


def test_account_transitions_validity() -> None:
    """Verify valid and invalid account transitions."""
    # Active -> Frozen and Closed are allowed
    assert AccountStatus.FROZEN in VALID_ACCOUNT_TRANSITIONS[AccountStatus.ACTIVE]
    assert AccountStatus.CLOSED in VALID_ACCOUNT_TRANSITIONS[AccountStatus.ACTIVE]
    # Frozen -> Active is allowed
    assert AccountStatus.ACTIVE in VALID_ACCOUNT_TRANSITIONS[AccountStatus.FROZEN]
    # Closed is terminal
    assert len(VALID_ACCOUNT_TRANSITIONS[AccountStatus.CLOSED]) == 0


def test_transaction_transitions_validity() -> None:
    """Verify valid and invalid transaction state machine transitions."""
    # SUBMITTED -> PENDING_AUTHORIZATION, REJECTED, CANCELLED
    assert (
        TransactionStatus.PENDING_AUTHORIZATION
        in VALID_TRANSACTION_TRANSITIONS[TransactionStatus.SUBMITTED]
    )
    assert TransactionStatus.REJECTED in VALID_TRANSACTION_TRANSITIONS[TransactionStatus.SUBMITTED]
    # PENDING_AUTHORIZATION -> HELD, SETTLED, REJECTED, CANCELLED
    assert (
        TransactionStatus.HELD
        in VALID_TRANSACTION_TRANSITIONS[TransactionStatus.PENDING_AUTHORIZATION]
    )
    assert (
        TransactionStatus.SETTLED
        in VALID_TRANSACTION_TRANSITIONS[TransactionStatus.PENDING_AUTHORIZATION]
    )
    assert (
        TransactionStatus.REJECTED
        in VALID_TRANSACTION_TRANSITIONS[TransactionStatus.PENDING_AUTHORIZATION]
    )
    # HELD -> PENDING_AUTHORIZATION, SETTLED, REJECTED, CANCELLED
    assert TransactionStatus.SETTLED in VALID_TRANSACTION_TRANSITIONS[TransactionStatus.HELD]
    # SETTLED is terminal
    assert len(VALID_TRANSACTION_TRANSITIONS[TransactionStatus.SETTLED]) == 0
    # REJECTED is terminal
    assert len(VALID_TRANSACTION_TRANSITIONS[TransactionStatus.REJECTED]) == 0


def test_transaction_schema_decimal_and_amount_constraints() -> None:
    """Ensure monetary amounts strictly require positive Decimal values within limit."""
    inst_id = uuid.uuid4()
    acct_id = uuid.uuid4()

    # Valid request with string decimal representation
    req = TransactionSubmitRequest(
        idempotency_key="idemp-unit-test-0001",
        origin_institution_id=inst_id,
        origin_account_id=acct_id,
        destination_institution_id=inst_id,
        destination_account_id=acct_id,
        amount=Decimal("150.25"),
        currency="USD",
        transaction_type=TransactionType.TRANSFER,
    )
    assert req.amount == Decimal("150.25")
    assert isinstance(req.amount, Decimal)

    # Negative amount rejected
    with pytest.raises(ValidationError):
        TransactionSubmitRequest(
            idempotency_key="idemp-unit-test-0002",
            origin_institution_id=inst_id,
            origin_account_id=acct_id,
            destination_institution_id=inst_id,
            destination_account_id=acct_id,
            amount=Decimal("-10.00"),
            currency="USD",
            transaction_type=TransactionType.TRANSFER,
        )

    # Zero amount rejected
    with pytest.raises(ValidationError):
        TransactionSubmitRequest(
            idempotency_key="idemp-unit-test-0003",
            origin_institution_id=inst_id,
            origin_account_id=acct_id,
            destination_institution_id=inst_id,
            destination_account_id=acct_id,
            amount=Decimal("0.00"),
            currency="USD",
            transaction_type=TransactionType.TRANSFER,
        )

    # Amount exceeding max limit (100,000,000) rejected
    with pytest.raises(ValidationError):
        TransactionSubmitRequest(
            idempotency_key="idemp-unit-test-0004",
            origin_institution_id=inst_id,
            origin_account_id=acct_id,
            destination_institution_id=inst_id,
            destination_account_id=acct_id,
            amount=Decimal("100000000.01"),
            currency="USD",
            transaction_type=TransactionType.TRANSFER,
        )


def test_account_creation_validation() -> None:
    """Verify account schema validation for initial balances and identifiers."""
    inst_id = uuid.uuid4()

    # Valid
    acct = AccountCreate(
        institution_id=inst_id,
        account_number="SYNTH-ACCT-1234",
        account_type=AccountType.CHECKING,
        currency="usd",  # normalized to uppercase
        initial_balance=Decimal("1000.50"),
    )
    assert acct.currency == "USD"
    assert acct.initial_balance == Decimal("1000.50")

    # Negative balance rejected
    with pytest.raises(ValidationError):
        AccountCreate(
            institution_id=inst_id,
            account_number="SYNTH-ACCT-1234",
            account_type=AccountType.CHECKING,
            currency="USD",
            initial_balance=Decimal("-50.00"),
        )


def test_institution_creation_validation() -> None:
    """Verify institution schema validation."""
    inst = InstitutionCreate(
        institution_code="APEX_BANK",
        name="Apex Bank",
        routing_identifier="11100001",
    )
    assert inst.institution_code == "APEX_BANK"

    with pytest.raises(ValidationError):
        InstitutionCreate(
            institution_code="INVALID CODE WITH SPACES!",
            name="Bank",
            routing_identifier="11100001",
        )
