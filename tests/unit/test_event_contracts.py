"""Unit test suite for Phase 8 Event Contracts, Schema Validation, and Payload Minimization."""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from sentinel_chain_drive.schemas.events import (
    EventCategory,
    EventEnvelope,
    FraudAlertPayload,
    SensitivePayloadDataError,
    SharedIndicatorPayload,
    StandardEventType,
    TransactionAuthorizedPayload,
    TransactionSettledPayload,
    TransactionSubmittedPayload,
    UnsupportedSchemaVersionError,
    sanitize_event_payload,
    validate_event_payload,
)


def test_transaction_submitted_payload_valid() -> None:
    """Verify valid TransactionSubmittedPayload creation."""
    payload = TransactionSubmittedPayload(
        transaction_id=str(uuid.uuid4()),
        idempotency_key="idemp_sub_001",
        origin_institution_id=str(uuid.uuid4()),
        destination_institution_id=str(uuid.uuid4()),
        amount="150.00",
        currency="USD",
        purpose_code="COMMERCIAL_SUPPLIER_PAYMENT",
        submitted_at=datetime.now(UTC).isoformat(),
    )
    assert payload.amount == "150.00"
    assert payload.currency == "USD"
    assert payload.idempotency_key == "idemp_sub_001"


def test_transaction_authorized_payload_valid() -> None:
    """Verify valid TransactionAuthorizedPayload creation."""
    payload = TransactionAuthorizedPayload(
        decision_id=str(uuid.uuid4()),
        agent_id=str(uuid.uuid4()),
        institution_id=str(uuid.uuid4()),
        decision="ALLOW",
        transaction_intent_hash="a" * 64,
        amount="250.00",
        currency="USD",
        evaluated_at=datetime.now(UTC).isoformat(),
    )
    assert payload.decision == "ALLOW"
    assert payload.amount == "250.00"
    assert payload.challenge_id is None


def test_transaction_settled_payload_valid() -> None:
    """Verify valid TransactionSettledPayload creation."""
    payload = TransactionSettledPayload(
        transaction_id=str(uuid.uuid4()),
        institution_id=str(uuid.uuid4()),
        amount="500.00",
        currency="USD",
        settled_at=datetime.now(UTC).isoformat(),
        receipt_reference="SETTLE-REF-999",
    )
    assert payload.receipt_reference == "SETTLE-REF-999"


def test_fraud_alert_payload_valid() -> None:
    """Verify valid FraudAlertPayload creation."""
    payload = FraudAlertPayload(
        alert_id=str(uuid.uuid4()),
        alert_code="MULE_FAN_IN_001",
        detector_type="FAN_IN",
        severity="HIGH",
        risk_score=85,
        primary_institution_id=str(uuid.uuid4()),
        primary_account_id="ACC_12345",
        currency="USD",
        detection_rule_version="1.0.0",
        evidence_summary={"fan_in_ratio": 5.2},
    )
    assert payload.severity == "HIGH"
    assert payload.risk_score == 85
    assert payload.detector_type == "FAN_IN"


def test_shared_indicator_payload_valid() -> None:
    """Verify valid SharedIndicatorPayload creation."""
    payload = SharedIndicatorPayload(
        indicator_id=str(uuid.uuid4()),
        indicator_code="IND_MULE_BURST",
        pseudonymous_mesh_id="mesh_pseudo_" + "a" * 32,
        indicator_type="RAPID_MOVEMENT_BURST",
        severity="MEDIUM",
        originating_institution_id=str(uuid.uuid4()),
    )
    assert payload.indicator_code == "IND_MULE_BURST"
    assert payload.severity == "MEDIUM"


