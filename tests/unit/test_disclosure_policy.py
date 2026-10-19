"""Unit tests for DataDisclosurePolicy and field-level disclosure allowlists."""

import uuid
from datetime import UTC, datetime

import pytest

from sentinel_chain_drive.db.models.alert import (
    AlertSeverity,
    AlertStatus,
    DetectorType,
    FraudAlert,
)
from sentinel_chain_drive.schemas.privacy import (
    ALLOWED_EVIDENCE_FIELDS,
    PROHIBITED_DISCLOSURE_FIELDS,
    validate_evidence_against_disclosure_allowlist,
)
from sentinel_chain_drive.services.privacy_gateway.disclosure import DataDisclosurePolicy


def test_prohibited_field_rejection_direct_identifiers() -> None:
    """Prohibited sensitive fields must be rejected immediately with ValueError."""
    for prohibited_field in PROHIBITED_DISCLOSURE_FIELDS:
        payload = {
            prohibited_field: "sensitive_value_12345",
            "pattern_type": "FAN_IN",
            "window_seconds": 3600,
        }
        with pytest.raises(ValueError, match="Prohibited disclosure field"):
            validate_evidence_against_disclosure_allowlist(payload)


def test_nested_prohibited_field_rejection() -> None:
    """Nested occurrences of prohibited sensitive fields must also be detected and rejected."""
    nested_payload = {
        "pattern_type": "FAN_IN",
        "nested_details": {
            "account_number": "ACC-SECRET-9999",
        },
    }
    with pytest.raises(ValueError, match="Prohibited disclosure field"):
        validate_evidence_against_disclosure_allowlist(nested_payload, check_allowlist=False)




def test_unallowlisted_field_rejection() -> None:
    """Fields not present in the strict allowlist must be rejected."""
    payload = {
        "pattern_type": "FAN_IN",
        "arbitrary_unapproved_field": "some_data",
    }
    with pytest.raises(ValueError, match="Unapproved disclosure evidence field"):
        validate_evidence_against_disclosure_allowlist(payload)


def test_classify_volume_tier_coarsening() -> None:
    """Monetary amounts are coarsened into privacy-preserving volume tiers."""
    assert DataDisclosurePolicy.classify_volume_tier(500) == "TIER_MICRO_UNDER_1K"
    assert DataDisclosurePolicy.classify_volume_tier("999.99") == "TIER_MICRO_UNDER_1K"
    assert DataDisclosurePolicy.classify_volume_tier(1000) == "TIER_LOW_1K_TO_10K"
    assert DataDisclosurePolicy.classify_volume_tier("9999.00") == "TIER_LOW_1K_TO_10K"
    assert DataDisclosurePolicy.classify_volume_tier(25000) == "TIER_MEDIUM_10K_TO_100K"
    assert DataDisclosurePolicy.classify_volume_tier(150000) == "TIER_HIGH_OVER_100K"
    assert DataDisclosurePolicy.classify_volume_tier("invalid_amount") == "TIER_UNKNOWN"


