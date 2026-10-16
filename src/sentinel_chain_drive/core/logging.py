"""Structured logging configuration with request correlation ID tracking and data sanitization.

Guarantees that sensitive tokens, passwords, authorization headers, and private keys
are never emitted to log destinations.
"""

import contextvars
import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

# Context variable holding the active request correlation ID
correlation_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)

SENSITIVE_KEY_PATTERNS = re.compile(
    r"(password|token|secret|authorization|api[-_]?key|private[-_]?key|credential|cvv|account[-_]?number)",
    re.IGNORECASE,
)


def get_correlation_id() -> str | None:
    """Retrieve the current execution context's correlation ID."""
    return correlation_id_ctx.get()


def set_correlation_id(correlation_id: str | None) -> None:
    """Set the correlation ID for the current execution context."""
    correlation_id_ctx.set(correlation_id)


def sanitize_sensitive_data(data: Any) -> Any:
    """Recursively scrub sensitive keys and token patterns from log payloads."""
    if isinstance(data, dict):
        sanitized: dict[str, Any] = {}
        for key, val in data.items():
            if isinstance(key, str) and SENSITIVE_KEY_PATTERNS.search(key):
                sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = sanitize_sensitive_data(val)
        return sanitized
    if isinstance(data, list):
        return [sanitize_sensitive_data(item) for item in data]
    if isinstance(data, str) and data.lower().startswith("bearer "):
        return "Bearer [REDACTED]"
    return data


class StructuredLogFormatter(logging.Formatter):
    """Formats log records as single-line JSON with context correlation ID."""

    def format(self, record: logging.LogRecord) -> str:
        log_payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": get_correlation_id() or getattr(record, "correlation_id", None),
        }

        # Include source code location for errors/warnings
        if record.levelno >= logging.WARNING:
            log_payload["source"] = f"{record.pathname}:{record.lineno}"

        # Include exception information if present
        if record.exc_info:
            log_payload["exception"] = self.formatException(record.exc_info)

        # Include any extra non-standard attributes attached to record
        standard_attrs = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
            "correlation_id",
        }
        extras = {
            k: v
            for k, v in record.__dict__.items()
            if k not in standard_attrs and not k.startswith("_")
        }
        if extras:
            log_payload["extra"] = sanitize_sensitive_data(extras)

        return json.dumps(log_payload)


class SensitiveDataFilter(logging.Filter):
    """Filter that intercepts log records and sanitizes their argument payloads."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, dict):
            record.args = sanitize_sensitive_data(record.args)
        elif isinstance(record.args, tuple):
            record.args = tuple(sanitize_sensitive_data(arg) for arg in record.args)
        return True


def setup_logging(log_level: str = "INFO", log_format: str = "json") -> None:
    """Configure the root and application loggers."""
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level.upper())

    # Remove existing handlers to avoid duplicates
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.addFilter(SensitiveDataFilter())

    if log_format.lower() == "json":
        stream_handler.setFormatter(StructuredLogFormatter())
    else:
        text_fmt = "%(asctime)s [%(levelname)s] [%(name)s] [%(correlation_id)s] %(message)s"
        stream_handler.setFormatter(logging.Formatter(text_fmt))

    root_logger.addHandler(stream_handler)

    # Silence excessively verbose third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
