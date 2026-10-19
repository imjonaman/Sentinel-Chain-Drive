"""Explainable risk scoring service for MuleChain fraud intelligence."""

import uuid
from typing import Any

from sentinel_chain_drive.db.models.alert import AlertSeverity, DetectorType
from sentinel_chain_drive.schemas.policy import RiskSignals
from sentinel_chain_drive.services.mulechain.models import DetectorFinding


class RiskScoringService:
    """Computes deterministic, explainable risk prioritization scores from 0 to 100."""

    SCORING_MODEL_VERSION = "v1.0"

    # Base risk scores per detector topology
    BASE_SCORES: dict[DetectorType, int] = {
        DetectorType.CIRCULAR_LAYERING: 85,
        DetectorType.RAPID_PASSTHROUGH: 75,
        DetectorType.FAN_IN: 65,
        DetectorType.FAN_OUT: 60,
    }

    @classmethod
    def map_severity(cls, score: int) -> AlertSeverity:
        """Map integer risk score (0-100) to AlertSeverity category."""
        if score >= 85:
            return AlertSeverity.CRITICAL
        if score >= 60:
            return AlertSeverity.HIGH
        if score >= 30:
            return AlertSeverity.MEDIUM
        return AlertSeverity.LOW

    @classmethod
    def normalize_score(cls, score: int) -> float:
        """Normalize 0-100 integer score to [0.0, 1.0] float for Phase 4 Policy Engine."""
        bounded = max(0, min(100, score))
        return round(bounded / 100.0, 4)

    @classmethod
    def aggregate_account_findings(
        cls,
        findings: list[DetectorFinding],
    ) -> tuple[int, AlertSeverity, dict[str, Any]]:
        """Compute composite account-level risk score across multiple detected indicators.

        Formula: max(scores) + sum(other_scores // 4), bounded at 100.
        Uses diminishing returns to prevent runaway aggregation while escalating
        multi-pattern behavior.
        """
        if not findings:
            return 0, AlertSeverity.LOW, {"score": 0, "findings_count": 0}

        scores = [f.risk_score for f in findings]
        scores.sort(reverse=True)

        primary_score = scores[0]
        secondary_contributions = sum(s // 4 for s in scores[1:])
        composite_score = min(100, primary_score + secondary_contributions)
        severity = cls.map_severity(composite_score)

        breakdown = {
            "scoring_model_version": cls.SCORING_MODEL_VERSION,
            "primary_indicator_score": primary_score,
            "secondary_contributions": secondary_contributions,
            "composite_score": composite_score,
            "severity": severity.value,
            "indicators_evaluated": [f.detector_type.value for f in findings],
            "disclaimer": (
                "Prioritization score based on topological graph patterns. "
                "Not a calibrated statistical fraud probability."
            ),
        }

        return composite_score, severity, breakdown

    @classmethod
    def build_risk_signals_for_policy_engine(
        cls,
        findings: list[DetectorFinding],
        account_id: uuid.UUID,
        is_stale: bool = False,
    ) -> RiskSignals:
        """Produce Phase 4 compatible RiskSignals payload from MuleChain findings.

        Ensures policy engine receives authoritative deterministic signals without
        circular dependencies.
        """
        if not findings:
            return RiskSignals(
                risk_score=0.0,
                velocity_warning=False,
                manual_review_flag=False,
                custom_signals={
                    "account_id": str(account_id),
                    "mulechain_findings_count": 0,
                    "is_stale": is_stale,
                },
            )

        composite_score, severity, breakdown = cls.aggregate_account_findings(findings)
        normalized_score = cls.normalize_score(composite_score)

        has_rapid_movement = any(
            f.detector_type in (DetectorType.RAPID_PASSTHROUGH, DetectorType.FAN_OUT)
            for f in findings
        )
        requires_manual_review = composite_score >= 60

        return RiskSignals(
            risk_score=normalized_score,
            velocity_warning=has_rapid_movement,
            manual_review_flag=requires_manual_review,
            custom_signals={
                "account_id": str(account_id),
                "mulechain_raw_score": composite_score,
                "mulechain_severity": severity.value,
                "mulechain_findings_count": len(findings),
                "is_stale": is_stale,
                "breakdown": breakdown,
                "alert_fingerprints": [f.dedup_fingerprint for f in findings],
            },
        )
