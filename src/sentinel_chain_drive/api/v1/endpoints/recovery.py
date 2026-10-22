"""API endpoints for Controlled Recovery Request Orchestration (Phase 9 Feature 9.4)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status

from sentinel_chain_drive.api.deps import get_recovery_service
from sentinel_chain_drive.core.errors import AppException
from sentinel_chain_drive.db.models.recovery import RecoveryStatus
from sentinel_chain_drive.schemas.recovery import (
    RecoveryAcknowledgeRequest,
    RecoveryApprovalRequest,
    RecoveryListResponse,
    RecoveryReconcileRequest,
    RecoveryRejectionRequest,
    RecoveryResponse,
    RecoveryStatusHistoryResponse,
    RecoverySubmissionRequest,
)
from sentinel_chain_drive.services.recovery_service import RecoveryService

router = APIRouter(prefix="/recovery-requests", tags=["Recovery Orchestration"])


def _require_institution_id(x_institution_id: uuid.UUID | None) -> uuid.UUID:
    """Validate that the caller provided an authorized institution tenant context."""
    if x_institution_id is None:
        raise AppException(
            message="Header X-Institution-ID is required for tenant isolation.",
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="MISSING_INSTITUTION_CONTEXT",
        )
    return x_institution_id


@router.get(
    "",
    response_model=RecoveryListResponse,
    status_code=status.HTTP_200_OK,
    summary="List recovery requests",
    description=(
        "Retrieve paginated recovery requests for caller's institution with status filtering."
    ),
)
async def list_recovery_requests(
    recovery_status: RecoveryStatus | None = Query(
        default=None, alias="status", description="Filter by status"
    ),
    limit: int = Query(default=50, ge=1, le=100, description="Items per page"),
    offset: int = Query(default=0, ge=0, description="Items to skip"),
    x_institution_id: Annotated[uuid.UUID | None, Header(alias="X-Institution-ID")] = None,
    service: RecoveryService = Depends(get_recovery_service),
) -> RecoveryListResponse:
    institution_id = _require_institution_id(x_institution_id)

    items, total = await service.list_requests(
        institution_id=institution_id,
        status=recovery_status,
        limit=limit,
        offset=offset,
    )

    page_number = (offset // limit) + 1 if limit > 0 else 1
    return RecoveryListResponse(
        items=[RecoveryResponse.model_validate(item) for item in items],
        total=total,
        page=page_number,
        page_size=limit,
    )


@router.get(
    "/{request_id}",
    response_model=RecoveryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get recovery request by ID",
    description="Retrieve details of a recovery request strictly scoped by institution.",
)
async def get_recovery_request(
    request_id: uuid.UUID,
    x_institution_id: Annotated[uuid.UUID | None, Header(alias="X-Institution-ID")] = None,
    service: RecoveryService = Depends(get_recovery_service),
) -> RecoveryResponse:
    institution_id = _require_institution_id(x_institution_id)

    req = await service.get_recovery_request(request_id=request_id, institution_id=institution_id)
    if req is None:
        raise AppException(
            message=f"Recovery request {request_id} not found in authorized institution scope.",
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="RECOVERY_REQUEST_NOT_FOUND",
        )
    return RecoveryResponse.model_validate(req)


@router.post(
    "/{request_id}/approve",
    response_model=RecoveryResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve recovery request (Dual Control)",
    description=(
        "Supervisor approval for recovery request. Enforces dual-control separation of duties."
    ),
)
async def approve_recovery_request(
    request_id: uuid.UUID,
    payload: RecoveryApprovalRequest,
    x_institution_id: Annotated[uuid.UUID | None, Header(alias="X-Institution-ID")] = None,
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-ID")] = None,
    x_actor_role: Annotated[str | None, Header(alias="X-Actor-Role")] = None,
    service: RecoveryService = Depends(get_recovery_service),
) -> RecoveryResponse:
    institution_id = _require_institution_id(x_institution_id)
    approver_id = x_actor_id or "supervisor_user"

    approved = await service.approve_recovery_request(
        request_id=request_id,
        institution_id=institution_id,
        payload=payload,
        approver_id=approver_id,
        approver_role=x_actor_role or "SUPERVISOR",
    )
    return RecoveryResponse.model_validate(approved)


@router.post(
    "/{request_id}/reject",
    response_model=RecoveryResponse,
    status_code=status.HTTP_200_OK,
    summary="Reject recovery request",
    description="Rejects a draft or pending recovery request with recorded justification.",
)
async def reject_recovery_request(
    request_id: uuid.UUID,
    payload: RecoveryRejectionRequest,
    x_institution_id: Annotated[uuid.UUID | None, Header(alias="X-Institution-ID")] = None,
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-ID")] = None,
    service: RecoveryService = Depends(get_recovery_service),
) -> RecoveryResponse:
    institution_id = _require_institution_id(x_institution_id)
    rejected_by = x_actor_id or "supervisor_user"

    rejected = await service.reject_recovery_request(
        request_id=request_id,
        institution_id=institution_id,
        payload=payload,
        rejected_by=rejected_by,
    )
    return RecoveryResponse.model_validate(rejected)


@router.post(
    "/{request_id}/submit",
    response_model=RecoveryResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit recovery request to simulated inter-bank rails",
    description=(
        "Dispatches an approved recovery request via simulated rails with idempotency protection."
    ),
)
async def submit_recovery_request(
    request_id: uuid.UUID,
    payload: RecoverySubmissionRequest,
    x_institution_id: Annotated[uuid.UUID | None, Header(alias="X-Institution-ID")] = None,
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-ID")] = None,
    service: RecoveryService = Depends(get_recovery_service),
) -> RecoveryResponse:
    institution_id = _require_institution_id(x_institution_id)
    actor = x_actor_id or "operator_user"

    submitted = await service.submit_recovery_request(
        request_id=request_id,
        institution_id=institution_id,
        payload=payload,
        actor=actor,
    )
    return RecoveryResponse.model_validate(submitted)


@router.post(
    "/{request_id}/acknowledge",
    response_model=RecoveryResponse,
    status_code=status.HTTP_200_OK,
    summary="Acknowledge recovery request (Simulated Callback)",
    description=(
        "Simulates receiving external acknowledgement and tracking reference from target."
    ),
)
async def acknowledge_recovery_request(
    request_id: uuid.UUID,
    payload: RecoveryAcknowledgeRequest,
    x_institution_id: Annotated[uuid.UUID | None, Header(alias="X-Institution-ID")] = None,
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-ID")] = None,
    service: RecoveryService = Depends(get_recovery_service),
) -> RecoveryResponse:
    institution_id = _require_institution_id(x_institution_id)
    actor = x_actor_id or "counterparty_gateway"

    ack = await service.acknowledge_recovery_request(
        request_id=request_id,
        institution_id=institution_id,
        external_reference=payload.external_reference,
        actor=actor,
        notes=payload.notes,
    )
    return RecoveryResponse.model_validate(ack)


@router.post(
    "/{request_id}/reconcile",
    response_model=RecoveryResponse,
    status_code=status.HTTP_200_OK,
    summary="Reconcile uncertain outcome or settlement",
    description=(
        "Resolves uncertain outcome (OUTCOME_UNKNOWN) or settlement with mandatory explanation."
    ),
)
async def reconcile_recovery_request(
    request_id: uuid.UUID,
    payload: RecoveryReconcileRequest,
    x_institution_id: Annotated[uuid.UUID | None, Header(alias="X-Institution-ID")] = None,
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-ID")] = None,
    service: RecoveryService = Depends(get_recovery_service),
) -> RecoveryResponse:
    institution_id = _require_institution_id(x_institution_id)
    actor = x_actor_id or "reconciliation_officer"

    reconciled = await service.reconcile_recovery_request(
        request_id=request_id,
        institution_id=institution_id,
        payload=payload,
        actor=actor,
    )
    return RecoveryResponse.model_validate(reconciled)


@router.get(
    "/{request_id}/history",
    response_model=list[RecoveryStatusHistoryResponse],
    status_code=status.HTTP_200_OK,
    summary="Get recovery request transition history",
    description=("Retrieve immutable audit trail of recovery state transitions and actions."),
)
async def get_recovery_history(
    request_id: uuid.UUID,
    x_institution_id: Annotated[uuid.UUID | None, Header(alias="X-Institution-ID")] = None,
    service: RecoveryService = Depends(get_recovery_service),
) -> list[RecoveryStatusHistoryResponse]:
    institution_id = _require_institution_id(x_institution_id)

    req = await service.get_recovery_request(request_id=request_id, institution_id=institution_id)
    if req is None:
        raise AppException(
            message=f"Recovery request {request_id} not found in authorized institution scope.",
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="RECOVERY_REQUEST_NOT_FOUND",
        )

    history = await service.recovery_repo.get_request_history(recovery_request_id=request_id)
    return [RecoveryStatusHistoryResponse.model_validate(hr) for hr in history]
