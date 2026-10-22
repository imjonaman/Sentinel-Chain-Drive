"""API endpoints for Alert Triage and Workflow Management (Phase 9 Feature 9.1)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status

from sentinel_chain_drive.api.deps import get_case_service, get_mulechain_service
from sentinel_chain_drive.core.errors import AppException
from sentinel_chain_drive.db.models.alert import (
    AlertSeverity,
    AlertStatus,
    DetectorType,
)
from sentinel_chain_drive.db.models.case import CasePriority
from sentinel_chain_drive.schemas.alert import (
    AlertTriageRequest,
    AlertTriageResponse,
    FraudAlertListResponse,
    FraudAlertResponse,
)
from sentinel_chain_drive.schemas.case import CaseCreateRequest
from sentinel_chain_drive.services.case_service import CaseService
from sentinel_chain_drive.services.mulechain.mulechain_service import MuleChainService

router = APIRouter(prefix="/alerts", tags=["Alert Triage & Case Workflow"])


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
    response_model=FraudAlertListResponse,
    status_code=status.HTTP_200_OK,
    summary="Filter alerts by severity, status, institution, and date",
    description=(
        "Retrieve paginated fraud alerts with multi-dimensional filtering "
        "strictly scoped by tenant."
    ),
)
async def list_alerts_for_triage(
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
    x_institution_id: Annotated[uuid.UUID | None, Header(alias="X-Institution-ID")] = None,
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


@router.patch(
    "/{alert_id}/triage",
    response_model=AlertTriageResponse,
    status_code=status.HTTP_200_OK,
    summary="Assign, escalate, dismiss, or open a case from an alert",
    description=(
        "Triage an alert: transition lifecycle status, escalate severity, or trigger case opening."
    ),
)
async def triage_alert(
    alert_id: uuid.UUID,
    payload: AlertTriageRequest,
    x_institution_id: Annotated[uuid.UUID | None, Header(alias="X-Institution-ID")] = None,
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-ID")] = None,
    x_actor_role: Annotated[str | None, Header(alias="X-Actor-Role")] = None,
    mule_service: MuleChainService = Depends(get_mulechain_service),
    case_service: CaseService = Depends(get_case_service),
) -> AlertTriageResponse:
    institution_id = _require_institution_id(x_institution_id)
    actor = x_actor_id or "system_analyst"

    alert = await mule_service.get_alert(alert_id=alert_id, institution_id=institution_id)
    if alert is None:
        raise AppException(
            message=f"Fraud alert {alert_id} not found in authorized institution scope.",
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="ALERT_NOT_FOUND",
        )

    # 1. Update status or escalated severity on alert
    updated_alert = await mule_service.alert_repo.update_triage(
        alert_id=alert_id,
        institution_id=institution_id,
        status=payload.status,
        severity=payload.escalate_severity,
    )
    current_alert = updated_alert or alert

    # 2. Automated case creation if requested
    case_id: uuid.UUID | None = None
    case_number: str | None = None
    triage_notes = [f"Alert triaged by {actor}"]

    if payload.status:
        triage_notes.append(f"Status updated to {payload.status.value}")
    if payload.escalate_severity:
        triage_notes.append(
            f"Severity escalated to {payload.escalate_severity.value} "
            f"(Reason: {payload.escalation_reason})"
        )

    if payload.create_case:
        priority_map = {
            AlertSeverity.LOW: CasePriority.LOW,
            AlertSeverity.MEDIUM: CasePriority.MEDIUM,
            AlertSeverity.HIGH: CasePriority.HIGH,
            AlertSeverity.CRITICAL: CasePriority.CRITICAL,
        }
        mapped_priority = priority_map.get(current_alert.severity, CasePriority.MEDIUM)

        case_req = CaseCreateRequest(
            summary=f"Case from Alert: {current_alert.alert_code} ({current_alert.severity.value})",
            description=payload.notes
            or f"Created via alert triage. Detector: {current_alert.detector_type.value}.",
            priority=mapped_priority,
            risk_score=current_alert.risk_score,
            assigned_analyst_id=payload.assigned_analyst_id,
            assigned_role=x_actor_role or "INVESTIGATOR",
            source_type="FRAUD_ALERT",
            source_id=str(current_alert.id),
            alert_ids=[current_alert.id],
            account_ids=[current_alert.primary_account_id]
            if current_alert.primary_account_id
            else [],
        )
        case = await case_service.create_case(
            institution_id=institution_id,
            payload=case_req,
            actor=actor,
            actor_role=x_actor_role,
        )
        case_id = case.id
        case_number = case.case_number
        triage_notes.append(f"Associated investigation case created: {case.case_number}")

    return AlertTriageResponse(
        alert=FraudAlertResponse.model_validate(current_alert),
        case_id=case_id,
        case_number=case_number,
        triage_summary="; ".join(triage_notes),
    )
