"""Exception hierarchy for DRUNIX integration and adapter communication.

Distinguishes between retryable transient network/service failures, terminal validation
rejections, and uncertain delivery timeouts requiring external reconciliation.
"""

from sentinel_chain_drive.core.errors import AppException


class DRUNIXAdapterError(AppException):
    """Base exception for all DRUNIX adapter operations."""

    def __init__(
        self,
        message: str = "DRUNIX adapter error occurred.",
        status_code: int = 502,
        error_code: str = "DRUNIX_ADAPTER_ERROR",
    ) -> None:
        super().__init__(message=message, status_code=status_code, error_code=error_code)


class DRUNIXTimeoutError(DRUNIXAdapterError):
    """Temporary timeout communicating with the DRUNIX node before submission verification."""

    def __init__(self, message: str = "DRUNIX node connection or request timed out.") -> None:
        super().__init__(
            message=message,
            status_code=504,
            error_code="DRUNIX_TIMEOUT",
        )


class DRUNIXTransientError(DRUNIXAdapterError):
    """Retryable error (e.g. rate limit, node busy, connection reset)."""

    def __init__(
        self, message: str = "Temporary transient failure communicating with DRUNIX."
    ) -> None:
        super().__init__(
            message=message,
            status_code=503,
            error_code="DRUNIX_TRANSIENT_ERROR",
        )


class DRUNIXTerminalError(DRUNIXAdapterError):
    """Non-retryable terminal failure (e.g. malformed payload, signature invalid)."""

    def __init__(
        self, message: str = "Terminal failure: payload or request permanently rejected by DRUNIX."
    ) -> None:
        super().__init__(
            message=message,
            status_code=400,
            error_code="DRUNIX_TERMINAL_REJECTION",
        )


class DRUNIXUncertainOutcomeError(DRUNIXAdapterError):
    """Timeout or disconnect after dispatch where external acceptance cannot be confirmed."""

    def __init__(
        self,
        message: str = (
            "DRUNIX request status uncertain: transmission occurred but "
            "acknowledgement was not received."
        ),
    ) -> None:
        super().__init__(
            message=message,
            status_code=504,
            error_code="DRUNIX_UNCERTAIN_OUTCOME",
        )


class DRUNIXMalformedResponseError(DRUNIXTerminalError):
    """Adapter or gateway node returned invalid, corrupted, or untrusted response structure."""

    def __init__(
        self, message: str = "DRUNIX node returned invalid or malformed response."
    ) -> None:
        super().__init__(message=message)
        self.error_code = "DRUNIX_MALFORMED_RESPONSE"
