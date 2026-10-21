"""Asynchronous outbox worker service for reliable DRUNIX ledger delivery.

Implements bounded exponential backoff with jitter, circuit breaker fault isolation,
safe lock recovery, idempotent delivery, strict payload validation, stream ordering,
and post-timeout reconciliation.
"""

import logging
import random
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.db.models.drunix_outbox import (
    DrunixEventType,
    DrunixOutboxEvent,
    DrunixOutboxStatus,
)
from sentinel_chain_drive.integrations.drunix import (
    CircuitBreaker,
    DRUNIXAdapter,
    DRUNIXMalformedResponseError,
    DRUNIXReceipt,
    DRUNIXTerminalError,
    DRUNIXTimeoutError,
    DRUNIXTransientError,
    DRUNIXUncertainOutcomeError,
    get_drunix_adapter,
)
from sentinel_chain_drive.repositories.drunix_outbox_repository import DrunixOutboxRepository
from sentinel_chain_drive.schemas.events import (
    SensitivePayloadDataError,
    UnsupportedSchemaVersionError,
    validate_event_payload,
)

logger = logging.getLogger(__name__)


class DrunixWorkerService:
    """Worker service executing durable, asynchronous delivery of outbox events to DRUNIX."""

    def __init__(
        self,
        session: AsyncSession,
        adapter: DRUNIXAdapter | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        worker_id: str | None = None,
        base_backoff_seconds: float = 1.0,
        max_backoff_seconds: float = 60.0,
        backoff_multiplier: float = 2.0,
        enable_jitter: bool = True,
        backpressure_threshold: int = 500,
    ) -> None:
        self.session = session
        self.outbox_repo = DrunixOutboxRepository(session)
        self.adapter = adapter or get_drunix_adapter()
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self.worker_id = worker_id or f"drunix_worker_{uuid.uuid4().hex[:8]}"
        self.base_backoff_seconds = base_backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self.backoff_multiplier = backoff_multiplier
        self.enable_jitter = enable_jitter
        self.backpressure_threshold = backpressure_threshold
        self._last_successful_processing_time: datetime | None = None
        self._latency_samples: list[float] = []

    def calculate_backoff_delay(self, attempt_count: int) -> float:
        """Calculate bounded exponential backoff delay with optional jitter."""
        attempt = max(1, attempt_count)
        delay = self.base_backoff_seconds * (self.backoff_multiplier ** (attempt - 1))
        delay = min(self.max_backoff_seconds, delay)
        if self.enable_jitter:
            jitter_factor = random.uniform(0.8, 1.2)
            delay = delay * jitter_factor
        return max(0.1, delay)

    def _record_latency(self, latency_ms: float) -> None:
        """Record processing latency in sliding window."""
        self._latency_samples.append(latency_ms)
        if len(self._latency_samples) > 100:
            self._latency_samples.pop(0)

    def get_average_latency_ms(self) -> float:
        """Calculate rolling average latency of event delivery."""
        if not self._latency_samples:
            return 0.0
        return sum(self._latency_samples) / len(self._latency_samples)

    @property
    def backpressure_active(self) -> bool:
        """Check if worker circuit breaker or queue state requires backpressure."""
        return not self.circuit_breaker.can_execute()

    async def process_batch(
        self,
        batch_size: int = 10,
        stale_lock_seconds: int = 300,
    ) -> int:
        """Claim and process a batch of eligible outbox events."""
        if not self.circuit_breaker.can_execute():
            logger.warning(
                "DRUNIX worker '%s' skipped batch: Circuit Breaker is %s",
                self.worker_id,
                self.circuit_breaker.state.value,
            )
            return 0

        claimed_events = await self.outbox_repo.claim_pending_events(
            worker_id=self.worker_id,
            batch_size=batch_size,
            stale_lock_seconds=stale_lock_seconds,
        )

        if not claimed_events:
            return 0

        delivered_count = 0
        for event in claimed_events:
            success = await self._process_single_event(event)
            if success:
                delivered_count += 1

        return delivered_count

    async def _process_single_event(self, event: DrunixOutboxEvent) -> bool:
        """Process an individual event with strict contract validation and error handling."""
        now = datetime.now(UTC)
        start_time = time.perf_counter()

        # 1. Strict payload contract validation and prohibited sensitive key rejection
        try:
            validate_event_payload(
                event_type=str(event.event_type),
                schema_version=event.schema_version,
                payload=event.payload,
            )
        except (UnsupportedSchemaVersionError, SensitivePayloadDataError, Exception) as val_err:
            logger.error(
                "Event %s failed contract validation: %s. Marking TERMINAL_FAILURE.",
                event.id,
                val_err,
            )
            await self.outbox_repo.record_terminal_failure(
                event_id=event.id,
                error_category="CONTRACT_VALIDATION_FAILURE",
                error_message=str(val_err)[:1000],
            )
            return False

        # 2. Delivery dispatch
        try:
            receipt: DRUNIXReceipt
            event_type_str = str(event.event_type)

            if event_type_str == DrunixEventType.AUTH_ATTESTATION:
                receipt = await self.adapter.record_authorization_attestation(
                    record_id=str(event.aggregate_id),
                    commitment_hash=event.commitment_hash,
                    payload_summary=event.payload,
                )
            elif event_type_str == DrunixEventType.FRAUD_INDICATOR:
                receipt = await self.adapter.publish_shared_fraud_indicator(
                    indicator_id=str(event.aggregate_id),
                    payload_hash=event.commitment_hash,
                    payload_summary=event.payload,
                )
            elif event_type_str == DrunixEventType.SETTLEMENT_RECORD:
                receipt = await self.adapter.record_authorization_attestation(
                    record_id=str(event.aggregate_id),
                    commitment_hash=event.commitment_hash,
                    payload_summary=event.payload,
                )
            else:
                # Internal domain or fraud intelligence event: record delivery directly
                receipt = DRUNIXReceipt(
                    tx_hash=f"internal_{event.id.hex[:12]}",
                    status="DELIVERED",
                    record_id=str(event.id),
                    commitment_hash=event.commitment_hash,
                    block_or_sequence=0,
                    recorded_at=now,
                    raw_response={"internal_dispatch": True, "event_type": event_type_str},
                )

            # Successful delivery
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            self._record_latency(elapsed_ms)
            self.circuit_breaker.record_success()
            await self.outbox_repo.record_delivery(
                event_id=event.id,
                receipt_reference=receipt.tx_hash,
                receipt_data=receipt.raw_response,
            )
            self._last_successful_processing_time = now
            logger.info(
                "Event %s delivered successfully. Receipt ref: %s (latency: %.2fms)",
                event.id,
                receipt.tx_hash,
                elapsed_ms,
            )
            return True

        except DRUNIXUncertainOutcomeError as exc:
            # External outcome is uncertain: do not assume failed, flag for reconciliation
            logger.warning(
                "Event %s delivery status uncertain: %s. Flagging for reconciliation.",
                event.id,
                exc.message,
            )
            self.circuit_breaker.record_failure(is_transient=True)
            await self.outbox_repo.record_reconciliation_required(
                event_id=event.id,
                error_category="UNCERTAIN_OUTCOME",
                error_message=exc.message,
            )
            return False

        except (DRUNIXTimeoutError, DRUNIXTransientError) as exc:
            # Retryable error
            self.circuit_breaker.record_failure(is_transient=True)
            delay = self.calculate_backoff_delay(event.attempt_count + 1)
            next_attempt_at = now + timedelta(seconds=delay)
            logger.warning(
                "Event %s transient delivery failure: %s. Rescheduling for %s UTC",
                event.id,
                exc.message,
                next_attempt_at.isoformat(),
            )
            await self.outbox_repo.record_retryable_failure(
                event_id=event.id,
                error_category="TRANSIENT_FAILURE",
                error_message=exc.message,
                next_attempt_at=next_attempt_at,
            )
            return False

        except (DRUNIXTerminalError, DRUNIXMalformedResponseError) as exc:
            # Permanent rejection: do not retry
            self.circuit_breaker.record_failure(is_transient=False)
            logger.error(
                "Event %s permanently rejected: %s",
                event.id,
                exc.message,
            )
            await self.outbox_repo.record_terminal_failure(
                event_id=event.id,
                error_category="TERMINAL_REJECTION",
                error_message=exc.message,
            )
            return False

        except Exception as exc:
            # Unexpected system error: schedule retry with backoff
            self.circuit_breaker.record_failure(is_transient=True)
            delay = self.calculate_backoff_delay(event.attempt_count + 1)
            next_attempt_at = now + timedelta(seconds=delay)
            logger.exception("Unexpected exception delivering event %s: %s", event.id, exc)
            await self.outbox_repo.record_retryable_failure(
                event_id=event.id,
                error_category="UNEXPECTED_ERROR",
                error_message=str(exc),
                next_attempt_at=next_attempt_at,
            )
            return False

    async def reconcile_event(self, event_id: uuid.UUID) -> bool:
        """Attempt to resolve an uncertain event by querying the external adapter."""
        event = await self.outbox_repo.get_by_id(event_id)
        if event is None:
            return False

        if event.status != DrunixOutboxStatus.RECONCILIATION_REQUIRED:
            return False

        record_id = str(event.aggregate_id)
        external_record = await self.adapter.retrieve_record(record_id)

        if external_record is not None:
            # External record found: verify commitment hash matches
            ext_commitment = external_record.get("commitment_hash")
            if ext_commitment == event.commitment_hash:
                tx_hash = external_record.get("tx_hash", "0x_reconciled")
                await self.outbox_repo.record_delivery(
                    event_id=event.id,
                    receipt_reference=tx_hash,
                    receipt_data={"reconciled": True, "external_record": external_record},
                )
                logger.info(
                    "Reconciliation succeeded for event %s. Resolved to DELIVERED.",
                    event.id,
                )
                return True
            else:
                await self.outbox_repo.record_terminal_failure(
                    event_id=event.id,
                    error_category="RECONCILIATION_COMMITMENT_MISMATCH",
                    error_message=(
                        "External record commitment does not match outbox event commitment."
                    ),
                )
                return False

        # Record not found externally
        if event.attempt_count >= event.max_attempts:
            await self.outbox_repo.record_terminal_failure(
                event_id=event.id,
                error_category="RECONCILIATION_NOT_FOUND_MAX_EXCEEDED",
                error_message=(
                    "Reconciliation failed to find record on external node after max attempts."
                ),
            )
            return False

        # Reschedule next reconciliation attempt
        delay = self.calculate_backoff_delay(event.attempt_count + 1)
        next_attempt = datetime.now(UTC) + timedelta(seconds=delay)
        event.next_attempt_at = next_attempt
        await self.session.flush()
        return False

    async def replay_failed_event(
        self,
        event_id: uuid.UUID,
        requesting_institution_id: uuid.UUID | None,
        actor: str = "system",
        reason: str = "Manual operator replay",
    ) -> DrunixOutboxEvent:
        """Controlled replay of an eligible failed event."""
        return await self.outbox_repo.replay_event(
            event_id=event_id,
            requesting_institution_id=requesting_institution_id,
            actor=actor,
            reason=reason,
        )

    async def replay_batch(
        self,
        requesting_institution_id: uuid.UUID,
        actor: str = "system",
        reason: str = "Batch operator replay",
        event_ids: list[uuid.UUID] | None = None,
        limit: int | None = None,
    ) -> int:
        """Batch replay of eligible failed outbox events."""
        return await self.outbox_repo.replay_batch(
            requesting_institution_id=requesting_institution_id,
            actor=actor,
            reason=reason,
            event_ids=event_ids,
            limit=limit,
        )

    async def get_status_overview(
        self,
        institution_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Provide sanitized operational metrics for monitoring endpoints."""
        outbox_metrics = await self.outbox_repo.get_metrics(institution_id=institution_id)
        is_node_available = await self.adapter.is_available()
        avg_latency = self.get_average_latency_ms()
        backpressure = self.backpressure_active or (
            outbox_metrics["total_pending"] >= self.backpressure_threshold
        )

        return {
            "worker_id": self.worker_id,
            "adapter_type": "simulator" if getattr(self.adapter, "is_simulator", False) else "live",
            "node_available": is_node_available,
            "circuit_breaker": self.circuit_breaker.to_dict(),
            "outbox": outbox_metrics,
            "average_processing_latency_ms": round(avg_latency, 2),
            "backpressure_active": backpressure,
            "last_successful_processing_time": (
                self._last_successful_processing_time.isoformat()
                if self._last_successful_processing_time
                else None
            ),
        }
