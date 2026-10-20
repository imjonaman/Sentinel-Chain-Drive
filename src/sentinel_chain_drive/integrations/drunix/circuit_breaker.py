"""Bounded-failure Circuit Breaker for DRUNIX ledger operations.

Protects against retry storms, cascading failures, and resource exhaustion
when external DRUNIX nodes experience downtime or latency spikes.
"""

import enum
import time
from dataclasses import dataclass
from typing import Any


class CircuitBreakerState(enum.StrEnum):
    """States of the circuit breaker."""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass(frozen=True)
class CircuitBreakerSnapshot:
    """Read-only snapshot of circuit breaker status for observability."""

    state: CircuitBreakerState
    consecutive_failures: int
    failure_threshold: int
    recovery_timeout_seconds: float
    last_failure_timestamp: float | None
    last_state_change: float


class CircuitBreaker:
    """Thread-safe circuit breaker implementation."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout_seconds: float = 30.0,
        half_open_success_threshold: int = 2,
    ) -> None:
        self.failure_threshold = max(1, failure_threshold)
        self.recovery_timeout_seconds = max(0.1, recovery_timeout_seconds)
        self.half_open_success_threshold = max(1, half_open_success_threshold)

        self._state = CircuitBreakerState.CLOSED
        self._consecutive_failures = 0
        self._consecutive_successes = 0
        self._last_failure_timestamp: float | None = None
        self._last_state_change = time.time()

    @property
    def state(self) -> CircuitBreakerState:
        """Current state, accounting for recovery timeout expiration."""
        now = time.time()
        if (
            self._state == CircuitBreakerState.OPEN
            and (now - self._last_state_change) >= self.recovery_timeout_seconds
        ):
            self._state = CircuitBreakerState.HALF_OPEN
            self._consecutive_successes = 0
            self._last_state_change = now
        return self._state

    def can_execute(self) -> bool:
        """Check whether requests are currently permitted to pass through."""
        current_state = self.state
        return current_state in (
            CircuitBreakerState.CLOSED,
            CircuitBreakerState.HALF_OPEN,
        )

    def record_success(self) -> None:
        """Record a successful external operation."""
        current_state = self.state
        now = time.time()

        if current_state == CircuitBreakerState.HALF_OPEN:
            self._consecutive_successes += 1
            if self._consecutive_successes >= self.half_open_success_threshold:
                self._state = CircuitBreakerState.CLOSED
                self._consecutive_failures = 0
                self._consecutive_successes = 0
                self._last_state_change = now
        elif current_state == CircuitBreakerState.CLOSED:
            self._consecutive_failures = 0

    def record_failure(self, is_transient: bool = True) -> None:
        """Record an operation failure. Only transient/timeout failures trip the breaker."""
        if not is_transient:
            # Terminal rejections do not indicate node outage
            return

        now = time.time()
        self._last_failure_timestamp = now
        self._consecutive_failures += 1
        current_state = self.state

        if current_state == CircuitBreakerState.HALF_OPEN:
            # Immediate trip back to OPEN on probe failure
            self._state = CircuitBreakerState.OPEN
            self._consecutive_successes = 0
            self._last_state_change = now
        elif (
            current_state == CircuitBreakerState.CLOSED
            and self._consecutive_failures >= self.failure_threshold
        ):
            self._state = CircuitBreakerState.OPEN
            self._last_state_change = now

    def reset(self) -> None:
        """Explicitly reset the circuit breaker to closed state."""
        self._state = CircuitBreakerState.CLOSED
        self._consecutive_failures = 0
        self._consecutive_successes = 0
        self._last_failure_timestamp = None
        self._last_state_change = time.time()

    def get_snapshot(self) -> CircuitBreakerSnapshot:
        """Return a read-only snapshot for telemetry and operational status."""
        return CircuitBreakerSnapshot(
            state=self.state,
            consecutive_failures=self._consecutive_failures,
            failure_threshold=self.failure_threshold,
            recovery_timeout_seconds=self.recovery_timeout_seconds,
            last_failure_timestamp=self._last_failure_timestamp,
            last_state_change=self._last_state_change,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize circuit breaker telemetry for operational APIs."""
        snapshot = self.get_snapshot()
        return {
            "state": snapshot.state.value,
            "consecutive_failures": snapshot.consecutive_failures,
            "failure_threshold": snapshot.failure_threshold,
            "recovery_timeout_seconds": snapshot.recovery_timeout_seconds,
            "last_failure_timestamp": snapshot.last_failure_timestamp,
            "last_state_change": snapshot.last_state_change,
        }