def test_sanitize_mulechain_alert_strips_pii_and_accounts() -> None:
    """Sanitizing a MuleChain alert produces a clean evidence summary conforming to allowlist."""
    inst_id = uuid.uuid4()
    acct_id = uuid.uuid4()
    alert_id = uuid.uuid4()

    alert = FraudAlert(
        id=alert_id,
        alert_code="ALT-20261019-TEST",
        detector_type=DetectorType.FAN_IN,
        severity=AlertSeverity.HIGH,
        status=AlertStatus.NEW,
        risk_score=85,
        primary_institution_id=inst_id,
        primary_account_id=acct_id,
        currency="USD",
        analysis_window_start=datetime.now(UTC),
        analysis_window_end=datetime.now(UTC),
        detection_rule_version="v1.0",
        scoring_model_version="v1.0",
        dedup_fingerprint="fp-test-1234",
        evidence_data={
            "detector": "FAN_IN",
            "source_count": 5,
            "window_seconds": 3600,
            "aggregate_amount": "45000.00",
            "pattern_description": f"Fan-in from multiple accounts to {acct_id}",
            "raw_account_leak_attempt": "123456",  # Should be ignored/not forwarded
        },
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    sanitized = DataDisclosurePolicy.sanitize_mulechain_alert(alert)

    # Must NOT contain raw accounts or prohibited keys
    for prohibited in PROHIBITED_DISCLOSURE_FIELDS:
        assert prohibited not in sanitized

    # Must contain coarsened fields
    assert sanitized["pattern_type"] == "FAN_IN"
    assert sanitized["burst_count"] == 5
    assert sanitized["anonymized_volume_tier"] == "TIER_MEDIUM_10K_TO_100K"
    assert "[ANONYMIZED_ENTITY]" in sanitized["pattern_description"]

    # All fields must be within allowlist
    for k in sanitized:
        assert k in ALLOWED_EVIDENCE_FIELDS


def test_provenance_validation_rejects_prohibited_and_unallowlisted_fields() -> None:
    """Provenance metadata must reject sensitive fields and unapproved attributes."""
    from sentinel_chain_drive.schemas.privacy import (
        ALLOWED_PROVENANCE_FIELDS,
        validate_provenance_against_allowlist,
    )

    # Valid provenance
    valid_prov = {
        "source_type": "MULECHAIN_DETECTOR",
        "detector_type": "FAN_IN",
        "scoring_model_version": "v1.0",
        "detection_rule_version": "v1.0",
        "origin_timestamp": datetime.now(UTC).isoformat(),
        "algorithm": "TOPOLOGICAL_DIRECTED_MULTIGRAPH",
    }
    validated = validate_provenance_against_allowlist(valid_prov)
    for k in validated:
        assert k in ALLOWED_PROVENANCE_FIELDS

    # Prohibited field: raw account
    bad_prov_1 = dict(valid_prov, account_number="123456789")
    with pytest.raises(ValueError, match="Prohibited disclosure field"):
        validate_provenance_against_allowlist(bad_prov_1)

    # Prohibited field: secret_key
    bad_prov_2 = dict(valid_prov, secret_key="super_secret")
    with pytest.raises(ValueError, match="Prohibited disclosure field"):
        validate_provenance_against_allowlist(bad_prov_2)

    # Unapproved field
    bad_prov_3 = dict(valid_prov, arbitrary_unapproved_meta="test")
    with pytest.raises(ValueError, match="Unapproved provenance field"):
        validate_provenance_against_allowlist(bad_prov_3)


def test_case_variant_prohibited_fields_detected() -> None:
    """Case variants and padded whitespace in prohibited fields must be caught."""
    variants = [
        "  ACCOUNT_NUMBER  ",
        "Customer_Name",
        "pRIvATe_Key",
        "  PASSWORD ",
        "RAW_TRANSACTION_IDS",
    ]
    for field_variant in variants:
        payload = {
            field_variant: "sensitive_data",
            "pattern_type": "FAN_IN",
        }
        with pytest.raises(ValueError, match="Prohibited disclosure field"):
            validate_evidence_against_disclosure_allowlist(payload)


def test_pattern_description_redacts_account_numbers_and_large_numbers() -> None:
    """MuleChain alert description containing account numbers or long digits are redacted."""
    inst_id = uuid.uuid4()
    alert = FraudAlert(
        id=uuid.uuid4(),
        alert_code="ALT-TEST-DESC",
        detector_type=DetectorType.RAPID_PASSTHROUGH,
        severity=AlertSeverity.HIGH,
        status=AlertStatus.NEW,
        risk_score=80,
        primary_institution_id=inst_id,
        primary_account_id=uuid.uuid4(),
        currency="USD",
        analysis_window_start=datetime.now(UTC),
        analysis_window_end=datetime.now(UTC),
        detection_rule_version="v1.0",
        scoring_model_version="v1.0",
        dedup_fingerprint="fp-desc-1234",
        evidence_data={
            "detector": "RAPID_PASSTHROUGH",
            "window_seconds": 1800,
            "pattern_description": (
                "Pass-through mule ACCT-SECRET-5555 received funds from 9876543210123"
            ),
        },
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    sanitized = DataDisclosurePolicy.sanitize_mulechain_alert(alert)
    desc = sanitized["pattern_description"]
    assert "ACCT-SECRET-5555" not in desc
    assert "[ANONYMIZED_ACCOUNT]" in desc
    assert "9876543210123" not in desc
    assert "[REDACTED_NUMBER]" in desc
