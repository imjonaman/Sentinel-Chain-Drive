"""Health check endpoints for container orchestrators and external monitoring probes."""

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse

from sentinel_chain_drive.api.deps import get_system_service
from sentinel_chain_drive.schemas.health import HealthLiveResponse, HealthReadyResponse
from sentinel_chain_drive.services.system_service import SystemService

router = APIRouter(prefix="/health", tags=["Health"])


@router.get(
    "/live",
    response_model=HealthLiveResponse,
    status_code=status.HTTP_200_OK,
    summary="Application liveness probe",
    description="Confirms that the application process is running and responding.",
)
async def get_live(
    system_service: SystemService = Depends(get_system_service),
) -> HealthLiveResponse:
    return system_service.check_liveness()


@router.get(
    "/ready",
    response_model=HealthReadyResponse,
    responses={
        200: {"description": "Application and all critical dependencies are ready."},
        503: {"description": "One or more critical dependencies are unavailable or failing."},
    },
    summary="Application readiness probe",
    description="Validates application readiness and database connectivity.",
)
async def get_ready(
    system_service: SystemService = Depends(get_system_service),
) -> Response:
    health_data, is_ready = await system_service.check_readiness()
    status_code = status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(
        status_code=status_code,
        content=health_data.model_dump(mode="json"),
    )