def test_sensitive_payload_attributes_prohibited() -> None:
    """Verify that sensitive keys such as raw_pan, password, private_key are strictly rejected."""
    with pytest.raises(SensitivePayloadDataError) as exc_info:
        sanitize_event_payload({"raw_pan": "4111111111111111"})
    assert "raw_pan" in str(exc_info.value)

    with pytest.raises(SensitivePayloadDataError) as exc_info:
        sanitize_event_payload({"password": "secretpassword"})
    assert "password" in str(exc_info.value)

    with pytest.raises(SensitivePayloadDataError) as exc_info:
        sanitize_event_payload({"private_key": "0xabc123"})
    assert "private_key" in str(exc_info.value)

    # In Pydantic model validation
    with pytest.raises(ValidationError) as exc_pydantic:
        TransactionSubmittedPayload.model_validate(
            {
                "transaction_id": str(uuid.uuid4()),
                "idempotency_key": "idemp_bad_001",
                "origin_institution_id": str(uuid.uuid4()),
                "destination_institution_id": str(uuid.uuid4()),
                "amount": "200.00",
                "currency": "USD",
                "purpose_code": "GENERAL",
                "submitted_at": datetime.now(UTC).isoformat(),
                "raw_pan": "4111111111111111",  # Prohibited sensitive attribute
            }
        )
    assert "prohibited sensitive fields" in str(exc_pydantic.value)


def test_unsupported_schema_version_rejected() -> None:
    """Verify that unsupported schema versions are rejected by EventEnvelope."""
    with pytest.raises(ValidationError) as exc_info:
        EventEnvelope(
            event_id=uuid.uuid4(),
            event_type=StandardEventType.TRANSACTION_SUBMITTED.value,
            event_category=EventCategory.DOMAIN,
            schema_version="v2.0",  # Unsupported version
            institution_id=uuid.uuid4(),
            aggregate_type="TRANSACTION",
            aggregate_id=uuid.uuid4(),
            created_at=datetime.now(UTC),
            payload={
                "transaction_id": str(uuid.uuid4()),
                "idempotency_key": "idemp_version_test",
                "origin_institution_id": str(uuid.uuid4()),
                "destination_institution_id": str(uuid.uuid4()),
                "amount": "100.00",
                "currency": "USD",
                "purpose_code": "COMMERCIAL",
                "submitted_at": datetime.now(UTC).isoformat(),
            },
        )
    assert "Unsupported event schema version" in str(exc_info.value)

    with pytest.raises(UnsupportedSchemaVersionError):
        validate_event_payload(
            event_type=StandardEventType.TRANSACTION_SUBMITTED.value,
            schema_version="v99.0",
            payload={},
        )


def test_event_envelope_serialization_and_validation() -> None:
    """Verify valid EventEnvelope serialization and deserialization."""
    event_id = uuid.uuid4()
    inst_id = uuid.uuid4()
    tx_id = uuid.uuid4()
    now = datetime.now(UTC)

    envelope = EventEnvelope(
        event_id=event_id,
        event_type=StandardEventType.TRANSACTION_SUBMITTED.value,
        event_category=EventCategory.DOMAIN,
        schema_version="v1.0",
        institution_id=inst_id,
        aggregate_type="TRANSACTION",
        aggregate_id=tx_id,
        created_at=now,
        correlation_id="corr-12345",
        causation_id="cause-67890",
        ordering_key=f"tx:{tx_id}",
        sequence_number=1,
        payload={
            "transaction_id": str(tx_id),
            "idempotency_key": "idemp_version_test",
            "origin_institution_id": str(inst_id),
            "destination_institution_id": str(uuid.uuid4()),
            "amount": "100.00",
            "currency": "USD",
            "purpose_code": "PAYMENT",
            "submitted_at": now.isoformat(),
        },
    )

    data = envelope.model_dump()
    assert data["event_id"] == event_id
    assert data["event_type"] == StandardEventType.TRANSACTION_SUBMITTED.value
    assert data["ordering_key"] == f"tx:{tx_id}"
    assert data["sequence_number"] == 1
    assert data["schema_version"] == "v1.0"
