"""Deterministic deduplication fingerprint generation for MuleChain alerts."""

import hashlib
import uuid

from sentinel_chain_drive.db.models.alert import DetectorType


def compute_alert_fingerprint(
    institution_id: uuid.UUID,
    detector_type: DetectorType,
    primary_account_id: uuid.UUID,
    currency: str,
    involved_transaction_ids: list[uuid.UUID],
    rule_version: str = "v1.0",
) -> str:
    """Generate a deterministic SHA-256 fingerprint for a fraud finding.

    This ensures identical topological detections over the same supporting transactions
    produce identical keys, preventing duplicate alerts upon re-runs.
    """
    sorted_tx_str = ",".join(sorted(str(tx_id) for tx_id in involved_transaction_ids))
    raw_payload = (
        f"{institution_id}:"
        f"{detector_type.value}:"
        f"{primary_account_id}:"
        f"{currency.upper()}:"
        f"{sorted_tx_str}:"
        f"{rule_version}"
    )
    return hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()
