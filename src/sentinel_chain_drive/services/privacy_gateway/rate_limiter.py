"""Anti-enumeration sliding-window rate limiter for the Privacy Gateway.

Prevents brute-force or bulk query enumeration of pseudonymous MeshIDs
across institutions by enforcing per-institution bounded query limits.
"""

import threading
from collections import deque
from datetime import UTC, datetime


class PrivacyQueryRateLimiter:
    """In-memory sliding window rate limiter for Privacy Gateway queries.

    Tracks query timestamps per institution over a rolling window.
    Thread-safe with bounded eviction to avoid memory growth.
    """

    def __init__(self, max_queries_per_window: int = 120, window_seconds: int = 60) -> None:
        self.max_queries = max_queries_per_window
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        self._history: dict[str, deque[float]] = {}

    def is_allowed(self, institution_id: str) -> tuple[bool, int]:
        """Check if institution is within query rate limits and record query if allowed.

        Returns:
            Tuple[bool, int]: (is_allowed, remaining_quota)
        """

        now = datetime.now(UTC).timestamp()
        cutoff = now - self.window_seconds

        with self._lock:
            if institution_id not in self._history:
                self._history[institution_id] = deque()

            window_deq = self._history[institution_id]

            # Evict timestamps older than cutoff
            while window_deq and window_deq[0] < cutoff:
                window_deq.popleft()

            if len(window_deq) >= self.max_queries:
                return False, 0

            window_deq.append(now)
            remaining = self.max_queries - len(window_deq)
            return True, remaining

    def reset_for_test(self, institution_id: str | None = None) -> None:
        """Helper for test suites to reset rate limiter history."""
        with self._lock:
            if institution_id:
                self._history.pop(institution_id, None)
            else:
                self._history.clear()
