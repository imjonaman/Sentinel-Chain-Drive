"""Agent management endpoints."""

import uuid

from fastapi import APIRouter, Depends, Header, Query, status

from sentinel_chain_drive.api.deps import get_agent_service
from sentinel_chain_drive.core.errors import AppException
from sentinel_chain_drive.db.models.agent import AgentStatus
from sentinel_chain_drive.schemas.agent import (
    AgentCreate,
    AgentKeyRotation,
    AgentListResponse,
    AgentResponse,
    AgentStatusUpdate,
    AgentUpdate,
)
from sentinel_chain_drive.services.agent_service import AgentService

router = APIRouter(prefix="/institutions/{institution_id}/agents", tags=["Agents"])


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
    response_model=AgentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new AI agent",
    description=(
        "Register an AI agent with an Ed25519 public verification key and metadata. "
        "Agents are initially created in PENDING_APPROVAL status."
    ),
)
async def register_agent(
    institution_id: uuid.UUID,
    data: AgentCreate,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    agent_service: AgentService = Depends(get_agent_service),
) -> AgentResponse:
    _check_institution_boundary(institution_id, x_institution_id)
    if data.institution_id is None:
        data.institution_id = institution_id
    actor = f"institution_{x_institution_id}" if x_institution_id else "api_client"
    return await agent_service.register_agent(
        institution_id=institution_id,
        data=data,
        actor=actor,
    )


@router.get(
    "/{agent_id}",
    response_model=AgentResponse,
    status_code=status.HTTP_200_OK,
    summary="Get agent metadata",
    description="Retrieve an agent by its unique identifier scoped to the owning institution.",
)
async def get_agent(
    institution_id: uuid.UUID,
    agent_id: uuid.UUID,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    agent_service: AgentService = Depends(get_agent_service),
) -> AgentResponse:
    _check_institution_boundary(institution_id, x_institution_id)
    return await agent_service.get_agent(
        institution_id=institution_id,
        agent_id=agent_id,
    )


@router.get(
    "",
    response_model=AgentListResponse,
    status_code=status.HTTP_200_OK,
    summary="List agents",
    description="Retrieve a paginated list of agents within the institution scope.",
)
async def list_agents(
    institution_id: uuid.UUID,
    status_filter: AgentStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    agent_service: AgentService = Depends(get_agent_service),
) -> AgentListResponse:
    _check_institution_boundary(institution_id, x_institution_id)
    return await agent_service.list_agents(
        limit=limit,
        offset=offset,
        institution_id=institution_id,
        agent_status=status_filter,
    )


@router.patch(
    "/{agent_id}",
    response_model=AgentResponse,
    status_code=status.HTTP_200_OK,
    summary="Update agent metadata",
    description="Update non-sensitive descriptive metadata for an agent.",
)
async def update_agent(
    institution_id: uuid.UUID,
    agent_id: uuid.UUID,
    data: AgentUpdate,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    agent_service: AgentService = Depends(get_agent_service),
) -> AgentResponse:
    _check_institution_boundary(institution_id, x_institution_id)
    actor = f"institution_{x_institution_id}" if x_institution_id else "api_client"
    return await agent_service.update_agent(
        institution_id=institution_id,
        agent_id=agent_id,
        data=data,
        actor=actor,
    )


@router.post(
    "/{agent_id}/status",
    response_model=AgentResponse,
    status_code=status.HTTP_200_OK,
    summary="Transition agent lifecycle status",
    description=(
        "Transition an agent's lifecycle state (e.g. PENDING_APPROVAL -> ACTIVE, "
        "ACTIVE -> SUSPENDED, ACTIVE -> REVOKED). REVOKED is terminal and non-reversible."
    ),
)
async def update_agent_status(
    institution_id: uuid.UUID,
    agent_id: uuid.UUID,
    data: AgentStatusUpdate,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    agent_service: AgentService = Depends(get_agent_service),
) -> AgentResponse:
    _check_institution_boundary(institution_id, x_institution_id)
    actor = f"institution_{x_institution_id}" if x_institution_id else "api_client"
    return await agent_service.update_agent_status(
        institution_id=institution_id,
        agent_id=agent_id,
        data=data,
        actor=actor,
    )


@router.post(
    "/{agent_id}/rotate-key",
    response_model=AgentResponse,
    status_code=status.HTTP_200_OK,
    summary="Rotate agent verification key",
    description="Rotate the Ed25519 public verification key and increment key version.",
)
async def rotate_agent_key(
    institution_id: uuid.UUID,
    agent_id: uuid.UUID,
    data: AgentKeyRotation,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    agent_service: AgentService = Depends(get_agent_service),
) -> AgentResponse:
    _check_institution_boundary(institution_id, x_institution_id)
    actor = f"institution_{x_institution_id}" if x_institution_id else "api_client"
    return await agent_service.rotate_agent_key(
        institution_id=institution_id,
        agent_id=agent_id,
        data=data,
        actor=actor,
    )
