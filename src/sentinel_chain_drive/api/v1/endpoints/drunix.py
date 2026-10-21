"""API endpoints for DRUNIX ledger integration observability, event replay, and health."""

import uuid

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.api.deps import get_db_session
from sentinel_chain_drive.core.errors import AppException, EntityNotFoundException
from sentinel_chain_drive.schemas.drunix import (
    DrunixStatusResponse,
    OutboxEventDetailResponse,
    ReplayBatchRequest,
    ReplayBatchResponse,
    ReplayEventRequest,
    ReplayEventResponse,
)
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


@router.get(
    "/outbox/{event_id}",
    response_model=OutboxEventDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Inspect outbox event details",
    description="Returns sanitized status and delivery telemetry for a specific outbox event.",
)
async def get_outbox_event(
    event_id: uuid.UUID,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    session: AsyncSession = Depends(get_db_session),
) -> OutboxEventDetailResponse:
    worker = DrunixWorkerService(session=session)
    event = await worker.outbox_repo.get_by_id(event_id)
    if event is None:
        raise EntityNotFoundException("DrunixOutboxEvent", str(event_id))

    if x_institution_id is not None and event.institution_id != x_institution_id:
        raise AppException(
            message="Access to outbox event belonging to another institution is forbidden.",
            status_code=status.HTTP_403_FORBIDDEN,
            error_code="CROSS_INSTITUTION_ACCESS_FORBIDDEN",
        )

    return OutboxEventDetailResponse(
        id=event.id,
        institution_id=event.institution_id,
        event_type=str(event.event_type),
        event_category=event.event_category,
        schema_version=event.schema_version,
        aggregate_type=event.aggregate_type,
        aggregate_id=event.aggregate_id,
        idempotency_key=event.idempotency_key,
        commitment_hash=event.commitment_hash,
        status=event.status.value,
        attempt_count=event.attempt_count,
        max_attempts=event.max_attempts,
        replay_count=event.replay_count,
        ordering_key=event.ordering_key,
        sequence_number=event.sequence_number,
        correlation_id=event.correlation_id,
        causation_id=event.causation_id,
        error_category=event.error_category,
        last_error=event.last_error,
        receipt_reference=event.receipt_reference,
        created_at=event.created_at.isoformat() if event.created_at else None,
    )


@router.post(
    "/outbox/{event_id}/replay",
    response_model=ReplayEventResponse,
    status_code=status.HTTP_200_OK,
    summary="Replay an eligible failed outbox event",
    description=(
        "Resets a failed event to PENDING status with immediate retry eligibility. "
        "Enforces institution boundary authorization and audit record logging."
    ),
)
async def replay_outbox_event(
    event_id: uuid.UUID,
    request: ReplayEventRequest,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    session: AsyncSession = Depends(get_db_session),
) -> ReplayEventResponse:
    worker = DrunixWorkerService(session=session)
    replayed = await worker.replay_failed_event(
        event_id=event_id,
        requesting_institution_id=x_institution_id,
        actor="operator",
        reason=request.reason,
    )
    return ReplayEventResponse(
        event_id=replayed.id,
        status=replayed.status.value,
        replay_count=replayed.replay_count,
        message="Outbox event successfully re-queued for delivery.",
    )


@router.post(
    "/outbox/replay-batch",
    response_model=ReplayBatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Batch replay eligible failed events for an institution",
    description="Resets eligible terminal-failed events for the institution to PENDING.",
)
async def replay_outbox_batch(
    request: ReplayBatchRequest,
    x_institution_id: uuid.UUID = Header(alias="X-Institution-ID"),
    session: AsyncSession = Depends(get_db_session),
) -> ReplayBatchResponse:
    worker = DrunixWorkerService(session=session)
    count = await worker.replay_batch(
        requesting_institution_id=x_institution_id,
        actor="operator",
        reason=request.reason,
        event_ids=request.event_ids,
    )
    return ReplayBatchResponse(
        replayed_count=count,
        message=f"Successfully re-queued {count} failed event(s) for delivery.",
    )
