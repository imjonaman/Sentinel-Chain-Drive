"""MuleChain fraud intelligence orchestrator service."""

import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.db.models.alert import (
    AlertSeverity,
    AlertStatus,
    DetectorType,
    FraudAlert,
)
from sentinel_chain_drive.db.models.transaction import TransactionStatus
from sentinel_chain_drive.repositories.account_repository import AccountRepository
from sentinel_chain_drive.repositories.alert_repository import AlertRepository
from sentinel_chain_drive.repositories.transaction_repository import TransactionRepository
from sentinel_chain_drive.schemas.alert import (
    FraudAlertResponse,
    MuleChainAnalysisSummary,
)
from sentinel_chain_drive.schemas.policy import RiskSignals
from sentinel_chain_drive.services.mulechain.detectors import (
    BaseDetector,
    CircularLayeringDetector,
    FanInDetector,
    FanOutDetector,
    RapidPassThroughDetector,
)
from sentinel_chain_drive.services.mulechain.graph_builder import TransactionGraphBuilder
from sentinel_chain_drive.services.mulechain.models import DetectorFinding
from sentinel_chain_drive.services.mulechain.scoring import RiskScoringService


class MuleChainService:
    """Orchestrates transaction graph analysis, fraud pattern detection, and alert lifecycle."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.transaction_repo = TransactionRepository(session)
        self.alert_repo = AlertRepository(session)
        self.account_repo = AccountRepository(session)

    async def run_analysis(
        self,
        institution_id: uuid.UUID,
        currency: str,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
        max_transactions: int = 5000,
        include_detectors: list[DetectorType] | None = None,
    ) -> MuleChainAnalysisSummary:
        """Execute deterministic graph analysis for an institution's transaction network."""
        start_wall_time = time.perf_counter()
        now = datetime.now(UTC)

        if window_end is not None:
            cutoff_end = (
                window_end.replace(tzinfo=UTC)
                if window_end.tzinfo is None
                else window_end.astimezone(UTC)
            )
        else:
            cutoff_end = now

        if window_start is not None:
            cutoff_start = (
                window_start.replace(tzinfo=UTC)
                if window_start.tzinfo is None
                else window_start.astimezone(UTC)
            )
        else:
            cutoff_start = cutoff_end - timedelta(days=7)

        currency_clean = currency.strip().upper()
        if len(currency_clean) != 3:
            raise ValueError(f"Invalid currency code: {currency}")

        # 1. Fetch transactions deterministically ordered
        # We query transactions involving the institution to analyze cross-bank and internal flows
        transactions = await self.transaction_repo.list_for_graph(
            currency=currency_clean,
            from_time=cutoff_start,
            to_time=cutoff_end,
            institution_id=institution_id,
            status=TransactionStatus.SETTLED,
            limit=max_transactions,
        )

        # 2. Build MultiDiGraph
        builder = TransactionGraphBuilder(
            currency=currency_clean,
            allowed_status=TransactionStatus.SETTLED,
        )
        graph = builder.build_graph(
            transactions=transactions,
            from_time=cutoff_start,
            to_time=cutoff_end,
        )

        # 3. Instantiate selected detectors
        detectors_to_run: list[BaseDetector] = []
        detector_types = set(include_detectors or [
            DetectorType.FAN_IN,
            DetectorType.FAN_OUT,
            DetectorType.RAPID_PASSTHROUGH,
            DetectorType.CIRCULAR_LAYERING,
        ])

        if DetectorType.FAN_IN in detector_types:
            detectors_to_run.append(FanInDetector(currency=currency_clean))
        if DetectorType.FAN_OUT in detector_types:
            detectors_to_run.append(FanOutDetector(currency=currency_clean))
        if DetectorType.RAPID_PASSTHROUGH in detector_types:
            detectors_to_run.append(RapidPassThroughDetector(currency=currency_clean))
        if DetectorType.CIRCULAR_LAYERING in detector_types:
            detectors_to_run.append(CircularLayeringDetector(currency=currency_clean))

        # 4. Execute detectors
        raw_findings: list[DetectorFinding] = []
        for detector in detectors_to_run:
            findings = detector.detect(graph)
            raw_findings.extend(findings)

        # 5. Filter findings to the caller's institution scope and persist alerts idempotently
        alerts_generated = 0
        alerts_deduplicated = 0
        persisted_alerts: list[FraudAlert] = []

        for finding in raw_findings:
            # Enforce institution isolation
            if finding.primary_institution_id != institution_id:
                continue

            alert_model = FraudAlert(
                alert_code=finding.alert_code,
                detector_type=finding.detector_type,
                severity=finding.severity,
                risk_score=finding.risk_score,
                primary_institution_id=finding.primary_institution_id,
                primary_account_id=finding.primary_account_id,
                currency=finding.currency,
                analysis_window_start=finding.analysis_window_start,
                analysis_window_end=finding.analysis_window_end,
                detection_rule_version=finding.detection_rule_version,
                scoring_model_version=finding.scoring_model_version,
                evidence_data=finding.evidence_data,
                dedup_fingerprint=finding.dedup_fingerprint,
                status=AlertStatus.NEW,
            )

            saved_alert, was_created = await self.alert_repo.create_idempotent(alert_model)
            persisted_alerts.append(saved_alert)
            if was_created:
                alerts_generated += 1
            else:
                alerts_deduplicated += 1

        elapsed_ms = round((time.perf_counter() - start_wall_time) * 1000, 2)

        return MuleChainAnalysisSummary(
            analysis_id=uuid.uuid4(),
            institution_id=institution_id,
            currency=currency_clean,
            window_start=cutoff_start,
            window_end=cutoff_end,
            transactions_analyzed=len(transactions),
            accounts_analyzed=graph.number_of_nodes(),
            alerts_generated=alerts_generated,
            alerts_deduplicated=alerts_deduplicated,
            execution_time_ms=elapsed_ms,
            alerts=[FraudAlertResponse.model_validate(a) for a in persisted_alerts],
        )

    async def get_alert(
        self,
        alert_id: uuid.UUID,
        institution_id: uuid.UUID,
    ) -> FraudAlert | None:
        """Retrieve a specific alert verifying caller institution tenant isolation."""
        return await self.alert_repo.get_by_id_scoped(alert_id, institution_id)

    async def list_alerts(
        self,
        institution_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
        detector_type: DetectorType | None = None,
        severity: AlertSeverity | None = None,
        status: AlertStatus | None = None,
        account_id: uuid.UUID | None = None,
    ) -> tuple[list[FraudAlert], int]:
        """List paginated alerts scoped to caller institution."""
        items, total = await self.alert_repo.list_alerts_scoped(
            institution_id=institution_id,
            limit=limit,
            offset=offset,
            detector_type=detector_type,
            severity=severity,
            status=status,
            account_id=account_id,
        )
        return list(items), total

    async def get_account_risk_signals(
        self,
        account_id: uuid.UUID,
        institution_id: uuid.UUID,
        stale_threshold_hours: int = 48,
    ) -> RiskSignals:
        """Extract recent MuleChain alerts on an account to produce Phase 4 RiskSignals."""
        alerts, _ = await self.alert_repo.list_alerts_scoped(
            institution_id=institution_id,
            account_id=account_id,
            limit=20,
        )

        if not alerts:
            return RiskSignals(
                risk_score=0.0,
                velocity_warning=False,
                manual_review_flag=False,
                custom_signals={
                    "mulechain_alerts_count": 0,
                    "is_stale": False,
                },
            )

        now = datetime.now(UTC)
        newest_alert_time = max(a.created_at for a in alerts)
        age_hours = (now - newest_alert_time).total_seconds() / 3600.0
        is_stale = age_hours > stale_threshold_hours

        # Convert FraudAlerts to pseudo-findings for scoring aggregation
        pseudo_findings = [
            DetectorFinding(
                detector_type=a.detector_type,
                alert_code=a.alert_code,
                primary_account_id=a.primary_account_id or account_id,
                primary_institution_id=a.primary_institution_id,
                currency=a.currency,
                analysis_window_start=a.analysis_window_start,
                analysis_window_end=a.analysis_window_end,
                detection_rule_version=a.detection_rule_version,
                scoring_model_version=a.scoring_model_version,
                risk_score=a.risk_score,
                severity=a.severity,
                evidence_data=a.evidence_data,
                involved_account_ids=[account_id],
                involved_transaction_ids=[],
                dedup_fingerprint=a.dedup_fingerprint,
            )
            for a in alerts
        ]

        return RiskScoringService.build_risk_signals_for_policy_engine(
            findings=pseudo_findings,
            account_id=account_id,
            is_stale=is_stale,
        )
