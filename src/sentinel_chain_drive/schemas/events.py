"""Pydantic schemas and contracts for Phase 8 Event Processing and System Coordination.

Enforces strict payload validation, data minimization (prohibiting raw PANs, credentials,
and private keys), backward-compatible schema versioning, and clear categorization between:
1. Internal Domain Events
2. Fraud-Intelligence Events
3. DRUNIX Delivery Events
"""

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EventCategory(enum.StrEnum):
    """Explicit high-level categorization of events in Sentinel Chain Drive."""

    DOMAIN = "DOMAIN"
    FRAUD_INTELLIGENCE = "FRAUD_INTELLIGENCE"
    DRUNIX_DELIVERY = "DRUNIX_DELIVERY"


class StandardEventType(enum.StrEnum):
    """Recognized event types across internal, fraud, and ledger domains."""

    # Internal Domain Events
    TRANSACTION_SUBMITTED = "TRANSACTION_SUBMITTED"
    TRANSACTION_AUTHORIZED = "TRANSACTION_AUTHORIZED"
    TRANSACTION_SETTLED = "TRANSACTION_SETTLED"
    TRANSACTION_HELD = "TRANSACTION_HELD"
    TRANSACTION_DECLINED = "TRANSACTION_DECLINED"

    # Fraud-Intelligence Events
    FRAUD_ALERT_RAISED = "FRAUD_ALERT_RAISED"
    SHARED_INDICATOR_PUBLISHED = "SHARED_INDICATOR_PUBLISHED"

    # DRUNIX Delivery Events
    AUTH_ATTESTATION = "AUTH_ATTESTATION"
    FRAUD_INDICATOR = "FRAUD_INDICATOR"
    SETTLEMENT_RECORD = "SETTLEMENT_RECORD"


SUPPORTED_SCHEMA_VERSIONS = {"v1.0"}

PROHIBITED_PAYLOAD_KEYS = {
    "raw_pan",
    "pan",
    "card_number",
    "account_number_plain",
    "plain_account_number",
    "private_key",
    "access_token",
    "secret",
    "password",
    "cvv",
    "pin",
}


class UnsupportedSchemaVersionError(ValueError):
    """Raised when an event payload references an unrecognized schema version."""

    def __init__(self, version: str) -> None:
        super().__init__(
            f"Unsupported event schema version: '{version}'. "
            f"Supported versions: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
        )
        self.version = version


class SensitivePayloadDataError(ValueError):
    """Raised when an event payload contains forbidden sensitive fields."""

    def __init__(self, forbidden_keys: list[str]) -> None:
        super().__init__(f"Payload contains prohibited sensitive fields: {sorted(forbidden_keys)}")
        self.forbidden_keys = forbidden_keys


