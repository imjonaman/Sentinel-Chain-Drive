"""System metadata endpoints exposing safe diagnostic information."""

from fastapi import APIRouter, Depends, status

from sentinel_chain_drive.api.deps import get_system_service
from sentinel_chain_drive.schemas.system import SystemInfoResponse
from sentinel_chain_drive.services.system_service import SystemService

router = APIRouter(prefix="/system", tags=["System"])


@router.get(
    "/info",
    response_model=SystemInfoResponse,
    status_code=status.HTTP_200_OK,
    summary="Get safe system metadata",
    description="Returns public non-sensitive application metadata and runtime identifiers.",
)
async def get_system_info(
    system_service: SystemService = Depends(get_system_service),
) -> SystemInfoResponse:
    return system_service.get_system_info()
