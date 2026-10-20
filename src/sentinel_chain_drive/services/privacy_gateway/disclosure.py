"""Data disclosure policy and evidence sanitization for Privacy Gateway."""

import re
from decimal import Decimal
from typing import Any

from sentinel_chain_drive.db.models.alert import FraudAlert
from sentinel_chain_drive.schemas.privacy import (
    validate_evidence_against_disclosure_allowlist,
)


class DataDisclosurePolicy:
    """Enforces field-level disclosure allowlists and sanitizes fraud evidence.

    Privacy Invariant:
    Under no circumstances are raw customer names, raw account numbers,
    credentials, private keys, or raw transaction identifiers permitted
    to leave the originating institution boundary.
    """

    POLICY_VERSION: str = "v1.0"

    @staticmethod
    def classify_volume_tier(amount: Decimal | float | int | str) -> str:
        """Categorize monetary flow into coarse tiers without exposing exact financial amounts."""
        try:
            val = Decimal(str(amount))
        except Exception:
            return "TIER_UNKNOWN"

        if val < Decimal("1000.0000"):
            return "TIER_MICRO_UNDER_1K"
        if val < Decimal("10000.0000"):
            return "TIER_LOW_1K_TO_10K"
        if val < Decimal("100000.0000"):
            return "TIER_MEDIUM_10K_TO_100K"
        return "TIER_HIGH_OVER_100K"

    @classmethod
    def sanitize_mulechain_alert(cls, alert: FraudAlert) -> dict[str, Any]:
        """Transform a localized MuleChain FraudAlert into sanitized cross-institution evidence.

        Strips:
        - Exact raw transaction UUIDs
        - Source and destination account UUIDs
        - Raw monetary totals
        - Customer-identifiable references

        Retains:
        - Topological pattern classification
        - Time window duration
        - Anonymized count tiers (burst size)
        - Anonymized volume tier
        - Rule and scoring model versions
        - High-level pattern description
        """
        raw_evidence = alert.evidence_data or {}

        detector = raw_evidence.get("detector", str(alert.detector_type.value))
        window_seconds = raw_evidence.get("window_seconds", 3600)
        description = raw_evidence.get("pattern_description", "")

        # Clean description to remove any embedded UUIDs, account patterns, or specific numbers
        clean_desc = re.sub(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
            "[ANONYMIZED_ENTITY]",
            str(description),
        )
        clean_desc = re.sub(r"\bACCT-[A-Za-z0-9_-]+\b", "[ANONYMIZED_ACCOUNT]", clean_desc)
        clean_desc = re.sub(r"\b\d{8,20}\b", "[REDACTED_NUMBER]", clean_desc)

        burst_count = (
            raw_evidence.get("source_count")
            or raw_evidence.get("destination_count")
            or raw_evidence.get("cycle_length")
            or 3
        )

        aggregate_amt = raw_evidence.get("aggregate_amount") or raw_evidence.get(
            "cycle_total_amount"
        )
        volume_tier = cls.classify_volume_tier(aggregate_amt) if aggregate_amt else "TIER_UNKNOWN"

        sanitized_evidence: dict[str, Any] = {
            "pattern_type": str(alert.detector_type.value),
            "detector": str(detector),
            "window_seconds": int(window_seconds),
            "burst_count": int(burst_count),
            "anonymized_volume_tier": volume_tier,
            "mulechain_rule_version": str(alert.detection_rule_version),
            "scoring_model_version": str(alert.scoring_model_version),
            "pattern_description": clean_desc,
        }

        if "cycle_length" in raw_evidence:
            sanitized_evidence["flow_hop_count"] = int(raw_evidence["cycle_length"])

        if "retention_ratio" in raw_evidence:
            try:
                ratio = float(raw_evidence["retention_ratio"])
                if ratio >= 0.95:
                    sanitized_evidence["ratio_range"] = "VERY_HIGH_RETENTION_OVER_95PCT"
                elif ratio >= 0.80:
                    sanitized_evidence["ratio_range"] = "HIGH_RETENTION_80_TO_95PCT"
                else:
                    sanitized_evidence["ratio_range"] = "STANDARD_RETENTION"
            except Exception:
                pass

        # Validate against strict disclosure allowlist
        return validate_evidence_against_disclosure_allowlist(sanitized_evidence)
