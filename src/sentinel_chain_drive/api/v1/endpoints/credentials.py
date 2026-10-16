"""Credential management and cryptographic authorization verification endpoints."""

import uuid

from fastapi import APIRouter, Depends, Header, Query, status

from sentinel_chain_drive.api.deps import get_agent_service
from sentinel_chain_drive.core.errors import AppException
from sentinel_chain_drive.schemas.credential import (
    AuthorizationVerificationRequest,
    AuthorizationVerificationResponse,
    CredentialIssueRequest,
    CredentialListResponse,
    CredentialResponse,
    CredentialRevocationRequest,
)
from sentinel_chain_drive.services.agent_service import AgentService

credentials_router = APIRouter(
    prefix="/institutions/{institution_id}/credentials",
    tags=["Credentials"],
)
authorizations_router = APIRouter(
    prefix="/authorizations",
    tags=["Authorizations"],
)


def _check_institution_boundary(
    path_institution_id: uuid.UUID, header_institution_id: uuid.UUID | None
) -> None:
    if header_institution_id is not None and header_institution_id != path_institution_id:
        raise AppException(
            message="Header X-Institution-ID does not match institution ID in path or request.",
            status_code=status.HTTP_403_FORBIDDEN,
            error_code="CROSS_INSTITUTION_ACCESS_FORBIDDEN",
        )


@credentials_router.post(
    "",
    response_model=CredentialResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Issue or register an agent credential",
    description="Issue a cryptographic credential signed for an active AI agent.",
)
async def issue_credential(
    institution_id: uuid.UUID,
    data: CredentialIssueRequest,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    agent_service: AgentService = Depends(get_agent_service),
) -> CredentialResponse:
    _check_institution_boundary(institution_id, x_institution_id)
    actor = f"institution_{x_institution_id}" if x_institution_id else "api_client"
    return await agent_service.issue_credential(
        institution_id=institution_id,
        data=data,
        actor=actor,
    )


@credentials_router.get(
    "/{credential_id}",
    response_model=CredentialResponse,
    status_code=status.HTTP_200_OK,
    summary="Get credential metadata",
    description="Retrieve credential metadata and revocation status by credential ID.",
)
async def get_credential(
    institution_id: uuid.UUID,
    credential_id: str,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    agent_service: AgentService = Depends(get_agent_service),
) -> CredentialResponse:
    _check_institution_boundary(institution_id, x_institution_id)
    return await agent_service.get_credential(
        institution_id=institution_id,
        credential_id=credential_id,
    )


@credentials_router.get(
    "",
    response_model=CredentialListResponse,
    status_code=status.HTTP_200_OK,
    summary="List credentials",
    description=(
        "List credentials scoped to the institution with optional agent or revocation filters."
    ),
)
async def list_credentials(
    institution_id: uuid.UUID,
    agent_id: uuid.UUID | None = Query(default=None),
    is_revoked: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    agent_service: AgentService = Depends(get_agent_service),
) -> CredentialListResponse:
    _check_institution_boundary(institution_id, x_institution_id)
    return await agent_service.list_credentials(
        limit=limit,
        offset=offset,
        agent_id=agent_id,
        institution_id=institution_id,
        is_revoked=is_revoked,
    )


@credentials_router.post(
    "/{credential_id}/revoke",
    response_model=CredentialResponse,
    status_code=status.HTTP_200_OK,
    summary="Revoke an agent credential",
    description="Immediately revoke an agent credential so it is rejected upon verification.",
)
async def revoke_credential(
    institution_id: uuid.UUID,
    credential_id: str,
    data: CredentialRevocationRequest,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    agent_service: AgentService = Depends(get_agent_service),
) -> CredentialResponse:
    _check_institution_boundary(institution_id, x_institution_id)
    actor = f"institution_{x_institution_id}" if x_institution_id else "api_client"
    return await agent_service.revoke_credential(
        institution_id=institution_id,
        credential_id=credential_id,
        reason=data.reason,
        actor=actor,
    )


@authorizations_router.post(
    "/verify",
    response_model=AuthorizationVerificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify cryptographic authorization request",
    description=(
        "Fail-closed evaluation verifying Ed25519 signature, single-use replay nonce, "
        "timestamp freshness, agent lifecycle state, credential validity, and "
        "capability boundary compliance."
    ),
)
async def verify_authorization(
    data: AuthorizationVerificationRequest,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    agent_service: AgentService = Depends(get_agent_service),
) -> AuthorizationVerificationResponse:
    _check_institution_boundary(data.institution_id, x_institution_id)
    actor = f"institution_{x_institution_id}" if x_institution_id else "verification_gateway"
    return await agent_service.verify_authorization(
        req=data,
        actor=actor,
    )
