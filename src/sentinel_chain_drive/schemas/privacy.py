"""Pydantic schemas for Privacy Gateway and Cross-Institution Intelligence."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sentinel_chain_drive.db.models.privacy_audit import PrivacyAction, PrivacyOutcome
from sentinel_chain_drive.db.models.shared_indicator import (
    IndicatorSeverity,
    IndicatorStatus,
    IndicatorType,
)

# Fields strictly forbidden from leaving institutional boundaries in shared intelligence
PROHIBITED_DISCLOSURE_FIELDS: frozenset[str] = frozenset({
    "raw_account_number",
    "account_number",
    "customer_name",
    "customer_id",
    "owner_contact",
    "private_key",
    "credentials",
    "password",
    "secret",
    "ssn",
    "tax_id",
    "national_id",
    "email",
    "phone",
    "raw_transactions",
    "transaction_ids",
    "raw_transaction_ids",
    "balance",
    "initial_balance",
})

# Fields permitted within evidence_summary
ALLOWED_EVIDENCE_FIELDS: frozenset[str] = frozenset({
    "pattern_type",
    "window_seconds",
    "burst_count",
    "source_count_tier",
    "destination_count_tier",
    "anonymized_volume_tier",
    "mulechain_rule_version",
    "scoring_model_version",
    "flow_hop_count",
    "ratio_range",
    "pattern_description",
    "detector",
})

# Fields permitted within provenance metadata
ALLOWED_PROVENANCE_FIELDS: frozenset[str] = frozenset({
    "source_type",
    "source",
    "detector_type",
    "scoring_model_version",
    "detection_rule_version",
    "origin_timestamp",
    "algorithm",
    "submission_timestamp",
    "submitter_actor",
    "originating_institution_id",
    "epoch_id",
})


def validate_evidence_against_disclosure_allowlist(
    evidence: dict[str, Any],
    check_allowlist: bool = True,
) -> dict[str, Any]:
    """Validate that evidence dict contains NO prohibited fields and strictly safe fields."""
    if not isinstance(evidence, dict):
        raise ValueError("Evidence summary must be a dictionary.")

    for k, v in evidence.items():
        k_lower = k.lower().strip()
        sensitive_substrings = [
            "account", "customer", "secret", "private_key", "password", "transaction_id", "raw_tx"
        ]
        if k_lower in PROHIBITED_DISCLOSURE_FIELDS or any(
            p in k_lower for p in sensitive_substrings
        ):
            raise ValueError(
                f"Prohibited disclosure field '{k}' is forbidden in cross-institution intelligence."
            )

        if check_allowlist and k_lower not in ALLOWED_EVIDENCE_FIELDS:
            raise ValueError(
                f"Unapproved disclosure evidence field '{k}' not in allowlist."
            )

        # Check nested structures
        if isinstance(v, dict):
            validate_evidence_against_disclosure_allowlist(v, check_allowlist=check_allowlist)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    validate_evidence_against_disclosure_allowlist(
                        item, check_allowlist=check_allowlist
                    )
                elif isinstance(item, str):
                    item_lower = item.lower().strip()
                    sensitive_terms = [
                        "account", "customer", "secret", "private_key", "password"
                    ]
                    if any(p in item_lower for p in sensitive_terms):
                        raise ValueError(f"Prohibited sensitive content in evidence list: '{item}'")

    return evidence


def validate_provenance_against_allowlist(
    provenance: dict[str, Any],
) -> dict[str, Any]:
    """Validate that provenance contains strictly approved metadata and NO prohibited fields."""
    if not isinstance(provenance, dict):
        raise ValueError("Provenance must be a dictionary.")

    for k, v in provenance.items():
        k_lower = k.lower().strip()
        if k_lower in PROHIBITED_DISCLOSURE_FIELDS or any(
            p in k_lower for p in ["account", "customer", "secret", "private_key", "password"]
        ):
            raise ValueError(
                f"Prohibited disclosure field '{k}' is forbidden in provenance metadata."
            )

        if k_lower not in ALLOWED_PROVENANCE_FIELDS:
            raise ValueError(
                f"Unapproved provenance field '{k}' not in allowlist. "
                f"Allowed fields: {sorted(ALLOWED_PROVENANCE_FIELDS)}"
            )

        if isinstance(v, dict):
            validate_provenance_against_allowlist(v)
        elif isinstance(v, str):
            v_lower = v.lower().strip()
            if any(p in v_lower for p in ["private_key", "secret_key", "password"]):
                raise ValueError(f"Prohibited credential string in provenance field '{k}'.")

    return provenance



class SharedIndicatorPublishRequest(BaseModel):
    """Request payload to directly publish a pre-sanitized cross-institution indicator."""

    pseudonymous_mesh_id: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-fA-F]{64}$",
        description="64-character lowercase hex HMAC-SHA256 pseudonym (MeshID)",
    )
    indicator_type: IndicatorType = Field(
        description="Topological indicator pattern classification",
    )
    severity: IndicatorSeverity = Field(
        default=IndicatorSeverity.MEDIUM,
        description="Threat severity assessment",
    )
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence probability metric between 0.0 and 1.0",
    )
    pattern_category: str = Field(
        min_length=3,
        max_length=64,
        description="Typology classification category e.g. TOPOLOGICAL_FAN_IN",
    )
    evidence_summary: dict[str, Any] = Field(
        default_factory=dict,
        description="Sanitized, non-sensitive topological attributes",
    )
    provenance: dict[str, Any] = Field(
        default_factory=dict,
        description="Detection source metadata, rule versions, and timestamps",
    )
    target_institution_id: uuid.UUID | None = Field(
        default=None,
        description="Optional specific recipient institution; null designates network broadcast",
    )
    validity_hours: int = Field(
        default=72,
        ge=1,
        le=720,
        description="Validity window in hours before indicator expires (1 hour to 30 days)",
    )
    sharing_policy_version: str = Field(
        default="v1.0",
        max_length=32,
        description="Sharing disclosure policy version",
    )

    @field_validator("evidence_summary")
    @classmethod
    def check_evidence(cls, v: dict[str, Any]) -> dict[str, Any]:
        return validate_evidence_against_disclosure_allowlist(v)

    @field_validator("provenance")
    @classmethod
    def check_provenance(cls, v: dict[str, Any]) -> dict[str, Any]:
        return validate_provenance_against_allowlist(v)


class SharedIndicatorPublishFromAlertRequest(BaseModel):
    """Convenience payload to publish a sanitized indicator directly from a MuleChain alert."""

    alert_id: uuid.UUID = Field(
        description="Identifier of the locally stored MuleChain FraudAlert",
    )
    account_number: str = Field(
        min_length=3,
        max_length=64,
        description="Account number used in-process to compute MeshID, never stored in registry",
    )
    target_institution_id: uuid.UUID | None = Field(
        default=None,
        description="Optional specific recipient institution; null designates network broadcast",
    )
    validity_hours: int = Field(
        default=72,
        ge=1,
        le=720,
        description="Validity window in hours before indicator expires",
    )


class MeshIDQueryRequest(BaseModel):
    """Scoped query request to check if an account pseudonym has active fraud indicators."""

    pseudonymous_mesh_id: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-fA-F]{64}$",
        description="Subject MeshID to query",
    )
    purpose: str = Field(
        min_length=3,
        max_length=64,
        description="Operational purpose justifying query (e.g. PAYMENT_AUTHORIZATION)",
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Bounded pagination limit",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Pagination offset",
    )


class IndicatorRevocationRequest(BaseModel):
    """Request payload to revoke or withdraw a published indicator."""

    reason: str = Field(
        min_length=3,
        max_length=256,
        description="Operational justification for revoking or withdrawing the indicator",
    )


class SharedIndicatorResponse(BaseModel):
    """Public representation of a cross-institution shared intelligence indicator."""

    id: uuid.UUID
    indicator_code: str
    schema_version: str
    pseudonymous_mesh_id: str
    originating_institution_id: uuid.UUID
    target_institution_id: uuid.UUID | None
    indicator_type: IndicatorType
    severity: IndicatorSeverity
    confidence_score: float
    pattern_category: str
    evidence_summary: dict[str, Any]
    provenance: dict[str, Any]
    sharing_policy_version: str
    status: IndicatorStatus
    revocation_reason: str | None
    revoked_at: datetime | None
    expires_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SharedIndicatorListResponse(BaseModel):
    """Paginated list of shared intelligence indicators."""

    items: list[SharedIndicatorResponse]
    total: int
    limit: int
    offset: int


class PrivacyAuditEventResponse(BaseModel):
    """Individual privacy audit log record."""

    id: uuid.UUID
    institution_id: uuid.UUID
    actor: str
    action: PrivacyAction
    outcome: PrivacyOutcome
    pseudonymous_mesh_id: str | None
    indicator_id: uuid.UUID | None
    details: dict[str, Any]
    correlation_id: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PrivacyAuditSummaryResponse(BaseModel):
    """Audit summary for an institution's cross-institution intelligence interactions."""

    institution_id: uuid.UUID
    published_count: int
    queried_count: int
    revoked_count: int
    recent_events: list[PrivacyAuditEventResponse]
