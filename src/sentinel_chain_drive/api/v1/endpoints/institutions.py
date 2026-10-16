"""Institution management endpoints."""

import uuid

from fastapi import APIRouter, Depends, Header, Query, status

from sentinel_chain_drive.api.deps import get_banking_service
from sentinel_chain_drive.db.models.institution import InstitutionStatus
from sentinel_chain_drive.schemas.institution import (
    InstitutionCreate,
    InstitutionListResponse,
    InstitutionResponse,
    InstitutionStatusUpdate,
    InstitutionUpdate,
)
from sentinel_chain_drive.services.banking_service import BankingService

router = APIRouter(prefix="/institutions", tags=["Institutions"])


@router.post(
    "",
    response_model=InstitutionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new financial institution",
    description=(
        "Creates a simulated financial institution boundary with unique code and routing "
        "transit identifiers."
    ),
)
async def create_institution(
    data: InstitutionCreate,
    x_correlation_id: str | None = Header(default=None),
    banking_service: BankingService = Depends(get_banking_service),
) -> InstitutionResponse:
    return await banking_service.create_institution(
        data=data,
        actor="api_client",
        correlation_id=x_correlation_id,
    )


@router.get(
    "",
    response_model=InstitutionListResponse,
    status_code=status.HTTP_200_OK,
    summary="List financial institutions",
    description=(
        "Retrieve a paginated list of registered financial institutions with optional status "
        "filter."
    ),
)
async def list_institutions(
    status_filter: InstitutionStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    banking_service: BankingService = Depends(get_banking_service),
) -> InstitutionListResponse:
    return await banking_service.list_institutions(
        limit=limit,
        offset=offset,
        status_filter=status_filter,
    )


@router.get(
    "/{institution_id}",
    response_model=InstitutionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get institution details",
    description="Retrieve a registered institution by internal UUID identifier.",
)
async def get_institution(
    institution_id: uuid.UUID,
    banking_service: BankingService = Depends(get_banking_service),
) -> InstitutionResponse:
    return await banking_service.get_institution(institution_id=institution_id)


@router.patch(
    "/{institution_id}",
    response_model=InstitutionResponse,
    status_code=status.HTTP_200_OK,
    summary="Update institution metadata",
    description="Update permitted metadata attributes such as display name or simulation settings.",
)
async def update_institution(
    institution_id: uuid.UUID,
    data: InstitutionUpdate,
    x_correlation_id: str | None = Header(default=None),
    banking_service: BankingService = Depends(get_banking_service),
) -> InstitutionResponse:
    return await banking_service.update_institution(
        institution_id=institution_id,
        data=data,
        actor="api_client",
        correlation_id=x_correlation_id,
    )


@router.patch(
    "/{institution_id}/status",
    response_model=InstitutionResponse,
    status_code=status.HTTP_200_OK,
    summary="Update institution lifecycle status",
    description=(
        "Transition an institution's status (ACTIVE, SUSPENDED, INACTIVE) according to valid "
        "lifecycle rules."
    ),
)
async def update_institution_status(
    institution_id: uuid.UUID,
    data: InstitutionStatusUpdate,
    x_correlation_id: str | None = Header(default=None),
    banking_service: BankingService = Depends(get_banking_service),
) -> InstitutionResponse:
    return await banking_service.update_institution_status(
        institution_id=institution_id,
        data=data,
        actor="api_client",
        correlation_id=x_correlation_id,
    )
