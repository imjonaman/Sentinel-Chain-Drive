"""MuleChain fraud intelligence schemas."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from sentinel_chain_drive.db.models.alert import (
    AlertSeverity,
    AlertStatus,
    DetectorType,
)

__all__ = [
    "AlertSeverity",
    "AlertStatus",
    "DetectorType",
    "FraudAlertListResponse",
    "FraudAlertResponse",
    "MuleChainAnalysisRequest",
    "MuleChainAnalysisSummary",
]


class FraudAlertResponse(BaseModel):
    """Fraud alert representation."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    alert_code: str
    detector_type: DetectorType
    severity: AlertSeverity
    status: AlertStatus
    risk_score: int
    primary_institution_id: uuid.UUID
    primary_account_id: uuid.UUID | None
    currency: str
    analysis_window_start: datetime
    analysis_window_end: datetime
    detection_rule_version: str
    scoring_model_version: str
    evidence_data: dict[str, Any]
    dedup_fingerprint: str
    created_at: datetime
    updated_at: datetime


class FraudAlertListResponse(BaseModel):
    """Paginated list of fraud alerts."""

    items: list[FraudAlertResponse]
    total: int
    page: int
    page_size: int


class MuleChainAnalysisRequest(BaseModel):
    """Request payload to execute MuleChain graph analysis."""

    currency: str = Field(
        min_length=3,
        max_length=3,
        description="ISO 4217 currency code to evaluate (currencies are isolated)",
    )
    window_start: datetime | None = Field(
        default=None,
        description="Beginning of analysis window. Defaults to 7 days before cutoff.",
    )
    window_end: datetime | None = Field(
        default=None,
        description="Cutoff timestamp for analysis. Defaults to current UTC time.",
    )
    max_transactions: int = Field(
        default=5000,
        ge=1,
        le=20000,
        description="Maximum transaction edges to ingest into the multigraph",
    )
    include_detectors: list[DetectorType] | None = Field(
        default=None,
        description="Subset of detectors to execute. Defaults to all 4 detectors if omitted.",
    )


class MuleChainAnalysisSummary(BaseModel):
    """Summary metrics of a completed graph analysis run."""

    analysis_id: uuid.UUID
    institution_id: uuid.UUID
    currency: str
    window_start: datetime
    window_end: datetime
    transactions_analyzed: int
    accounts_analyzed: int
    alerts_generated: int
    alerts_deduplicated: int
    execution_time_ms: float
    alerts: list[FraudAlertResponse]
