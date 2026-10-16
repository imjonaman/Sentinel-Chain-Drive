"""Simulated transaction gateway endpoints."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, Query, Response, status
from fastapi.responses import JSONResponse

from sentinel_chain_drive.api.deps import get_banking_service
from sentinel_chain_drive.db.models.transaction import TransactionStatus
from sentinel_chain_drive.schemas.transaction import (
    TransactionListResponse,
    TransactionResponse,
    TransactionSimulationActionRequest,
    TransactionSubmitRequest,
)
from sentinel_chain_drive.services.banking_service import BankingService

router = APIRouter(prefix="/transactions", tags=["Transactions"])


@router.post(
    "",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Transaction newly submitted and placed into PENDING_AUTHORIZATION."},
        200: {"description": "Idempotent duplicate submission matched existing transaction."},
        409: {"description": "Idempotency key collision with conflicting transaction payload."},
    },
    summary="Submit a simulated transaction",
    description=(
        "Submits a simulated transaction between accounts. Enforces idempotency, "
        "decimal precision, and places the transaction into PENDING_AUTHORIZATION state. "
        "Does NOT authorize or settle."
    ),
)
async def submit_transaction(
    data: TransactionSubmitRequest,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    x_correlation_id: str | None = Header(default=None),
    banking_service: BankingService = Depends(get_banking_service),
) -> Response:
    tx_resp, is_new = await banking_service.submit_transaction(
        data=data,
        actor="api_client",
        correlation_id=x_correlation_id,
        requesting_institution_id=x_institution_id,
    )
    status_code = status.HTTP_201_CREATED if is_new else status.HTTP_200_OK
    return JSONResponse(
        status_code=status_code,
        content=tx_resp.model_dump(mode="json"),
    )


@router.get(
    "",
    response_model=TransactionListResponse,
    status_code=status.HTTP_200_OK,
    summary="List transactions",
    description=(
        "Retrieve a paginated list of transactions with optional institution, status, "
        "and date filters."
    ),
)
async def list_transactions(
    institution_id: uuid.UUID | None = Query(default=None),
    status_filter: TransactionStatus | None = Query(default=None, alias="status"),
    from_time: datetime | None = Query(default=None),
    to_time: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    banking_service: BankingService = Depends(get_banking_service),
) -> TransactionListResponse:
    return await banking_service.list_transactions(
        limit=limit,
        offset=offset,
        institution_id=institution_id,
        status_filter=status_filter,
        from_time=from_time,
        to_time=to_time,
        requesting_institution_id=x_institution_id,
    )


@router.get(
    "/{transaction_id}",
    response_model=TransactionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get transaction details",
    description=(
        "Retrieve transaction details by internal UUID identifier including its complete "
        "status history."
    ),
)
async def get_transaction(
    transaction_id: uuid.UUID,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    banking_service: BankingService = Depends(get_banking_service),
) -> TransactionResponse:
    return await banking_service.get_transaction(
        transaction_id=transaction_id,
        requesting_institution_id=x_institution_id,
    )


@router.post(
    "/{transaction_id}/simulate-action",
    response_model=TransactionResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute simulation lifecycle action",
    description=(
        "Explicitly transitions a simulated transaction's lifecycle state (SIMULATE_SETTLE, "
        "SIMULATE_HOLD, SIMULATE_REJECT, CANCEL) and appends an immutable status history record."
    ),
)
async def execute_simulation_action(
    transaction_id: uuid.UUID,
    data: TransactionSimulationActionRequest,
    x_correlation_id: str | None = Header(default=None),
    banking_service: BankingService = Depends(get_banking_service),
) -> TransactionResponse:
    return await banking_service.execute_simulation_action(
        transaction_id=transaction_id,
        data=data,
        actor="simulation_operator",
        correlation_id=x_correlation_id,
    )
