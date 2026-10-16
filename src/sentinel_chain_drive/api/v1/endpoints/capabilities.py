"""Capability governance endpoints."""

import uuid

from fastapi import APIRouter, Depends, Header, Query, status

from sentinel_chain_drive.api.deps import get_agent_service
from sentinel_chain_drive.core.errors import AppException
from sentinel_chain_drive.schemas.capability import (
    CapabilityCreate,
    CapabilityListResponse,
    CapabilityResponse,
    CapabilityUpdate,
)
from sentinel_chain_drive.services.agent_service import AgentService

router = APIRouter(prefix="/institutions/{institution_id}/capabilities", tags=["Capabilities"])


def _check_institution_boundary(
    path_institution_id: uuid.UUID, header_institution_id: uuid.UUID | None
) -> None:
    if header_institution_id is not None and header_institution_id != path_institution_id:
        raise AppException(
            message="Header X-Institution-ID does not match institution ID in path.",
            status_code=status.HTTP_403_FORBIDDEN,
            error_code="CROSS_INSTITUTION_ACCESS_FORBIDDEN",
        )


@router.post(
    "",
    response_model=CapabilityResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign capability boundary to an agent",
    description=(
        "Define authorization boundaries such as transaction types, single and daily "
        "cumulative limits, allowed accounts whitelist, and operating time windows."
    ),
)
async def create_capability(
    institution_id: uuid.UUID,
    data: CapabilityCreate,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    agent_service: AgentService = Depends(get_agent_service),
) -> CapabilityResponse:
    _check_institution_boundary(institution_id, x_institution_id)
    actor = f"institution_{x_institution_id}" if x_institution_id else "api_client"
    return await agent_service.create_capability(
        institution_id=institution_id,
        data=data,
        actor=actor,
    )


@router.get(
    "/{capability_id}",
    response_model=CapabilityResponse,
    status_code=status.HTTP_200_OK,
    summary="Get capability details",
    description="Retrieve a capability boundary by ID scoped to the institution.",
)
async def get_capability(
    institution_id: uuid.UUID,
    capability_id: uuid.UUID,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    agent_service: AgentService = Depends(get_agent_service),
) -> CapabilityResponse:
    _check_institution_boundary(institution_id, x_institution_id)
    return await agent_service.get_capability(
        institution_id=institution_id,
        capability_id=capability_id,
    )


@router.get(
    "",
    response_model=CapabilityListResponse,
    status_code=status.HTTP_200_OK,
    summary="List capabilities",
    description="List capability boundaries scoped to the institution with optional agent filter.",
)
async def list_capabilities(
    institution_id: uuid.UUID,
    agent_id: uuid.UUID | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    agent_service: AgentService = Depends(get_agent_service),
) -> CapabilityListResponse:
    _check_institution_boundary(institution_id, x_institution_id)
    return await agent_service.list_capabilities(
        limit=limit,
        offset=offset,
        agent_id=agent_id,
        institution_id=institution_id,
        is_active=is_active,
    )


@router.patch(
    "/{capability_id}",
    response_model=CapabilityResponse,
    status_code=status.HTTP_200_OK,
    summary="Update capability limits or status",
    description="Update bounds, whitelist accounts, or active status for a capability.",
)
async def update_capability(
    institution_id: uuid.UUID,
    capability_id: uuid.UUID,
    data: CapabilityUpdate,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    agent_service: AgentService = Depends(get_agent_service),
) -> CapabilityResponse:
    _check_institution_boundary(institution_id, x_institution_id)
    actor = f"institution_{x_institution_id}" if x_institution_id else "api_client"
    return await agent_service.update_capability(
        institution_id=institution_id,
        capability_id=capability_id,
        data=data,
        actor=actor,
    )
