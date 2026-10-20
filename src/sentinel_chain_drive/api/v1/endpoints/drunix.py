"""API endpoints for DRUNIX ledger integration observability and operational health."""

import uuid

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.api.deps import get_db_session
from sentinel_chain_drive.schemas.drunix import DrunixStatusResponse
from sentinel_chain_drive.services.drunix_worker import DrunixWorkerService

router = APIRouter(prefix="/drunix", tags=["DRUNIX Ledger Integration"])


@router.get(
    "/status",
    response_model=DrunixStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Get DRUNIX integration and outbox operational status",
    description=(
        "Returns sanitized operational metrics for DRUNIX transactional outbox queues, "
        "circuit breaker state, and node connectivity. Does not expose credentials or payloads."
    ),
)
async def get_drunix_status(
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    session: AsyncSession = Depends(get_db_session),
) -> DrunixStatusResponse:
    worker = DrunixWorkerService(session=session)
    overview = await worker.get_status_overview(institution_id=x_institution_id)
    return DrunixStatusResponse.model_validate(overview)