def sanitize_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Sanitize payload dictionary by checking and redacting sensitive data.

    Raises SensitivePayloadDataError if prohibited field names are found.
    """
    forbidden_found: list[str] = []
    for k in payload:
        k_lower = k.lower().replace("-", "_")
        if k_lower in PROHIBITED_PAYLOAD_KEYS or any(
            p in k_lower for p in ["private_key", "password", "access_token", "raw_pan"]
        ):
            forbidden_found.append(k)

    if forbidden_found:
        raise SensitivePayloadDataError(forbidden_found)

    return payload


# ---------------------------------------------------------------------------
# Specific Payload Schemas (v1.0)
# ---------------------------------------------------------------------------


class BaseEventPayload(BaseModel):
    """Base model for validated, sanitized event payloads."""

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def check_prohibited_fields(cls, values: Any) -> Any:
        if isinstance(values, dict):
            sanitize_event_payload(values)
        return values


class TransactionSubmittedPayload(BaseEventPayload):
    """Payload contract for TRANSACTION_SUBMITTED domain events."""

    transaction_id: str | None = Field(default=None, description="Internal transaction identifier")
    idempotency_key: str | None = Field(default=None, description="Submission idempotency key")
    origin_institution_id: str | None = Field(
        default=None, description="Originating institution ID"
    )
    destination_institution_id: str | None = Field(
        default=None, description="Destination institution ID"
    )
    amount: str | None = Field(default=None, description="Monetary amount in decimal string format")
    currency: str | None = Field(default=None, description="ISO currency code")
    purpose_code: str | None = Field(default=None, description="Business purpose code")
    submitted_at: str | None = Field(default=None, description="ISO timestamp of submission")


class TransactionAuthorizedPayload(BaseEventPayload):
    """Payload contract for TRANSACTION_AUTHORIZED / AUTH_ATTESTATION events."""

    decision: str | None = Field(default="ALLOW", description="Outcome decision string, e.g. ALLOW")
    decision_id: str | None = Field(default=None, description="Policy evaluation record ID")
    agent_id: str | None = Field(default=None, description="Authorized AI agent ID")
    institution_id: str | None = Field(default=None, description="Sponsoring institution ID")
    transaction_intent_hash: str | None = Field(
        default=None, description="Canonical SHA-256 intent hash"
    )
    amount: str | None = Field(default=None, description="Authorized monetary amount")
    currency: str | None = Field(default=None, description="ISO currency code")
    evaluated_at: str | None = Field(default=None, description="ISO timestamp of evaluation")
    challenge_id: str | None = Field(default=None, description="Optional step-up challenge ID")
    approver_id: str | None = Field(default=None, description="Optional supervisor approver ID")
    hold_id: str | None = Field(default=None, description="Optional resolved hold ID")
    resolved_by: str | None = Field(default=None, description="Optional hold resolver ID")


class TransactionSettledPayload(BaseEventPayload):
    """Payload contract for TRANSACTION_SETTLED / SETTLEMENT_RECORD events."""

    transaction_id: str | None = Field(default=None, description="Settled transaction ID")
    institution_id: str | None = Field(default=None, description="Settling institution ID")
    amount: str | None = Field(default=None, description="Settled monetary amount")
    currency: str | None = Field(default=None, description="ISO currency code")
    settled_at: str | None = Field(default=None, description="ISO timestamp of settlement")
    receipt_reference: str | None = Field(default=None, description="Optional bank core receipt")


class FraudAlertPayload(BaseEventPayload):
    """Payload contract for FRAUD_ALERT_RAISED events."""

    alert_id: str | None = Field(default=None, description="Generated fraud alert ID")
    alert_code: str | None = Field(default=None, description="Specific anomaly code")
    detector_type: str | None = Field(default=None, description="Detector type, e.g. FAN_IN")
    severity: str | None = Field(
        default=None, description="Severity tier: LOW, MEDIUM, HIGH, CRITICAL"
    )
    risk_score: int | None = Field(default=None, description="Normalized risk score 0-100")
    primary_institution_id: str | None = Field(default=None, description="Primary institution ID")
    primary_account_id: str | None = Field(default=None, description="Primary account identifier")
    currency: str | None = Field(default=None, description="Monetary currency of inspected flow")
    detection_rule_version: str | None = Field(default=None, description="Detector rule version")
    evidence_summary: dict[str, Any] | None = Field(
        default=None, description="Non-sensitive topological summary"
    )


class SharedIndicatorPayload(BaseEventPayload):
    """Payload contract for SHARED_INDICATOR_PUBLISHED / FRAUD_INDICATOR events."""

    indicator_id: str | None = Field(default=None, description="Shared indicator identifier")
    indicator_code: str | None = Field(default=None, description="Specific indicator code")
    pseudonymous_mesh_id: str | None = Field(default=None, description="HMAC-SHA256 pseudonym")
    indicator_type: str | None = Field(default=None, description="Categorical indicator type")
    severity: str | None = Field(default=None, description="Severity rating")
    originating_institution_id: str | None = Field(
        default=None, description="Originating institution ID"
    )


# Registry mapping event type and schema version to payload models
PAYLOAD_MODEL_REGISTRY: dict[tuple[str, str], type[BaseEventPayload]] = {
    (StandardEventType.TRANSACTION_SUBMITTED.value, "v1.0"): TransactionSubmittedPayload,
    (StandardEventType.TRANSACTION_AUTHORIZED.value, "v1.0"): TransactionAuthorizedPayload,
    (StandardEventType.TRANSACTION_SETTLED.value, "v1.0"): TransactionSettledPayload,
    (StandardEventType.AUTH_ATTESTATION.value, "v1.0"): TransactionAuthorizedPayload,
    (StandardEventType.SETTLEMENT_RECORD.value, "v1.0"): TransactionSettledPayload,
    (StandardEventType.FRAUD_ALERT_RAISED.value, "v1.0"): FraudAlertPayload,
    (StandardEventType.SHARED_INDICATOR_PUBLISHED.value, "v1.0"): SharedIndicatorPayload,
    (StandardEventType.FRAUD_INDICATOR.value, "v1.0"): SharedIndicatorPayload,
}


def validate_event_payload(
    event_type: str,
    schema_version: str,
    payload: dict[str, Any],
) -> BaseEventPayload:
    """Validate that an event payload satisfies its contract for the given type and version.

    Raises:
        UnsupportedSchemaVersionError: If schema version is unrecognized.
        SensitivePayloadDataError: If prohibited sensitive fields are present.
        pydantic.ValidationError: If payload fails schema fields/types validation.
    """
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise UnsupportedSchemaVersionError(schema_version)

    # Check sensitive data keys first
    sanitize_event_payload(payload)

    model_cls = PAYLOAD_MODEL_REGISTRY.get((event_type, schema_version))
    if model_cls is not None:
        return model_cls.model_validate(payload)

    # Generic validated payload if no specific model registered for custom event
    return BaseEventPayload.model_validate(payload)


# ---------------------------------------------------------------------------
# Event Envelope Contract
# ---------------------------------------------------------------------------


class EventEnvelope(BaseModel):
    """Canonical event envelope contract for all asynchronous events."""

    model_config = ConfigDict(from_attributes=True)

    event_id: uuid.UUID = Field(description="Globally unique event identifier")
    event_type: str = Field(description="Explicit event type string")
    event_category: EventCategory = Field(
        description="DOMAIN, FRAUD_INTELLIGENCE, or DRUNIX_DELIVERY"
    )
    schema_version: str = Field(default="v1.0", description="Schema version identifier")
    institution_id: uuid.UUID = Field(description="Institution scope boundary")
    aggregate_type: str = Field(description="Aggregate entity category, e.g. TRANSACTION")
    aggregate_id: uuid.UUID = Field(description="Aggregate entity primary key")
    ordering_key: str | None = Field(
        default=None,
        description="Optional ordering partition key, e.g. tx:{transaction_id}",
    )
    sequence_number: int | None = Field(
        default=None,
        description="Monotonic sequence number within the ordering partition",
    )
    correlation_id: str | None = Field(
        default=None,
        description="End-to-end tracing correlation identifier",
    )
    causation_id: str | None = Field(
        default=None,
        description="Preceding causation event or transaction identifier",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC creation timestamp",
    )
    payload: dict[str, Any] = Field(description="Sanitized event payload")

    @field_validator("schema_version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        if v not in SUPPORTED_SCHEMA_VERSIONS:
            raise UnsupportedSchemaVersionError(v)
        return v

    @field_validator("payload")
    @classmethod
    def validate_payload_data(cls, v: dict[str, Any]) -> dict[str, Any]:
        return sanitize_event_payload(v)
