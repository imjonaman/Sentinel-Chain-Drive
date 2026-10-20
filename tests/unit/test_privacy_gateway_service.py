"""Unit tests for Privacy Gateway inbound validation, rate limiting, and PolicyBridge."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from sentinel_chain_drive.db.models.shared_indicator import (
    IndicatorSeverity,
    IndicatorStatus,
    IndicatorType,
    SharedIndicator,
)
from sentinel_chain_drive.schemas.policy import RiskSignals
from sentinel_chain_drive.services.privacy_gateway.inbound_validator import (
    InboundIndicatorValidator,
)
from sentinel_chain_drive.services.privacy_gateway.policy_bridge import (
    PrivacyGatewayPolicyBridge,
)
from sentinel_chain_drive.services.privacy_gateway.rate_limiter import (
    PrivacyQueryRateLimiter,
)


def test_inbound_validator_valid_payload() -> None:
    """Valid inbound indicator payload passes validation without error."""
    valid_mesh_id = "a" * 64
    future_time = datetime.now(UTC) + timedelta(days=2)

    # Should not raise
    InboundIndicatorValidator.validate_inbound_indicator(
        pseudonymous_mesh_id=valid_mesh_id,
        indicator_type=IndicatorType.MULE_BURST_INGRESS,
        severity=IndicatorSeverity.HIGH,
        confidence_score=0.88,
        pattern_category="TOPOLOGICAL_FAN_IN",
        evidence_summary={
            "pattern_type": "FAN_IN",
            "burst_count": 5,
            "anonymized_volume_tier": "TIER_LOW_1K_TO_10K",
        },
        expires_at=future_time,
    )


def test_inbound_validator_malformed_mesh_id() -> None:
    """Invalid MeshID hex string raises ValueError."""
    future_time = datetime.now(UTC) + timedelta(days=2)
    with pytest.raises(ValueError, match="Invalid MeshID format"):
        InboundIndicatorValidator.validate_inbound_indicator(
            pseudonymous_mesh_id="short_hex",
            indicator_type=IndicatorType.MULE_BURST_INGRESS,
            severity=IndicatorSeverity.HIGH,
            confidence_score=0.8,
            pattern_category="TOPOLOGICAL_FAN_IN",
            evidence_summary={},
            expires_at=future_time,
        )


def test_inbound_validator_expired_indicator_rejected() -> None:
    """Expired inbound indicator is strictly rejected and never treated as valid."""
    past_time = datetime.now(UTC) - timedelta(hours=1)
    with pytest.raises(ValueError, match="Indicator is expired"):
        InboundIndicatorValidator.validate_inbound_indicator(
            pseudonymous_mesh_id="b" * 64,
            indicator_type=IndicatorType.MULE_FAN_OUT,
            severity=IndicatorSeverity.CRITICAL,
            confidence_score=0.95,
            pattern_category="TOPOLOGICAL_FAN_OUT",
            evidence_summary={},
            expires_at=past_time,
        )


def test_inbound_validator_confidence_bounds() -> None:
    """Confidence score outside [0.0, 1.0] raises ValueError."""
    future_time = datetime.now(UTC) + timedelta(days=1)
    with pytest.raises(ValueError, match="Confidence score"):
        InboundIndicatorValidator.validate_inbound_indicator(
            pseudonymous_mesh_id="c" * 64,
            indicator_type=IndicatorType.MULE_FAN_OUT,
            severity=IndicatorSeverity.MEDIUM,
            confidence_score=1.5,
            pattern_category="TOPOLOGICAL_FAN_OUT",
            evidence_summary={},
            expires_at=future_time,
        )


def test_rate_limiter_allows_under_quota_and_blocks_over_quota() -> None:
    """Sliding-window rate limiter tracks quotas per institution and blocks excess queries."""
    limiter = PrivacyQueryRateLimiter(max_queries_per_window=3, window_seconds=60)
    inst = "inst-rate-test-1"

    # First 3 queries allowed
    allowed_1, rem_1 = limiter.is_allowed(inst)
    assert allowed_1 is True
    assert rem_1 == 2

    allowed_2, rem_2 = limiter.is_allowed(inst)
    assert allowed_2 is True
    assert rem_2 == 1

    allowed_3, rem_3 = limiter.is_allowed(inst)
    assert allowed_3 is True
    assert rem_3 == 0

    # 4th query blocked
    allowed_4, rem_4 = limiter.is_allowed(inst)
    assert allowed_4 is False
    assert rem_4 == 0

    # Another institution is completely unaffected
    other_inst = "inst-rate-test-2"
    other_allowed, other_rem = limiter.is_allowed(other_inst)
    assert other_allowed is True
    assert other_rem == 2


def test_policy_bridge_no_match() -> None:
    """Zero active matching indicators produces explicit NO_MATCH telemetry."""
    base = RiskSignals(risk_score=0.1)
    result = PrivacyGatewayPolicyBridge.evaluate_indicators(
        indicators=[],
        base_signals=base,
    )
    assert result.risk_score == 0.1
    assert result.manual_review_flag is False
    assert result.custom_signals["cross_institution_intel"]["status"] == "NO_MATCH"


def test_policy_bridge_critical_indicator_escalates_to_hold() -> None:
    """Active CRITICAL indicator elevates risk score to 0.90 and flags manual review."""
    now = datetime.now(UTC)
    future = now + timedelta(days=5)

    critical_ind = SharedIndicator(
        id=uuid.uuid4(),
        indicator_code="IND-CRIT-001",
        schema_version="v1.0",
        pseudonymous_mesh_id="d" * 64,
        originating_institution_id=uuid.uuid4(),
        indicator_type=IndicatorType.MULE_BURST_INGRESS,
        severity=IndicatorSeverity.CRITICAL,
        confidence_score=0.92,
        pattern_category="RAPID_DISPERSION",
        evidence_summary={},
        provenance={},
        sharing_policy_version="v1.0",
        status=IndicatorStatus.ACTIVE,
        expires_at=future,
        created_at=now,
        updated_at=now,
    )

    result = PrivacyGatewayPolicyBridge.evaluate_indicators(
        indicators=[critical_ind],
        evaluation_time=now,
    )

    assert result.risk_score == 0.90
    assert result.manual_review_flag is True
    assert result.velocity_warning is True
    assert result.custom_signals["cross_institution_intel"]["status"] == "MATCH"
    assert result.custom_signals["cross_institution_intel"]["max_severity"] == "CRITICAL"


def test_policy_bridge_excludes_expired_and_revoked_indicators() -> None:
    """Expired or revoked indicators are strictly excluded and not counted as active evidence."""
    now = datetime.now(UTC)
    past = now - timedelta(days=1)
    future = now + timedelta(days=5)

    expired_ind = SharedIndicator(
        id=uuid.uuid4(),
        indicator_code="IND-EXP-001",
        schema_version="v1.0",
        pseudonymous_mesh_id="e" * 64,
        originating_institution_id=uuid.uuid4(),
        indicator_type=IndicatorType.MULE_BURST_INGRESS,
        severity=IndicatorSeverity.CRITICAL,
        confidence_score=0.99,
        pattern_category="FAN_IN",
        evidence_summary={},
        provenance={},
        sharing_policy_version="v1.0",
        status=IndicatorStatus.ACTIVE,
        expires_at=past,  # Expired!
        created_at=now,
        updated_at=now,
    )

    revoked_ind = SharedIndicator(
        id=uuid.uuid4(),
        indicator_code="IND-REV-001",
        schema_version="v1.0",
        pseudonymous_mesh_id="e" * 64,
        originating_institution_id=uuid.uuid4(),
        indicator_type=IndicatorType.MULE_BURST_INGRESS,
        severity=IndicatorSeverity.HIGH,
        confidence_score=0.95,
        pattern_category="FAN_IN",
        evidence_summary={},
        provenance={},
        sharing_policy_version="v1.0",
        status=IndicatorStatus.REVOKED,  # Revoked!
        expires_at=future,
        created_at=now,
        updated_at=now,
    )

    result = PrivacyGatewayPolicyBridge.evaluate_indicators(
        indicators=[expired_ind, revoked_ind],
        evaluation_time=now,
    )

    # Excluded -> falls back to NO_MATCH
    assert result.risk_score is None
    assert result.manual_review_flag is False
    assert result.custom_signals["cross_institution_intel"]["status"] == "NO_MATCH"


def test_policy_bridge_unavailable_gateway_telemetry() -> None:
    """Gateway outage returns explicit UNAVAILABLE status without clearing existing risk."""
    base = RiskSignals(risk_score=0.4, velocity_warning=True)
    result = PrivacyGatewayPolicyBridge.unavailable_intel_signals(
        base_signals=base,
        reason="NETWORK_TIMEOUT",
    )
    assert result.risk_score == 0.4
    assert result.velocity_warning is True
    assert result.custom_signals["cross_institution_intel"]["status"] == "UNAVAILABLE"
    assert result.custom_signals["cross_institution_intel"]["fallback"] == "LOCAL_POLICY_ONLY"


def test_policy_bridge_boundary_scores() -> None:
    """Validate all four severity tiers against policy engine threshold expectations."""
    now = datetime.now(UTC)
    future = now + timedelta(days=5)

    def _make_ind(sev: IndicatorSeverity) -> SharedIndicator:
        return SharedIndicator(
            id=uuid.uuid4(),
            indicator_code=f"IND-{sev.value}",
            schema_version="v1.0",
            pseudonymous_mesh_id="a" * 64,
            originating_institution_id=uuid.uuid4(),
            indicator_type=IndicatorType.MULE_BURST_INGRESS,
            severity=sev,
            confidence_score=0.8,
            pattern_category="NORMAL_FLOW",
            evidence_summary={},
            provenance={},
            sharing_policy_version="v1.0",
            status=IndicatorStatus.ACTIVE,
            expires_at=future,
            created_at=now,
            updated_at=now,
        )

    # 1. LOW -> 0.25
    res_low = PrivacyGatewayPolicyBridge.evaluate_indicators(
        [_make_ind(IndicatorSeverity.LOW)], evaluation_time=now
    )
    assert res_low.risk_score == 0.25
    assert res_low.manual_review_flag is False

    # 2. MEDIUM -> 0.50 (meets standard step_up threshold)
    res_med = PrivacyGatewayPolicyBridge.evaluate_indicators(
        [_make_ind(IndicatorSeverity.MEDIUM)], evaluation_time=now
    )
    assert res_med.risk_score == 0.50
    assert res_med.manual_review_flag is False

    # 3. HIGH -> 0.75 (above standard step_up threshold 0.50)
    res_high = PrivacyGatewayPolicyBridge.evaluate_indicators(
        [_make_ind(IndicatorSeverity.HIGH)], evaluation_time=now
    )
    assert res_high.risk_score == 0.75
    assert res_high.manual_review_flag is False

    # 4. CRITICAL -> 0.90 (above standard hold threshold 0.85, manual review True)
    res_crit = PrivacyGatewayPolicyBridge.evaluate_indicators(
        [_make_ind(IndicatorSeverity.CRITICAL)], evaluation_time=now
    )
    assert res_crit.risk_score == 0.90
    assert res_crit.manual_review_flag is True

