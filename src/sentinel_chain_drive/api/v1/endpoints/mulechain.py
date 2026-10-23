"""API endpoints for MuleChain graph-based fraud intelligence."""

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from sentinel_chain_drive.api.deps import get_mulechain_service
from sentinel_chain_drive.core.errors import AppException
from sentinel_chain_drive.db.models.alert import (
    AlertSeverity,
    AlertStatus,
    DetectorType,
)
from sentinel_chain_drive.schemas.alert import (
    FraudAlertListResponse,
    FraudAlertResponse,
    MuleChainAnalysisRequest,
    MuleChainAnalysisSummary,
)
from sentinel_chain_drive.services.mulechain.mulechain_service import MuleChainService

router = APIRouter(prefix="/mulechain", tags=["MuleChain Fraud Intelligence"])


def _require_institution_id(x_institution_id: uuid.UUID | None) -> uuid.UUID:
    """Validate that the caller provided an authorized institution tenant context."""
    if x_institution_id is None:
        raise AppException(
            message="Header X-Institution-ID is required for multi-tenant graph intelligence.",
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="MISSING_INSTITUTION_CONTEXT",
        )
    return x_institution_id


@router.post(
    "/analyze",
    response_model=MuleChainAnalysisSummary,
    status_code=status.HTTP_200_OK,
    summary="Trigger MuleChain graph fraud analysis",
    description=(
        "Executes deterministic topological fraud detection over historical banking transactions "
        "within the caller's institution scope for a specified currency and time window."
    ),
)
async def analyze_transaction_graph(
    payload: MuleChainAnalysisRequest,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    service: MuleChainService = Depends(get_mulechain_service),
) -> MuleChainAnalysisSummary:
    institution_id = _require_institution_id(x_institution_id)

    try:
        return await service.run_analysis(
            institution_id=institution_id,
            currency=payload.currency,
            window_start=payload.window_start,
            window_end=payload.window_end,
            max_transactions=payload.max_transactions,
            include_detectors=payload.include_detectors,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(e),
        ) from e


@router.get(
    "/alerts/{alert_id}",
    response_model=FraudAlertResponse,
    status_code=status.HTTP_200_OK,
    summary="Get fraud alert by identifier",
    description=(
        "Retrieve full evidence and scoring details for an alert within the caller's "
        "authorized institution scope."
    ),
)
async def get_fraud_alert(
    alert_id: uuid.UUID,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    service: MuleChainService = Depends(get_mulechain_service),
) -> FraudAlertResponse:
    institution_id = _require_institution_id(x_institution_id)

    alert = await service.get_alert(alert_id=alert_id, institution_id=institution_id)
    if alert is None:
        raise AppException(
            message=f"Fraud alert {alert_id} not found in authorized institution scope.",
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="ALERT_NOT_FOUND",
        )

    return FraudAlertResponse.model_validate(alert)


@router.get(
    "/alerts",
    response_model=FraudAlertListResponse,
    status_code=status.HTTP_200_OK,
    summary="List fraud alerts",
    description=(
        "Retrieve paginated fraud alerts with optional pattern, severity, status, "
        "and account filtering."
    ),
)
async def list_fraud_alerts(
    detector_type: DetectorType | None = Query(
        default=None, description="Filter by detector pattern"
    ),
    severity: AlertSeverity | None = Query(default=None, description="Filter by severity level"),
    alert_status: AlertStatus | None = Query(
        default=None, alias="status", description="Filter by lifecycle status"
    ),
    account_id: uuid.UUID | None = Query(default=None, description="Filter by primary account"),
    limit: int = Query(default=50, ge=1, le=100, description="Items per page"),
    offset: int = Query(default=0, ge=0, description="Items to skip"),
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    service: MuleChainService = Depends(get_mulechain_service),
) -> FraudAlertListResponse:
    institution_id = _require_institution_id(x_institution_id)

    items, total = await service.list_alerts(
        institution_id=institution_id,
        limit=limit,
        offset=offset,
        detector_type=detector_type,
        severity=severity,
        status=alert_status,
        account_id=account_id,
    )

    page_number = (offset // limit) + 1 if limit > 0 else 1
    return FraudAlertListResponse(
        items=[FraudAlertResponse.model_validate(item) for item in items],
        total=total,
        page=page_number,
        page_size=limit,
    )
