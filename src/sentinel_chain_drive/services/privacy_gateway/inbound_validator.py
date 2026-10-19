"""Inbound indicator validation for untrusted external intelligence."""

import re
from datetime import UTC, datetime
from typing import Any

from sentinel_chain_drive.db.models.shared_indicator import (
    IndicatorSeverity,
    IndicatorType,
)
from sentinel_chain_drive.schemas.privacy import (
    validate_evidence_against_disclosure_allowlist,
)

HEX_64_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
SUPPORTED_SCHEMA_VERSIONS = {"v1.0"}


class InboundIndicatorValidator:
    """Validates inbound cross-institution intelligence payloads.

    Trust Boundary Rule:
    All inbound intelligence from external institutions must be treated as untrusted input.
    Expired, malformed, oversized, or unauthorized indicators are rejected immediately.
    Validation failures must fail closed and NEVER be interpreted as a clean bill of health.
    """

    @classmethod
    def validate_inbound_indicator(
        cls,
        pseudonymous_mesh_id: str,
        indicator_type: IndicatorType | str,
        severity: IndicatorSeverity | str,
        confidence_score: float,
        pattern_category: str,
        evidence_summary: dict[str, Any],
        expires_at: datetime,
        schema_version: str = "v1.0",
        now: datetime | None = None,
    ) -> None:
        """Execute validation suite against an untrusted inbound indicator payload."""
        current_time = now or datetime.now(UTC)

        # 1. Schema version validation
        if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f"Unsupported indicator schema version: '{schema_version}'. "
                f"Supported versions: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
            )

        # 2. Pseudonym format validation
        if not HEX_64_PATTERN.match(pseudonymous_mesh_id):
            raise ValueError(
                "Invalid MeshID format. Expected exactly 64 hexadecimal characters."
            )

        # 3. Indicator type validation
        if isinstance(indicator_type, str):
            try:
                IndicatorType(indicator_type)
            except ValueError as err:
                raise ValueError(f"Unrecognized indicator type: '{indicator_type}'") from err

        # 4. Severity validation
        if isinstance(severity, str):
            try:
                IndicatorSeverity(severity)
            except ValueError as err:
                raise ValueError(f"Unrecognized indicator severity: '{severity}'") from err

        # 5. Confidence score range
        if not (0.0 <= confidence_score <= 1.0):
            raise ValueError(
                f"Confidence score {confidence_score} must be within range [0.0, 1.0]."
            )

        # 6. Pattern category
        if not pattern_category or len(pattern_category.strip()) < 3:
            raise ValueError("Pattern category must be at least 3 characters.")

        # 7. Expiry validation (must be in the future)
        exp_time = (
            expires_at.replace(tzinfo=UTC)
            if expires_at.tzinfo is None
            else expires_at.astimezone(UTC)
        )
        if exp_time <= current_time:
            msg = (
                f"Indicator is expired. Expiration {exp_time.isoformat()} "
                f"<= current time {current_time.isoformat()}."
            )
            raise ValueError(msg)


        # 8. Field-level disclosure allowlist & prohibited field checks
        validate_evidence_against_disclosure_allowlist(evidence_summary)
