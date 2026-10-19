"""Unit tests for MuleChain explainable risk scoring and Policy Engine bridge."""

import uuid
from datetime import UTC, datetime

from sentinel_chain_drive.db.models.alert import AlertSeverity, DetectorType
from sentinel_chain_drive.services.mulechain.fingerprint import compute_alert_fingerprint
from sentinel_chain_drive.services.mulechain.models import DetectorFinding
from sentinel_chain_drive.services.mulechain.scoring import RiskScoringService


def _dummy_finding(
    detector_type: DetectorType,
    score: int,
    account_id: uuid.UUID,
    inst_id: uuid.UUID,
    tx_ids: list[uuid.UUID],
) -> DetectorFinding:
    now = datetime.now(UTC)
    return DetectorFinding(
        detector_type=detector_type,
        alert_code=f"MULE_{detector_type.value}",
        primary_account_id=account_id,
        primary_institution_id=inst_id,
        currency="USD",
        analysis_window_start=now,
        analysis_window_end=now,
        detection_rule_version="v1.0",
        scoring_model_version="v1.0",
        risk_score=score,
        severity=RiskScoringService.map_severity(score),
        evidence_data={"score": score},
        involved_account_ids=[account_id],
        involved_transaction_ids=tx_ids,
        dedup_fingerprint=f"fp-{uuid.uuid4()}",
    )


class TestRiskScoringService:
    """Tests deterministic risk scoring formulas and severity categorization."""

    def test_severity_threshold_mapping(self) -> None:
        assert RiskScoringService.map_severity(0) == AlertSeverity.LOW
        assert RiskScoringService.map_severity(29) == AlertSeverity.LOW
        assert RiskScoringService.map_severity(30) == AlertSeverity.MEDIUM
        assert RiskScoringService.map_severity(59) == AlertSeverity.MEDIUM
        assert RiskScoringService.map_severity(60) == AlertSeverity.HIGH
        assert RiskScoringService.map_severity(84) == AlertSeverity.HIGH
        assert RiskScoringService.map_severity(85) == AlertSeverity.CRITICAL
        assert RiskScoringService.map_severity(100) == AlertSeverity.CRITICAL

    def test_score_normalization(self) -> None:
        assert RiskScoringService.normalize_score(0) == 0.0
        assert RiskScoringService.normalize_score(50) == 0.5
        assert RiskScoringService.normalize_score(85) == 0.85
        assert RiskScoringService.normalize_score(100) == 1.0
        assert RiskScoringService.normalize_score(120) == 1.0
        assert RiskScoringService.normalize_score(-10) == 0.0

    def test_multi_indicator_composite_score(self) -> None:
        inst_id = uuid.uuid4()
        acc_id = uuid.uuid4()

        # Findings: Circular Layering (85) + Rapid Pass-Through (75)
        # Expected composite: 85 + (75 // 4) = 85 + 18 = 103 -> capped at 100
        f1 = _dummy_finding(DetectorType.CIRCULAR_LAYERING, 85, acc_id, inst_id, [uuid.uuid4()])
        f2 = _dummy_finding(DetectorType.RAPID_PASSTHROUGH, 75, acc_id, inst_id, [uuid.uuid4()])

        score, severity, breakdown = RiskScoringService.aggregate_account_findings([f1, f2])
        assert score == 100
        assert severity == AlertSeverity.CRITICAL
        assert breakdown["primary_indicator_score"] == 85
        assert breakdown["secondary_contributions"] == 18

    def test_policy_engine_risk_signals_bridge_fresh(self) -> None:
        inst_id = uuid.uuid4()
        acc_id = uuid.uuid4()
        tx_id = uuid.uuid4()

        f = _dummy_finding(DetectorType.RAPID_PASSTHROUGH, 75, acc_id, inst_id, [tx_id])
        signals = RiskScoringService.build_risk_signals_for_policy_engine(
            findings=[f],
            account_id=acc_id,
            is_stale=False,
        )

        assert signals.risk_score == 0.75
        assert signals.velocity_warning is True
        assert signals.manual_review_flag is True
        assert signals.custom_signals["is_stale"] is False
        assert signals.custom_signals["mulechain_raw_score"] == 75
        assert signals.custom_signals["account_id"] == str(acc_id)

    def test_policy_engine_risk_signals_bridge_stale(self) -> None:
        inst_id = uuid.uuid4()
        acc_id = uuid.uuid4()
        tx_id = uuid.uuid4()

        f = _dummy_finding(DetectorType.FAN_IN, 65, acc_id, inst_id, [tx_id])
        signals = RiskScoringService.build_risk_signals_for_policy_engine(
            findings=[f],
            account_id=acc_id,
            is_stale=True,
        )

        assert signals.risk_score == 0.65
        assert signals.custom_signals["is_stale"] is True


class TestAlertFingerprint:
    """Tests determinism and idempotency of alert deduplication fingerprinting."""

    def test_fingerprint_is_deterministic(self) -> None:
        inst_id = uuid.uuid4()
        acc_id = uuid.uuid4()
        tx1 = uuid.uuid4()
        tx2 = uuid.uuid4()

        # Same transactions in different order must yield identical fingerprints
        fp1 = compute_alert_fingerprint(
            institution_id=inst_id,
            detector_type=DetectorType.FAN_IN,
            primary_account_id=acc_id,
            currency="USD",
            involved_transaction_ids=[tx1, tx2],
            rule_version="v1.0",
        )

        fp2 = compute_alert_fingerprint(
            institution_id=inst_id,
            detector_type=DetectorType.FAN_IN,
            primary_account_id=acc_id,
            currency="USD",
            involved_transaction_ids=[tx2, tx1],
            rule_version="v1.0",
        )

        assert fp1 == fp2
        assert len(fp1) == 64  # SHA-256 hex string

    def test_different_accounts_yield_different_fingerprints(self) -> None:
        inst_id = uuid.uuid4()
        tx1 = uuid.uuid4()

        fp1 = compute_alert_fingerprint(
            institution_id=inst_id,
            detector_type=DetectorType.FAN_IN,
            primary_account_id=uuid.uuid4(),
            currency="USD",
            involved_transaction_ids=[tx1],
        )

        fp2 = compute_alert_fingerprint(
            institution_id=inst_id,
            detector_type=DetectorType.FAN_IN,
            primary_account_id=uuid.uuid4(),
            currency="USD",
            involved_transaction_ids=[tx1],
        )

        assert fp1 != fp2
