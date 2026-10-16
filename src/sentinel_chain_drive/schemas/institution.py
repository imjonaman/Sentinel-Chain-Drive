"""Institution request and response schemas."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from sentinel_chain_drive.db.models.institution import InstitutionStatus


class InstitutionCreate(BaseModel):
    """Schema for registering a new simulated financial institution."""

    institution_code: str = Field(
        min_length=3,
        max_length=16,
        pattern=r"^[A-Z0-9_-]+$",
        description="Uppercase unique identifier (e.g., APEX_BANK)",
    )
    name: str = Field(
        min_length=2,
        max_length=128,
        description="Display name of the financial institution",
    )
    routing_identifier: str = Field(
        min_length=4,
        max_length=32,
        pattern=r"^[A-Z0-9]+$",
        description="Synthetic transit or BIC routing identifier",
    )
    settings: dict[str, Any] | None = Field(
        default=None,
        description="Optional simulation settings and policy thresholds",
    )


class InstitutionUpdate(BaseModel):
    """Schema for updating permitted institution metadata."""

    name: str | None = Field(
        default=None,
        min_length=2,
        max_length=128,
        description="Updated display name",
    )
    settings: dict[str, Any] | None = Field(
        default=None,
        description="Updated simulation settings",
    )


class InstitutionStatusUpdate(BaseModel):
    """Schema for lifecycle status changes."""

    status: InstitutionStatus = Field(
        description="Target lifecycle status (ACTIVE, SUSPENDED, INACTIVE)",
    )
    reason: str | None = Field(
        default=None,
        max_length=256,
        description="Operational rationale for status change",
    )


class InstitutionResponse(BaseModel):
    """Response model representing a financial institution."""

    id: uuid.UUID
    institution_code: str
    name: str
    routing_identifier: str
    status: InstitutionStatus
    settings: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InstitutionListResponse(BaseModel):
    """Paginated list response for institutions."""

    items: list[InstitutionResponse]
    total: int
    limit: int
    offset: int
