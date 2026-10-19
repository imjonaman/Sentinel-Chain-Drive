"""API endpoints for Phase 6 Privacy Gateway and cross-institution fraud intelligence."""

import uuid

from fastapi import APIRouter, Depends, Header, status

from sentinel_chain_drive.api.deps import get_privacy_gateway_service
from sentinel_chain_drive.core.errors import AppException
from sentinel_chain_drive.schemas.privacy import (
    IndicatorRevocationRequest,
    MeshIDQueryRequest,
    PrivacyAuditSummaryResponse,
    SharedIndicatorListResponse,
    SharedIndicatorPublishFromAlertRequest,
    SharedIndicatorPublishRequest,
    SharedIndicatorResponse,
)
from sentinel_chain_drive.services.privacy_gateway.service import PrivacyGatewayService

router = APIRouter(prefix="/privacy-gateway", tags=["Privacy Gateway"])


def _require_institution_id(x_institution_id: uuid.UUID | None) -> uuid.UUID:
    """Validate that the caller provided an authorized institution tenant context."""
    if x_institution_id is None:
        raise AppException(
            message=(
                "Header X-Institution-ID is required for "
                "cross-institution intelligence operations."
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="MISSING_INSTITUTION_CONTEXT",
        )

    return x_institution_id


@router.post(
    "/indicators/publish",
    response_model=SharedIndicatorResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Publish an eligible pre-sanitized fraud indicator",
    description=(
        "Publishes a privacy-preserving fraud indicator under strict field allowlist controls. "
        "The subject is identified solely via an epoch-keyed, purpose-bound MeshID."
    ),
)
async def publish_indicator(
    payload: SharedIndicatorPublishRequest,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    x_actor: str = Header(default="SIMULATED_INSTITUTION", alias="X-Actor"),
    x_correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
    service: PrivacyGatewayService = Depends(get_privacy_gateway_service),
) -> SharedIndicatorResponse:
    institution_id = _require_institution_id(x_institution_id)
    return await service.publish_indicator(
        request=payload,
        caller_institution_id=institution_id,
        actor=x_actor,
        correlation_id=x_correlation_id,
    )


@router.post(
    "/indicators/publish-from-alert",
    response_model=SharedIndicatorResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Sanitize and share an existing MuleChain fraud alert",
    description=(
        "Converts a localized MuleChain graph alert into a sanitized, non-sensitive "
        "cross-institution indicator. Account numbers are converted in-memory to MeshID "
        "and discarded."
    ),
)
async def publish_from_alert(
    payload: SharedIndicatorPublishFromAlertRequest,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    x_actor: str = Header(default="SIMULATED_INSTITUTION", alias="X-Actor"),
    x_correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
    service: PrivacyGatewayService = Depends(get_privacy_gateway_service),
) -> SharedIndicatorResponse:
    institution_id = _require_institution_id(x_institution_id)
    return await service.publish_from_alert(
        request=payload,
        caller_institution_id=institution_id,
        actor=x_actor,
        correlation_id=x_correlation_id,
    )


@router.post(
    "/indicators/query",
    response_model=SharedIndicatorListResponse,
    status_code=status.HTTP_200_OK,
    summary="Query active fraud indicators for a pseudonymous MeshID",
    description=(
        "Queries unexpired, active indicators matching a specific 64-hex MeshID. "
        "Enforces anti-enumeration rate limiting per institution. Wildcard queries are forbidden."
    ),
)
async def query_indicators_by_mesh_id(
    payload: MeshIDQueryRequest,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    x_actor: str = Header(default="SIMULATED_INSTITUTION", alias="X-Actor"),
    x_correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
    service: PrivacyGatewayService = Depends(get_privacy_gateway_service),
) -> SharedIndicatorListResponse:
    institution_id = _require_institution_id(x_institution_id)
    return await service.query_by_mesh_id(
        request=payload,
        caller_institution_id=institution_id,
        actor=x_actor,
        correlation_id=x_correlation_id,
    )


@router.get(
    "/indicators/{indicator_id}",
    response_model=SharedIndicatorResponse,
    status_code=status.HTTP_200_OK,
    summary="Get shared indicator by identifier",
    description=(
        "Retrieves a shared indicator if authorized for the caller institution "
        "(originator, direct recipient, or broadcast recipient)."
    ),
)
async def get_indicator_by_id(
    indicator_id: uuid.UUID,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    service: PrivacyGatewayService = Depends(get_privacy_gateway_service),
) -> SharedIndicatorResponse:
    institution_id = _require_institution_id(x_institution_id)
    return await service.get_indicator(
        indicator_id=indicator_id,
        caller_institution_id=institution_id,
    )


@router.post(
    "/indicators/{indicator_id}/revoke",
    response_model=SharedIndicatorResponse,
    status_code=status.HTTP_200_OK,
    summary="Revoke or withdraw a published indicator",
    description="Only the originating institution can revoke a previously published indicator.",
)
async def revoke_indicator(
    indicator_id: uuid.UUID,
    payload: IndicatorRevocationRequest,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    x_actor: str = Header(default="SIMULATED_INSTITUTION", alias="X-Actor"),
    x_correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
    service: PrivacyGatewayService = Depends(get_privacy_gateway_service),
) -> SharedIndicatorResponse:
    institution_id = _require_institution_id(x_institution_id)
    return await service.revoke_indicator(
        indicator_id=indicator_id,
        request=payload,
        caller_institution_id=institution_id,
        actor=x_actor,
        correlation_id=x_correlation_id,
    )


@router.get(
    "/audit-summary",
    response_model=PrivacyAuditSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve institution-scoped privacy audit summary",
    description=(
        "Returns aggregate counts and recent privacy audit events for the calling institution."
    ),
)
async def get_audit_summary(
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    service: PrivacyGatewayService = Depends(get_privacy_gateway_service),
) -> PrivacyAuditSummaryResponse:
    institution_id = _require_institution_id(x_institution_id)
    return await service.get_audit_summary(institution_id=institution_id)

