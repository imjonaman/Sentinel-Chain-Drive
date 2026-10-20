"""Mock implementation and simulator of the DRUNIX adapter for testing and local development.

IMPORTANT:
This class is an IN-MEMORY TEST SIMULATOR. It does NOT establish live network connections
to real DRUNIX distributed ledger nodes. Authoritative DRUNIX specifications (cryptographic
primitives, RPC endpoint schemas, consensus finality models, and authentication protocols)
remain pending from upstream consortium governance.
"""

import enum
import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

from sentinel_chain_drive.integrations.drunix.adapter import DRUNIXAdapter, DRUNIXReceipt
from sentinel_chain_drive.integrations.drunix.exceptions import (
    DRUNIXMalformedResponseError,
    DRUNIXTerminalError,
    DRUNIXTimeoutError,
    DRUNIXTransientError,
    DRUNIXUncertainOutcomeError,
)

logger = logging.getLogger(__name__)


class MockSimulationMode(enum.StrEnum):
    """Deterministic simulation modes for adversarial and failure-scenario testing."""

    NORMAL = "NORMAL"
    TIMEOUT = "TIMEOUT"
    TRANSIENT_ERROR = "TRANSIENT_ERROR"
    TERMINAL_ERROR = "TERMINAL_ERROR"
    UNCERTAIN_TIMEOUT = "UNCERTAIN_TIMEOUT"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    DELAYED_CONFIRMATION = "DELAYED_CONFIRMATION"


