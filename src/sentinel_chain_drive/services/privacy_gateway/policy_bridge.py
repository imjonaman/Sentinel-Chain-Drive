"""Policy engine integration bridge for the Privacy Gateway.

Converts validated, authorized cross-institution indicators into deterministic
Phase 4 RiskSignals telemetry without altering policy engine authority or
violating institutional isolation.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from sentinel_chain_drive.db.models.shared_indicator import (
    IndicatorSeverity,
    IndicatorStatus,
    SharedIndicator,
)
from sentinel_chain_drive.schemas.policy import RiskSignals


class PrivacyGatewayPolicyBridge:
    """Translates shared fraud indicators into deterministic RiskSignals."""

    # Deterministic mapping from indicator severity to minimum risk score
    SEVERITY_SCORE_MAP = {
        IndicatorSeverity.LOW: 0.25,
        IndicatorSeverity.MEDIUM: 0.50,
        IndicatorSeverity.HIGH: 0.75,
        IndicatorSeverity.CRITICAL: 0.90,
    }

    @classmethod
    def evaluate_indicators(
        cls,
        indicators: Sequence[SharedIndicator],
        base_signals: RiskSignals | None = None,
        evaluation_time: datetime | None = None,
    ) -> RiskSignals:
        """Evaluate a set of shared indicators against an account and produce RiskSignals.

        Rules:
        - Expired indicators (expires_at <= evaluation_time) are strictly excluded.
        - Non-ACTIVE indicators (REVOKED, EXPIRED, WITHDRAWN) are strictly excluded.
        - Zero active matching indicators returns an explicit NO_MATCH telemetry.
        - Active indicators elevate the risk score monotonically and preserve provenance metadata.
        - Does NOT invent calibrated fraud probabilities; uses deterministic score caps.
        """
        now = evaluation_time or datetime.now(UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)

        base = base_signals or RiskSignals()

        # Filter strictly active, non-expired indicators
        def _is_active_and_valid(ind: SharedIndicator) -> bool:
            if ind.status != IndicatorStatus.ACTIVE:
                return False
            if ind.expires_at is None:
                return True
            exp = (
                ind.expires_at.replace(tzinfo=UTC)
                if ind.expires_at.tzinfo is None
                else ind.expires_at
            )
            return exp > now

        active: list[SharedIndicator] = [ind for ind in indicators if _is_active_and_valid(ind)]

        if not active:
            # Explicit NO-MATCH
            custom = dict(base.custom_signals)
            custom["cross_institution_intel"] = {
                "status": "NO_MATCH",
                "active_indicators_count": 0,
                "evaluated_at": now.isoformat(),
            }
            return RiskSignals(
                risk_score=base.risk_score,
                velocity_warning=base.velocity_warning,
                manual_review_flag=base.manual_review_flag,
                custom_signals=custom,
            )

        # Determine highest severity among active indicators
        severity_order = [
            IndicatorSeverity.LOW,
            IndicatorSeverity.MEDIUM,
            IndicatorSeverity.HIGH,
            IndicatorSeverity.CRITICAL,
        ]
        max_severity = max(active, key=lambda ind: severity_order.index(ind.severity)).severity
        derived_score = cls.SEVERITY_SCORE_MAP[max_severity]

        # Combine monotonically with existing base score
        final_score = max(base.risk_score or 0.0, derived_score)

        # Flag manual review for CRITICAL indicators
        manual_review = base.manual_review_flag or (max_severity == IndicatorSeverity.CRITICAL)

        # Check for velocity patterns in indicators
        velocity_pattern = any(
            ind.pattern_category in (
                "RAPID_DISPERSION",
                "STRUCTURING_FAN_OUT",
                "HIGH_VELOCITY_BURST",
            )
            for ind in active
        )
        velocity_warning = base.velocity_warning or velocity_pattern

        origin_inst_count = len({ind.originating_institution_id for ind in active})
        custom = dict(base.custom_signals)
        custom["cross_institution_intel"] = {
            "status": "MATCH",
            "active_indicators_count": len(active),
            "max_severity": max_severity.value,
            "originating_institutions_count": origin_inst_count,
            "indicator_types": sorted({ind.indicator_type.value for ind in active}),
            "evaluated_at": now.isoformat(),
        }

        return RiskSignals(
            risk_score=final_score,
            velocity_warning=velocity_warning,
            manual_review_flag=manual_review,
            custom_signals=custom,
        )

    @classmethod
    def unavailable_intel_signals(
        cls,
        base_signals: RiskSignals | None = None,
        reason: str = "GATEWAY_UNAVAILABLE",
    ) -> RiskSignals:
        """Produce RiskSignals when external intelligence service is unavailable.

        Crucial requirement: Distinguish unavailable intelligence from an explicit no-match.
        Does NOT convert an outage into a low-risk signal or a clean bill of health.
        """
        base = base_signals or RiskSignals()
        custom = dict(base.custom_signals)
        custom["cross_institution_intel"] = {
            "status": "UNAVAILABLE",
            "reason": reason,
            "fallback": "LOCAL_POLICY_ONLY",
        }
        return RiskSignals(
            risk_score=base.risk_score,
            velocity_warning=base.velocity_warning,
            manual_review_flag=base.manual_review_flag,
            custom_signals=custom,
        )

