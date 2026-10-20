"""Abstract adapter specification for DRUNIX permissioned-ledger integration.

Isolates all future blockchain / distributed ledger operations behind a strict interface contract.
All external ledger attestations are asynchronous and decoupled from local synchronous
authorization.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class DRUNIXReceipt:
    """Standardized acknowledgement and commitment evidence returned by DRUNIX adapters."""

    tx_hash: str
    status: str
    record_id: str
    commitment_hash: str
    block_or_sequence: int | None = None
    recorded_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    adapter_name: str = "drunix_adapter"
    raw_response: dict[str, Any] | None = None


class DRUNIXAdapter(ABC):
    """Abstract interface defining required interactions with the DRUNIX platform."""

    @abstractmethod
    async def is_available(self) -> bool:
        """Check whether the DRUNIX gateway node is reachable and responsive."""
        pass

    @abstractmethod
    async def record_authorization_attestation(
        self,
        record_id: str,
        commitment_hash: str,
        payload_summary: dict[str, Any] | None = None,
    ) -> DRUNIXReceipt:
        """Submit a signed or hashed authorization decision record to the ledger.

        Args:
            record_id: Unique identifier for the authorization record.
            commitment_hash: Cryptographic commitment (SHA-256) of the authorized decision.
            payload_summary: Minimized, non-sensitive metadata for the attestation.

        Returns:
            DRUNIXReceipt containing the external transaction hash and commitment evidence.
        """
        pass

    @abstractmethod
    async def publish_shared_fraud_indicator(
        self,
        indicator_id: str,
        payload_hash: str,
        payload_summary: dict[str, Any] | None = None,
    ) -> DRUNIXReceipt:
        """Submit a privacy-preserving fraud indicator reference to the ledger.

        Args:
            indicator_id: Unique identifier for the shared indicator.
            payload_hash: Cryptographic hash of the indicator content.
            payload_summary: Non-sensitive topological attributes.

        Returns:
            DRUNIXReceipt containing transaction hash and commitment evidence.
        """
        pass

    @abstractmethod
    async def verify_attestation(
        self,
        receipt_reference: str,
        expected_hash: str,
    ) -> bool:
        """Validate that an on-chain commitment matches expected state.

        Args:
            receipt_reference: Transaction hash or receipt identifier to inspect.
            expected_hash: Expected cryptographic commitment hash.

        Returns:
            True if external state matches expected_hash, False otherwise.
        """
        pass

    @abstractmethod
    async def retrieve_record(self, record_id: str) -> dict[str, Any] | None:
        """Fetch a recorded state by record identifier for reconciliation."""
        pass

    # Backward-compatible Phase 1 methods
    async def record_authorization_state(
        self,
        decision_id: str,
        agent_id: str,
        decision: str,
        payload_hash: str,
    ) -> str:
        """Phase 1 legacy compatibility wrapper."""
        receipt = await self.record_authorization_attestation(
            record_id=decision_id,
            commitment_hash=payload_hash,
            payload_summary={"agent_id": agent_id, "decision": decision},
        )
        return receipt.tx_hash

    async def retrieve_authorization_record(self, record_id: str) -> dict[str, Any] | None:
        """Phase 1 legacy compatibility wrapper."""
        return await self.retrieve_record(record_id)
