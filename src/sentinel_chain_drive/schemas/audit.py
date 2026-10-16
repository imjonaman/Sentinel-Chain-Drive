"""Audit schemas for event creation and query responses."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AuditLogCreate(BaseModel):
    """Schema for recording a new audit log event."""

    event_type: str = Field(
        min_length=2,
        max_length=64,
        description="Categorical event classification.",
    )
    severity: str = Field(
        default="INFO",
        max_length=16,
        description="Severity level of the event (INFO, WARNING, ERROR, CRITICAL).",
    )
    actor: str = Field(
        default="system",
        max_length=128,
        description="Entity or agent responsible for the action.",
    )
    description: str = Field(
        min_length=1,
        max_length=500,
        description="Summary of the audited action.",
    )
    correlation_id: str | None = Field(
        default=None,
        max_length=64,
        description="Optional correlation ID linking to the triggering HTTP request.",
    )
    details: dict[str, Any] | None = Field(
        default=None,
        description="Optional structured diagnostic details.",
    )


class AuditLogResponse(BaseModel):
    """Schema for returning recorded audit log records."""

    id: uuid.UUID
    event_type: str
    severity: str
    actor: str
    description: str
    correlation_id: str | None
    details: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}
