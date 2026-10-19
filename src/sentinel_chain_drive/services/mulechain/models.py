"""Internal domain representations and indicator data models for MuleChain."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sentinel_chain_drive.db.models.alert import (
    AlertSeverity,
    DetectorType,
)


@dataclass(frozen=True)
class AccountNodeData:
    """Attributes stored on each account node within the transaction graph."""

    account_id: uuid.UUID
    institution_id: uuid.UUID
    account_type: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class TransactionEdgeData:
    """Attributes stored on each directed transaction edge in the multigraph."""

    transaction_id: uuid.UUID
    source_account_id: uuid.UUID
    destination_account_id: uuid.UUID
    source_institution_id: uuid.UUID
    destination_institution_id: uuid.UUID
    amount: Decimal
    currency: str
    timestamp: datetime
    status: str
    purpose_code: str | None = None


@dataclass(frozen=True)
class FanInConfig:
    """Configurable thresholds for Fan-In (smurfing ingress) detector."""

    min_sources: int = 5
    window_seconds: int = 86400  # 24 hours
    rule_version: str = "v1.0"

    def __post_init__(self) -> None:
        if self.min_sources < 2:
            raise ValueError("FanInConfig min_sources must be at least 2")
        if self.window_seconds <= 0:
            raise ValueError("FanInConfig window_seconds must be positive")


@dataclass(frozen=True)
class FanOutConfig:
    """Configurable thresholds for Fan-Out (rapid dispersal) detector."""

    min_destinations: int = 5
    window_seconds: int = 86400  # 24 hours
    rule_version: str = "v1.0"

    def __post_init__(self) -> None:
        if self.min_destinations < 2:
            raise ValueError("FanOutConfig min_destinations must be at least 2")
        if self.window_seconds <= 0:
            raise ValueError("FanOutConfig window_seconds must be positive")


@dataclass(frozen=True)
class RapidPassThroughConfig:
    """Configurable thresholds for Rapid Pass-Through (transit mule) detector."""

    max_delta_seconds: int = 1800  # 30 minutes
    min_pass_through_ratio: float = 0.85
    rule_version: str = "v1.0"

    def __post_init__(self) -> None:
        if self.max_delta_seconds <= 0:
            raise ValueError("RapidPassThroughConfig max_delta_seconds must be positive")
        if not (0.0 < self.min_pass_through_ratio <= 1.0):
            raise ValueError(
                "RapidPassThroughConfig min_pass_through_ratio must be between 0 and 1"
            )


@dataclass(frozen=True)
class CircularLayeringConfig:
    """Configurable thresholds for Circular Layering (directed cycle) detector."""

    min_cycle_length: int = 3
    max_cycle_length: int = 5
    window_seconds: int = 604800  # 7 days
    rule_version: str = "v1.0"

    def __post_init__(self) -> None:
        if self.min_cycle_length < 2:
            raise ValueError("CircularLayeringConfig min_cycle_length must be >= 2")
        if self.max_cycle_length < self.min_cycle_length:
            raise ValueError(
                "CircularLayeringConfig max_cycle_length cannot be less than min_cycle_length"
            )
        if self.max_cycle_length > 10:
            raise ValueError(
                "CircularLayeringConfig max_cycle_length cannot exceed 10 to bound graph traversal"
            )
        if self.window_seconds <= 0:
            raise ValueError("CircularLayeringConfig window_seconds must be positive")


@dataclass
class DetectorFinding:
    """Normalized finding emitted by a topological pattern detector."""

    detector_type: DetectorType
    alert_code: str
    primary_account_id: uuid.UUID
    primary_institution_id: uuid.UUID
    currency: str
    analysis_window_start: datetime
    analysis_window_end: datetime
    detection_rule_version: str
    scoring_model_version: str
    risk_score: int
    severity: AlertSeverity
    evidence_data: dict[str, Any]
    involved_account_ids: list[uuid.UUID]
    involved_transaction_ids: list[uuid.UUID]
    dedup_fingerprint: str = ""
