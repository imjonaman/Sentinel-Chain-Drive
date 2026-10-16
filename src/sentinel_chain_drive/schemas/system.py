"""System metadata schemas."""

from typing import Literal

from pydantic import BaseModel, Field


class SystemInfoResponse(BaseModel):
    """Safe, non-sensitive application metadata and version information."""

    app_name: str = Field(
        description="Public human-readable application name.",
    )
    version: str = Field(
        description="Application semantic version.",
    )
    environment: Literal["development", "testing", "staging", "production"] = Field(
        description="Current runtime environment.",
    )
    api_version: str = Field(
        default="v1",
        description="Current API specification version.",
    )
    database_status: Literal["configured", "unconfigured"] = Field(
        default="configured",
        description="Database configuration status without revealing secrets.",
    )
    drunix_adapter_type: str = Field(
        description="Current configured DRUNIX integration adapter type.",
    )
