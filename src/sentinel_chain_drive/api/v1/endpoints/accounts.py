"""Account management endpoints."""

import uuid

from fastapi import APIRouter, Depends, Header, Query, status

from sentinel_chain_drive.api.deps import get_banking_service
from sentinel_chain_drive.db.models.account import AccountStatus
from sentinel_chain_drive.schemas.account import (
    AccountCreate,
    AccountListResponse,
    AccountResponse,
    AccountStatusUpdate,
)
from sentinel_chain_drive.services.banking_service import BankingService

router = APIRouter(prefix="/accounts", tags=["Accounts"])


@router.post(
    "",
    response_model=AccountResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a synthetic account",
    description="Create a synthetic account associated with an active financial institution.",
)
async def create_account(
    data: AccountCreate,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    x_correlation_id: str | None = Header(default=None),
    banking_service: BankingService = Depends(get_banking_service),
) -> AccountResponse:
    return await banking_service.create_account(
        data=data,
        actor="api_client",
        correlation_id=x_correlation_id,
        requesting_institution_id=x_institution_id,
    )


@router.get(
    "",
    response_model=AccountListResponse,
    status_code=status.HTTP_200_OK,
    summary="List synthetic accounts",
    description=(
        "Retrieve a paginated list of accounts with optional institution and status filters."
    ),
)
async def list_accounts(
    institution_id: uuid.UUID | None = Query(default=None),
    status_filter: AccountStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    banking_service: BankingService = Depends(get_banking_service),
) -> AccountListResponse:
    return await banking_service.list_accounts(
        limit=limit,
        offset=offset,
        institution_id=institution_id,
        status_filter=status_filter,
        requesting_institution_id=x_institution_id,
    )


@router.get(
    "/{account_id}",
    response_model=AccountResponse,
    status_code=status.HTTP_200_OK,
    summary="Get account details",
    description="Retrieve account details by internal UUID identifier.",
)
async def get_account(
    account_id: uuid.UUID,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    banking_service: BankingService = Depends(get_banking_service),
) -> AccountResponse:
    return await banking_service.get_account(
        account_id=account_id,
        requesting_institution_id=x_institution_id,
    )


@router.patch(
    "/{account_id}/status",
    response_model=AccountResponse,
    status_code=status.HTTP_200_OK,
    summary="Update account status",
    description=(
        "Update account operational status (ACTIVE, FROZEN, CLOSED) following valid "
        "lifecycle transitions."
    ),
)
async def update_account_status(
    account_id: uuid.UUID,
    data: AccountStatusUpdate,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    x_correlation_id: str | None = Header(default=None),
    banking_service: BankingService = Depends(get_banking_service),
) -> AccountResponse:
    return await banking_service.update_account_status(
        account_id=account_id,
        data=data,
        actor="api_client",
        correlation_id=x_correlation_id,
        requesting_institution_id=x_institution_id,
    )