class MockDRUNIXAdapter(DRUNIXAdapter):
    """In-memory simulator implementing the DRUNIXAdapter interface.

    Allows deterministic testing of network partitions, transient failures,
    timeouts, uncertain submissions, duplicate idempotency hits, and reconciliation.
    """

    is_simulator: bool = True

    def __init__(self, endpoint_url: str = "http://localhost:9000") -> None:
        self.endpoint_url = endpoint_url
        self._records: dict[str, dict[str, Any]] = {}
        self._records_by_commitment: dict[str, dict[str, Any]] = {}
        self._simulation_mode: MockSimulationMode = MockSimulationMode.NORMAL
        self._available: bool = True
        self._sequence_counter: int = 1000
        self._call_count: int = 0

    def set_simulation_mode(self, mode: MockSimulationMode | str) -> None:
        """Set deterministic behavior for subsequent adapter calls."""
        if isinstance(mode, str):
            mode = MockSimulationMode(mode)
        self._simulation_mode = mode
        logger.info("MockDRUNIXAdapter simulation mode changed to: %s", mode.value)

    def set_availability(self, available: bool) -> None:
        """Toggle simulated node liveness."""
        self._available = available

    async def is_available(self) -> bool:
        """Simulate liveness probe."""
        return self._available

    def _generate_tx_hash(self, record_id: str, commitment_hash: str) -> str:
        """Generate deterministic transaction hash based on record identifier and commitment."""
        content = f"drunix:mock:{record_id}:{commitment_hash}"
        return f"0x{hashlib.sha256(content.encode('utf-8')).hexdigest()}"

    async def record_authorization_attestation(
        self,
        record_id: str,
        commitment_hash: str,
        payload_summary: dict[str, Any] | None = None,
    ) -> DRUNIXReceipt:
        """Record authorization attestation under the active simulation mode."""
        return await self._process_submission(
            record_id=record_id,
            commitment_hash=commitment_hash,
            submission_type="AUTH_ATTESTATION",
            payload_summary=payload_summary,
        )

    async def publish_shared_fraud_indicator(
        self,
        indicator_id: str,
        payload_hash: str,
        payload_summary: dict[str, Any] | None = None,
    ) -> DRUNIXReceipt:
        """Publish shared fraud indicator under the active simulation mode."""
        return await self._process_submission(
            record_id=indicator_id,
            commitment_hash=payload_hash,
            submission_type="FRAUD_INDICATOR",
            payload_summary=payload_summary,
        )

    async def _process_submission(
        self,
        record_id: str,
        commitment_hash: str,
        submission_type: str,
        payload_summary: dict[str, Any] | None = None,
    ) -> DRUNIXReceipt:
        """Execute submission with simulated adversarial failures."""
        self._call_count += 1

        if not self._available:
            raise DRUNIXTransientError("Simulated DRUNIX node unavailable (liveness probe down).")

        # 1. Deterministic simulation modes
        if self._simulation_mode == MockSimulationMode.TIMEOUT:
            raise DRUNIXTimeoutError("Simulated DRUNIX request timeout before node dispatch.")

        if self._simulation_mode == MockSimulationMode.TRANSIENT_ERROR:
            raise DRUNIXTransientError("Simulated DRUNIX transient error (node busy / rate limit).")

        if self._simulation_mode == MockSimulationMode.TERMINAL_ERROR:
            raise DRUNIXTerminalError("Simulated DRUNIX permanent rejection (invalid payload/key).")

        if self._simulation_mode == MockSimulationMode.MALFORMED_RESPONSE:
            raise DRUNIXMalformedResponseError(
                "Simulated DRUNIX malformed or corrupt response payload."
            )

        # Check for duplicate idempotency
        if record_id in self._records:
            existing = self._records[record_id]
            logger.debug(
                "Mock DRUNIX returning existing duplicate receipt for record: %s", record_id
            )
            return DRUNIXReceipt(
                tx_hash=existing["tx_hash"],
                status="ACKNOWLEDGED",
                record_id=record_id,
                commitment_hash=existing["commitment_hash"],
                block_or_sequence=existing["sequence"],
                recorded_at=existing["recorded_at"],
                adapter_name="mock_drunix_simulator",
                raw_response={"duplicate": True, "tx_hash": existing["tx_hash"]},
            )

        # Generate receipt
        tx_hash = self._generate_tx_hash(record_id, commitment_hash)
        now = datetime.now(UTC)
        self._sequence_counter += 1
        seq = self._sequence_counter

        record_entry = {
            "tx_hash": tx_hash,
            "record_id": record_id,
            "commitment_hash": commitment_hash,
            "submission_type": submission_type,
            "payload_summary": payload_summary or {},
            "sequence": seq,
            "recorded_at": now.isoformat(),
            "status": "CONFIRMED",
            "is_simulator": True,
        }

        # 2. Uncertain timeout: Record is successfully written in external node,
        # but network timeout occurs while returning receipt to client!
        if self._simulation_mode == MockSimulationMode.UNCERTAIN_TIMEOUT:
            self._records[record_id] = record_entry
            self._records_by_commitment[commitment_hash] = record_entry
            raise DRUNIXUncertainOutcomeError(
                "Simulated post-dispatch network partition: submission was committed on node, "
                "but response connection timed out before client receipt."
            )

        # Normal or delayed confirmation recording
        self._records[record_id] = record_entry
        self._records_by_commitment[commitment_hash] = record_entry

        receipt_status = (
            "PENDING_CONFIRMATION"
            if self._simulation_mode == MockSimulationMode.DELAYED_CONFIRMATION
            else "ACKNOWLEDGED"
        )

        return DRUNIXReceipt(
            tx_hash=tx_hash,
            status=receipt_status,
            record_id=record_id,
            commitment_hash=commitment_hash,
            block_or_sequence=seq,
            recorded_at=now,
            adapter_name="mock_drunix_simulator",
            raw_response={"mock": True, "sequence": seq, "status": receipt_status},
        )

    async def verify_attestation(
        self,
        receipt_reference: str,
        expected_hash: str,
    ) -> bool:
        """Validate that external state matches expected commitment hash."""
        for rec in self._records.values():
            if rec["tx_hash"] == receipt_reference or rec["record_id"] == receipt_reference:
                return bool(rec["commitment_hash"] == expected_hash)
        return False

    async def retrieve_record(self, record_id: str) -> dict[str, Any] | None:
        """Retrieve stored simulated transaction record for reconciliation."""
        return self._records.get(record_id)

    def get_call_count(self) -> int:
        """Return total calls handled by the adapter."""
        return self._call_count

    def clear(self) -> None:
        """Reset simulator state."""
        self._records.clear()
        self._records_by_commitment.clear()
        self._simulation_mode = MockSimulationMode.NORMAL
        self._available = True
        self._call_count = 0
